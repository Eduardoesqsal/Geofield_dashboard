"""Servicio principal de procesamiento raster.

Encapsula lectura de ortomosaicos, tiles, recortes, reproyección y cálculo de
índices espectrales completos o acotados al ROI.
"""

from __future__ import annotations

import io
import hashlib
import json
import logging
import re
import tempfile
from collections import deque
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import numpy as np
import pyproj
import rasterio
from affine import Affine
from PIL import Image
from rasterio.enums import ColorInterp, Resampling
from rasterio.errors import RasterioIOError
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.mask import mask as raster_mask
from rasterio.mask import raster_geometry_mask
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import Window, from_bounds, transform as window_transform
from shapely.affinity import rotate as rotate_geometry
from shapely.geometry import MultiLineString, Polygon, mapping
from shapely.ops import transform as project_geometry

from geofield.config import Settings
from geofield.errors import RasterNotConfiguredError
from geofield.services import raster_bands
from geofield.services import raster_cache
from geofield.services import raster_helpers
from geofield.services import raster_tiles
from geofield.services import raster_processing


logger = logging.getLogger(__name__)



class RasterIndexMixin:
    """Seleccion de bandas, colorizacion de indices y cache de ecualizacion."""

    def _ndvi_bands(
        self,
        path: Path | None = None,
        sensor: str | None = None,
        context: Any | None = None,
    ) -> tuple[int, int]:
        """Return the red and NIR band indexes configured in the raster."""
        selected_sensor = sensor or self._sensor_value(context)
        if selected_sensor == "mavic3m":
            with rasterio.open(path or self._path(context)) as src:
                if src.count < 4:
                    raise ValueError("DJI Mavic 3M requiere al menos 4 bandas: Green, Red, Red Edge y NIR.")
                # Exportación DJI/Pix4D habitual: Blue, Green, Red, RedEdge, NIR.
                # Algunos mosaicos omiten Blue y conservan: Green, Red, RedEdge, NIR.
                return 2, 4
        if selected_sensor == "micasense":
            with rasterio.open(path or self._path(context)) as src:
                names = {name.strip().lower(): index for index, name in enumerate(src.descriptions, 1) if name}
                red = next((names[name] for name in ("red", "red band", "b04", "band 4") if name in names), None)
                nir = next((names[name] for name in ("nir", "near infrared", "near-infrared", "b08", "band 6") if name in names), None)
                if red and nir:
                    return red, nir
                if src.count >= 6:
                    # Blue, Green, Pan, Red, RedEdge, NIR, Alpha.
                    return 4, 6
                if src.count >= 5:
                    # RedEdge-MX: Blue, Green, Red, NIR, RedEdge.
                    return 3, 4
                raise ValueError("MicaSense requiere bandas Red y NIR; el archivo tiene menos de 5 bandas.")
        with rasterio.open(path or self._path(context)) as src:
            names = {name.strip().lower(): index for index, name in enumerate(src.descriptions, 1) if name}
            red = next((names[name] for name in ("red", "b04", "band 4") if name in names), None)
            nir = next((names[name] for name in ("nir", "near infrared", "b08", "band 6") if name in names), None)
    
            # Pix4D multispectral exports commonly use Red=4 and NIR=6.
            if red is None and src.count >= 4:
                red = 4
            if nir is None and src.count >= 6:
                nir = 6
            if red is None or nir is None:
                raise ValueError(
                    f"El raster '{(path or self._path(context)).name}' no contiene bandas Red y NIR; "
                    f"tiene {src.count} banda(s): {', '.join(src.descriptions)}. "
                    "Para NDVI se requiere un GeoTIFF multiespectral."
                )
            return red, nir
    
    @staticmethod
    def _wavelength_nm(value: str) -> float | None:
        return raster_bands.wavelength_nm(value)
    
    @classmethod
    def _band_role_from_text(cls, value: str) -> str | None:
        return raster_bands.band_role_from_text(value)
    
    @staticmethod
    def _band_role_from_wavelength(wavelength_nm: float | None) -> str | None:
        return raster_bands.band_role_from_wavelength(wavelength_nm)
    
    @classmethod
    def _dataset_wavelengths(cls, src: Any) -> list[float] | None:
        return raster_bands.dataset_wavelengths(src)
    
    def _rgb_bands(
        self,
        src: Any | None = None,
        *,
        path: Path | None = None,
        sensor: str | None = None,
        context: Any | None = None,
    ) -> tuple[int, int, int]:
        """Resolve display bands from color interpretation and band metadata."""
        if src is None:
            with rasterio.open(path or self._path(context)) as dataset:
                return self._rgb_bands(dataset, sensor=sensor, context=context)
    
        roles: dict[str, int] = {}
        for index, interpretation in enumerate(src.colorinterp, 1):
            role = str(getattr(interpretation, "name", interpretation)).lower()
            if role in {"red", "green", "blue"}:
                roles.setdefault(role, index)
    
        dataset_wavelengths = self._dataset_wavelengths(src)
        for index in range(1, src.count + 1):
            description = src.descriptions[index - 1] or ""
            tags = src.tags(index)
            metadata_text = " ".join(
                [description, *[f"{key} {value}" for key, value in tags.items()]],
            )
            role = self._band_role_from_text(metadata_text)
            if role not in {"red", "green", "blue"}:
                wavelength = next(
                    (
                        self._wavelength_nm(str(value))
                        for key, value in tags.items()
                        if "wavelength" in key.lower()
                    ),
                    None,
                )
                if wavelength is None and dataset_wavelengths:
                    wavelength = dataset_wavelengths[index - 1]
                role = self._band_role_from_wavelength(wavelength)
            if role in {"red", "green", "blue"}:
                roles.setdefault(role, index)
    
        selected_sensor = sensor or self._sensor_value(context)
        is_multispectral = selected_sensor in {"mavic3m", "micasense"} or src.count > 4
        if not is_multispectral and src.count in {3, 4}:
            # A plain three-channel RGB GeoTIFF is the only safe positional
            # fallback. A fourth band is accepted only when it is Alpha.
            alpha_index = next(
                (
                    index
                    for index, interpretation in enumerate(src.colorinterp, 1)
                    if str(getattr(interpretation, "name", interpretation)).lower() == "alpha"
                ),
                None,
            )
            if src.count == 3 or alpha_index == 4:
                roles.setdefault("red", 1)
                roles.setdefault("green", 2)
                roles.setdefault("blue", 3)
        elif selected_sensor == "mavic3m" and src.count >= 4:
            # Mavic 3M has no true blue channel. Use Red, Green and Red edge
            # to keep the upload preview and overlay generation working.
            roles.setdefault("red", 2)
            roles.setdefault("green", 1)
            roles.setdefault("blue", 3)
    
        missing = [role for role in ("red", "green", "blue") if role not in roles]
        if missing:
            details = ", ".join(
                f"banda {index}: {src.descriptions[index - 1] or 'sin descripcion'}; tags={src.tags(index)}"
                for index in range(1, src.count + 1)
            )
            message = (
                f"No se pudieron identificar las bandas RGB del raster '{Path(src.name).name}'. "
                f"Faltan metadatos para: {', '.join(missing)}. {details}"
            )
            logger.error(message)
            raise ValueError(message)
        return roles["red"], roles["green"], roles["blue"]
    
    def _multispectral_band_roles(
        self,
        src: Any | None = None,
        *,
        path: Path | None = None,
        sensor: str | None = None,
        context: Any | None = None,
    ) -> dict[str, int]:
        """Resolve multispectral semantic roles for NDWI/NDRE style formulas."""
        if src is None:
            with rasterio.open(path or self._path(context)) as dataset:
                return self._multispectral_band_roles(dataset, sensor=sensor, context=context)
        return raster_bands.multispectral_band_roles(src, sensor=sensor, fallback_path=path)
    
    def _index_bands(self, name: str, context: Any | None = None) -> tuple[int, int]:
        """Return bands as (positive, negative) for the normalized difference."""
        if name == "NDVI":
            red, nir = self._ndvi_bands(context=context)
            return nir, red
        selected_sensor = self._sensor_value(context)
        if selected_sensor == "mavic3m":
            bands = {"NDWI": (1, 4), "NDRE": (4, 3)}.get(name)
        elif selected_sensor == "micasense":
            bands = {"NDWI": (2, 6), "NDRE": (6, 5)}.get(name)
        else:
            bands = None
        if not bands:
            raise ValueError("El indice requiere un ortomosaico multiespectral compatible.")
        return bands
    
    @staticmethod
    def _calculate_index(positive: np.ndarray, negative: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return raster_helpers.calculate_index(positive, negative)
    
    @classmethod
    def _index_color_lut(cls, name: str) -> np.ndarray:
        cached = cls._index_lut_cache.get(name)
        if cached is not None:
            return cached
        lut = np.empty((256, 4), dtype=np.uint8)
        positions = np.linspace(0.0, 1.0, 256, dtype=np.float32)
        lut[:, :3] = cls._sample_ramp(name, positions)
        lut[:, 3] = 255
        cls._index_lut_cache[name] = lut
        return lut
    
    @classmethod
    def _colorize_index(
        cls,
        name: str,
        values: np.ndarray,
        valid: np.ndarray,
        low: float | None = None,
        high: float | None = None,
        *,
        equalized: bool = False,
        fill_mode: str = "transparent",
        equalization_cdf: np.ndarray | None = None,
    ) -> np.ndarray:
        domain_minimum, domain_maximum = cls.INDEX_DOMAINS[name]
        safe_values = np.where(np.isfinite(values), values, domain_minimum)
        visible = valid & np.isfinite(values)
        range_low = domain_minimum if low is None else low
        range_high = domain_maximum if high is None else high
        range_low, range_high = sorted((range_low, range_high))
        in_range = (values >= range_low) & (values <= range_high)
        if fill_mode == "transparent":
            visible &= in_range
        display_position = np.clip(
            (
                (safe_values - range_low)
                / max(range_high - range_low, np.finfo(np.float32).eps)
                * 255
            ).round().astype(np.int16),
            0,
            255,
        )
        domain_position = np.clip(
            (
                (safe_values - domain_minimum)
                / max(domain_maximum - domain_minimum, np.finfo(np.float32).eps)
                * 255
            ).round().astype(np.int16),
            0,
            255,
        )
        if equalized and equalization_cdf is not None and equalization_cdf.size:
            raw_index = np.clip(
                (
                    (safe_values - range_low)
                    / max(range_high - range_low, np.finfo(np.float32).eps)
                    * (equalization_cdf.size - 1)
                ),
                0.0,
                float(equalization_cdf.size - 1),
            )
            lower_index = np.floor(raw_index).astype(np.int16)
            upper_index = np.ceil(raw_index).astype(np.int16)
            factor = raw_index - lower_index
            lower_value = equalization_cdf[lower_index]
            upper_value = equalization_cdf[upper_index]
            equalized_position = np.clip(
                np.round((lower_value + (upper_value - lower_value) * factor) * 255),
                0,
                255,
            ).astype(np.int16)
            position = np.where(in_range, equalized_position, display_position)
        else:
            position = domain_position
        rgba = cls._index_color_lut(name)[position].copy()
        rgba[..., 3] = np.where(visible, 255, 0).astype(np.uint8)
        return rgba
    
    @staticmethod
    def _response_index_values(name: str, response: dict[str, Any]) -> np.ndarray:
        return raster_helpers.response_index_values(name, response)
    
    @staticmethod
    def _build_equalization_cdf(
        values: np.ndarray,
        minimum: float,
        maximum: float,
        *,
        bin_count: int = 256,
    ) -> np.ndarray | None:
        return raster_helpers.build_equalization_cdf(
            values,
            minimum,
            maximum,
            bin_count=bin_count,
        )
    
    def _equalization_cache_key(
        self,
        name: str,
        crop_id: str | None,
        low: float | None,
        high: float | None,
    ) -> tuple[Any, ...]:
        active_path = str(self._path())
        return (
            active_path,
            self.sensor,
            name,
            crop_id,
            None if low is None else round(float(low), 6),
            None if high is None else round(float(high), 6),
        )
    
    def _cached_equalization_cdf(
        self,
        name: str,
        crop_id: str | None,
        low: float | None,
        high: float | None,
    ) -> np.ndarray | None:
        key = self._equalization_cache_key(name, crop_id, low, high)
        if key in self.equalization_cache:
            return self.equalization_cache[key]
        cdf = self._build_equalization_cdf(
            self._response_index_values(name, self._equalization_response(name, crop_id)),
            self.INDEX_DOMAINS[name][0] if low is None else low,
            self.INDEX_DOMAINS[name][1] if high is None else high,
        )
        self.equalization_cache[key] = cdf
        if len(self.equalization_cache) > self._equalization_cache_limit:
            oldest_key = next(iter(self.equalization_cache))
            self.equalization_cache.pop(oldest_key, None)
        return cdf
    
