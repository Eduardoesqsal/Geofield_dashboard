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



class RasterTileExportMixin:
    """Analisis de raster, tiles, recortes y respuestas de indices."""

    def analyze_uploaded(self, content: bytes, kind: str, filename: str = "upload.tif", sensor: str | None = None) -> dict[str, Any]:
        """Analyze one uploaded raster using the same RGB/NDVI preparation as the configured raster."""
        suffix = Path(filename).suffix.lower() or ".tif"
        uploaded_path = self.settings.output_dir / f"active_ortho{suffix}"
        if self.active_path and self.active_path != uploaded_path and self.active_path.parent == self.settings.output_dir:
            self.active_path.unlink(missing_ok=True)
        uploaded_path.write_bytes(content)
        self.active_path = uploaded_path
        self.sensor = sensor
        self.rgb_stretch = None
        self.overlay = None
        self.equalization_cache.clear()
        try:
            with rasterio.open(uploaded_path) as src:
                if src.count < 3:
                    raise ValueError("El ortomosaico debe contener al menos tres bandas.")
                max_pixels = self.settings.ndvi_max_pixels if kind == "multispectral" else self.settings.rgb_max_pixels
                scale = self.scale(src, max_pixels)
                source_height = max(1, src.height // scale)
                source_width = max(1, src.width // scale)
                source_transform = src.transform * Affine.scale(src.width / source_width, src.height / source_height)
                height, width = source_height, source_width
                profile = self.rgb_render_profile(src)
                rgb_bands = profile["bands"]
                rgb = src.read(
                    list(rgb_bands),
                    out_shape=(3, source_height, source_width),
                    resampling=Resampling.nearest,
                )
                mask = self._rgb_valid_mask(src, rgb_bands, rgb)
                red, green, blue = self._render_rgb_values(rgb, profile)
                if src.crs and src.crs.to_string() != "EPSG:4326":
                    transform, width, height = calculate_default_transform(src.crs, "EPSG:4326", width, height, *src.bounds)
                    projected = []
                    for band in (red, green, blue):
                        destination = np.zeros((height, width), dtype=np.uint8)
                        reproject(band, destination, src_transform=source_transform, src_crs=src.crs, dst_transform=transform, dst_crs="EPSG:4326", resampling=Resampling.bilinear)
                        projected.append(destination)
                    red, green, blue = projected
                    projected_mask = np.zeros((height, width), dtype=np.uint8)
                    reproject(
                        mask.astype(np.uint8),
                        projected_mask,
                        src_transform=source_transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs="EPSG:4326",
                        resampling=Resampling.nearest,
                    )
                    mask = projected_mask > 0
                bounds = array_bounds(height, width, transform if src.crs and src.crs.to_string() != "EPSG:4326" else src.transform * Affine.scale(src.width / width, src.height / height))
                response: dict[str, Any] = {
                    "status": "ok",
                    "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
                    "rgb_matrix": np.moveaxis(np.stack((red, green, blue)), 0, -1).tolist(),
                    "mask": mask.astype(np.uint8).tolist(),
                    "tile_version": self.tile_cache_version(uploaded_path),
                }
                if kind == "multispectral":
                    red_band, nir_band = self._ndvi_bands(uploaded_path, sensor)
                    ndvi_resampling = Resampling.nearest if sensor == "micasense" else Resampling.average
                    red_values = src.read(red_band, out_shape=(source_height, source_width), resampling=ndvi_resampling).astype(np.float32)
                    nir_values = src.read(nir_band, out_shape=(source_height, source_width), resampling=ndvi_resampling).astype(np.float32)
                    if src.crs and src.crs.to_string() != "EPSG:4326":
                        projected_values = []
                        for band in (red_values, nir_values):
                            destination = np.zeros((height, width), dtype=np.float32)
                            reproject(band, destination, src_transform=source_transform, src_crs=src.crs, src_nodata=src.nodata, dst_transform=transform, dst_crs="EPSG:4326", dst_nodata=0, resampling=ndvi_resampling)
                            projected_values.append(destination)
                        red_values, nir_values = projected_values
                    valid = (red_values > 0) & (nir_values > 0)
                    denominator = nir_values + red_values
                    ndvi = np.divide(nir_values - red_values, denominator, out=np.zeros_like(denominator), where=valid & (denominator != 0))
                    response["ndvi_matrix"] = (np.clip((ndvi + 1) / 2, 0, 1) * 255).astype(np.uint8).tolist()
                    response["mask"] = valid.astype(np.uint8).tolist()
                return response
        except Exception:
            raise
    
    @staticmethod
    def scale(src: Any, max_pixels: int) -> int:
        return raster_helpers.scale(src.width, src.height, max_pixels)
    
    @staticmethod
    def normalize(band: np.ndarray) -> np.ndarray:
        return raster_helpers.normalize_band(band)
    
    def _rgb_profile_key(self, path: Path | None = None) -> tuple[str, int, int]:
        return raster_cache.rgb_profile_key(path or self._path())
    
    def tile_cache_version(self, path: Path | None = None) -> str:
        """Return a browser cache key tied to both the file and renderer."""
        return raster_cache.tile_cache_version(path or self._path(), self.RGB_RENDER_VERSION)
    
    def index_tile_cache_version(self, path: Path | None = None) -> str:
        return raster_cache.index_tile_cache_version(path or self._path(), self.INDEX_RENDER_VERSION)
    
    def _tile_cache_path(
        self,
        kind: str,
        version: str,
        z: int,
        x: int,
        y: int,
        variant: str = "default",
    ) -> Path:
        return raster_cache.tile_cache_path(
            self.settings.cache_dir,
            self._path().resolve(),
            version,
            kind,
            z,
            x,
            y,
            variant,
        )
    
    @staticmethod
    def _read_tile_cache(cache_path: Path) -> bytes | None:
        return raster_cache.read_tile_cache(cache_path)
    
    @staticmethod
    def _write_tile_cache(cache_path: Path, content: bytes) -> None:
        raster_cache.write_tile_cache(cache_path, content)
    
    @staticmethod
    def _rgb_valid_mask(
        src: Any,
        bands: tuple[int, int, int],
        data: np.ndarray,
        *,
        window: Window | None = None,
        boundless: bool = False,
    ) -> np.ndarray:
        height, width = data.shape[1:]
        read_options: dict[str, Any] = {
            "out_shape": (len(bands), height, width),
            "resampling": Resampling.nearest,
        }
        mask_options: dict[str, Any] = {
            "out_shape": (height, width),
            "resampling": Resampling.nearest,
        }
        if window is not None:
            read_options["window"] = window
            mask_options["window"] = window
        if boundless:
            read_options["boundless"] = True
            mask_options["boundless"] = True
        band_masks = src.read_masks(list(bands), **read_options)
        dataset_mask = src.dataset_mask(**mask_options)
        finite = np.all(np.isfinite(data), axis=0)
        nonempty = np.any(data != 0, axis=0)
        return (
            np.all(band_masks > 0, axis=0)
            & (dataset_mask > 0)
            & finite
            & nonempty
        )
    
    def _calculate_rgb_profile(
        self,
        src: Any,
        bands: tuple[int, int, int],
    ) -> dict[str, Any]:
        if all(np.dtype(src.dtypes[index - 1]) == np.dtype("uint8") for index in bands):
            return {"mode": "original", "bands": bands, "ranges": None}
    
        scale = self.scale(src, self.settings.rgb_max_pixels)
        height = max(1, src.height // scale)
        width = max(1, src.width // scale)
        data = src.read(
            list(bands),
            out_shape=(len(bands), height, width),
            resampling=Resampling.nearest,
        ).astype(np.float64)
        valid = self._rgb_valid_mask(src, bands, data)
        if not np.any(valid):
            ranges = ((0.0, 1.0),) * 3
        else:
            ranges = tuple(
                tuple(float(value) for value in np.percentile(data[index][valid], [2, 98]))
                for index in range(3)
            )
        return {"mode": "global-stretch", "bands": bands, "ranges": ranges}
    
    def rgb_render_profile(self, src: Any | None = None) -> dict[str, Any]:
        """Resolve and cache one immutable color decision for the whole file."""
        if src is None:
            with rasterio.open(self._path()) as dataset:
                return self.rgb_render_profile(dataset)
        key = self._rgb_profile_key(Path(src.name))
        cached = self._rgb_profile_cache.get(key)
        if cached is not None:
            self.rgb_stretch = cached.get("ranges")
            return cached
        bands = self._rgb_bands(src)
        profile = self._calculate_rgb_profile(src, bands)
        self._rgb_profile_cache[key] = profile
        self.rgb_stretch = profile.get("ranges")
        return profile
    
    @staticmethod
    def _render_rgb_values(data: np.ndarray, profile: dict[str, Any]) -> np.ndarray:
        if profile["mode"] == "original":
            return data.astype(np.uint8, copy=False)
        rendered = np.zeros(data.shape, dtype=np.uint8)
        for index, (low, high) in enumerate(profile["ranges"]):
            if not np.isfinite(low) or not np.isfinite(high) or low == high:
                continue
            rendered[index] = (
                (np.clip(data[index].astype(np.float64), low, high) - low)
                / (high - low)
                * 255
            ).clip(0, 255).astype(np.uint8)
        return rendered
    
    def stretch_rgb(self, r: np.ndarray, g: np.ndarray, b: np.ndarray, limits: tuple[float, float] | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        stack = np.stack([r, g, b]).astype(np.float32)
        valid = np.any(stack > 0, axis=0)
        low, high = limits or (tuple(np.percentile(stack[:, valid].reshape(-1), [2, 98])) if np.any(valid) else (0, 1))
        if low == high:
            return tuple(np.zeros_like(band, dtype=np.uint8) for band in (r, g, b))  # type: ignore[return-value]
        def stretch(band: np.ndarray) -> np.ndarray:
            return ((np.clip(band.astype(np.float32), low, high) - low) / (high - low) * 255).clip(0, 255).astype(np.uint8)
        return stretch(r), stretch(g), stretch(b)
    
    def ensure_overlay(self) -> tuple[int, int, Affine]:
        if self.overlay:
            return self.overlay
        with rasterio.open(self._path()) as src:
            scale = self.scale(src, self.settings.rgb_max_pixels)
            height, width = max(1, src.height // scale), max(1, src.width // scale)
            self.rgb_render_profile(src)
            if src.crs and src.crs.to_string() != "EPSG:4326":
                transform, width, height = calculate_default_transform(src.crs, "EPSG:4326", width, height, *src.bounds)
            else:
                transform = src.transform * Affine.scale(src.width / width, src.height / height)
            self.overlay = (width, height, transform)
            bounds = array_bounds(height, width, transform)
            (self.settings.output_dir / "bounds_overlay.txt").write_text(repr([[bounds[1], bounds[0]], [bounds[3], bounds[2]]]), encoding="utf-8")
            return self.overlay
    
    @staticmethod
    def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
        return raster_tiles.tile_bounds(z, x, y)
    
    @staticmethod
    def tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
        return raster_tiles.tile_bounds_mercator(z, x, y)
    
    def _reproject_rgb_tile(
        self,
        src: Any,
        z: int,
        x: int,
        y: int,
    ) -> tuple[np.ndarray, np.ndarray, Affine]:
        mercator_bounds = self.tile_bounds_mercator(z, x, y)
        return raster_tiles.reproject_rgb_tile(
            src,
            z,
            x,
            y,
            tile_size=self.RGB_TILE_SIZE,
            mercator_bounds=mercator_bounds,
            rgb_render_profile=self.rgb_render_profile,
            rgb_valid_mask=self._rgb_valid_mask,
            render_rgb_values=self._render_rgb_values,
        )
    
    def _reproject_index_matrix(
        self,
        src: Any,
        name: str,
        z: int,
        x: int,
        y: int,
    ) -> tuple[np.ndarray, np.ndarray, Affine]:
        mercator_bounds = self.tile_bounds_mercator(z, x, y)
        return raster_tiles.reproject_index_matrix(
            src,
            name,
            z,
            x,
            y,
            tile_size=self.RGB_TILE_SIZE,
            mercator_bounds=mercator_bounds,
            index_bands=self._index_bands,
            calculate_index=self._calculate_index,
        )
    
    def tile(self, kind: str, z: int, x: int, y: int, low: float = -0.05, high: float = 1.0) -> bytes:
        if kind == "rgb":
            cache_path = self._tile_cache_path(
                "rgb",
                self.tile_cache_version(),
                z,
                x,
                y,
            )
            cached = self._read_tile_cache(cache_path)
            if cached is not None:
                return cached
        elif kind == "ndvi":
            cache_path = self._tile_cache_path(
                "ndvi",
                self.index_tile_cache_version(),
                z,
                x,
                y,
                variant=f"{low:.4f}-{high:.4f}",
            )
            cached = self._read_tile_cache(cache_path)
            if cached is not None:
                return cached
        else:
            raise ValueError(f"Tipo de tile no soportado: {kind}")
    
        with rasterio.open(self._path()) as src:
            if kind == "rgb":
                rendered, valid, _transform = self._reproject_rgb_tile(src, z, x, y)
                rgba = np.dstack(
                    (*rendered, np.where(valid, 255, 0).astype(np.uint8)),
                )
                output = io.BytesIO()
                Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
                content = output.getvalue()
                self._write_tile_cache(cache_path, content)
                return content
            if kind == "ndvi":
                values, valid, _transform = self._reproject_index_matrix(
                    src,
                    "NDVI",
                    z,
                    x,
                    y,
                )
                rgba = self._colorize_index("NDVI", values, valid, low, high)
                output = io.BytesIO()
                Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
                content = output.getvalue()
                self._write_tile_cache(cache_path, content)
                return content
        raise ValueError(f"Tipo de tile no soportado: {kind}")
    
    def begin_crop_tiles(self, geom: Any) -> dict[str, Any]:
        """Register a ROI to mask exact Web Mercator RGB tiles."""
        crop_id = uuid4().hex
        self.crop_geometries[crop_id] = geom
        minx, miny, maxx, maxy = geom.bounds
        return {
            "crop_id": crop_id,
            "bounds": [[miny, minx], [maxy, maxx]],
            "tile_version": self.tile_cache_version(),
        }
    
    def export_crop(self, crop_id: str) -> bytes:
        """Export the active ROI as a georeferenced, masked GeoTIFF."""
        geom = self.crop_geometries.get(crop_id)
        if geom is None:
            raise ValueError("El recorte ya no esta disponible. Selecciona el ROI nuevamente.")
    
        with rasterio.open(self._path()) as source:
            if not source.crs:
                raise ValueError("El ortomosaico necesita un CRS para exportar el recorte.")
            source_geometry = geom
            if source.crs.to_string() != "EPSG:4326":
                source_geometry = project_geometry(
                    pyproj.Transformer.from_crs(
                        "EPSG:4326",
                        source.crs,
                        always_xy=True,
                    ).transform,
                    geom,
                )
            try:
                outside, cropped_transform, crop_window = raster_geometry_mask(
                    source, [mapping(source_geometry)], crop=True,
                )
            except ValueError as exc:
                raise ValueError("El ROI no intersecta el ortomosaico activo.") from exc
    
            profile = source.profile.copy()
            profile.update(
                driver="GTiff", width=outside.shape[1], height=outside.shape[0],
                transform=cropped_transform, compress="deflate", tiled=True,
                blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER",
            )
            fill_value = source.nodata if source.nodata is not None else 0
            with tempfile.TemporaryDirectory(dir=self.settings.cache_dir, prefix="crop-") as temporary:
                output_path = Path(temporary) / "crop.tif"
                with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
                    with rasterio.open(output_path, "w", **profile) as destination:
                        for local in raster_processing.windows(outside.shape[1], outside.shape[0]):
                            window = Window(
                                crop_window.col_off + local.col_off,
                                crop_window.row_off + local.row_off,
                                local.width, local.height,
                            )
                            cropped = source.read(window=window, masked=True)
                            rows, cols = local.toslices()
                            cropped.mask = np.ma.getmaskarray(cropped) | outside[rows, cols]
                            destination.write(cropped.filled(fill_value), window=local)
                            valid = np.any(~np.ma.getmaskarray(cropped), axis=0)
                            destination.write_mask(valid.astype(np.uint8) * 255, window=local)
                        destination.update_tags(**source.tags())
                        for band_index in range(1, source.count + 1):
                            description = source.descriptions[band_index - 1]
                            if description:
                                destination.set_band_description(band_index, description)
                            destination.update_tags(band_index, **source.tags(band_index))
                        destination.colorinterp = source.colorinterp
                return output_path.read_bytes()
    
    def export_crop_visual(self, crop_id: str) -> bytes:
        """Export a broadly compatible uint8 RGBA GeoTIFF for cloud viewers."""
        geom = self.crop_geometries.get(crop_id)
        if geom is None:
            raise ValueError("El recorte ya no esta disponible. Selecciona el ROI nuevamente.")
    
        with rasterio.open(self._path()) as source:
            if not source.crs:
                raise ValueError("El ortomosaico necesita un CRS para exportar el recorte.")
            source_geometry = geom
            if source.crs.to_string() != "EPSG:4326":
                source_geometry = project_geometry(
                    pyproj.Transformer.from_crs(
                        "EPSG:4326",
                        source.crs,
                        always_xy=True,
                    ).transform,
                    geom,
                )
            render_profile = self.rgb_render_profile(source)
            try:
                cropped, cropped_transform = raster_mask(
                    source,
                    [mapping(source_geometry)],
                    indexes=list(render_profile["bands"]),
                    crop=True,
                    filled=False,
                )
            except ValueError as exc:
                raise ValueError("El ROI no intersecta el ortomosaico activo.") from exc
    
            raw = np.asarray(cropped.filled(0))
            rendered = self._render_rgb_values(raw, render_profile)
            valid = np.all(~np.ma.getmaskarray(cropped), axis=0)
            rgba = np.concatenate(
                (rendered, (valid.astype(np.uint8) * 255)[np.newaxis, ...]),
                axis=0,
            )
            visual_profile = source.profile.copy()
            visual_profile.update(
                driver="GTiff",
                width=rgba.shape[2],
                height=rgba.shape[1],
                count=4,
                dtype="uint8",
                nodata=None,
                transform=cropped_transform,
                compress="deflate",
                interleave="pixel",
                photometric="RGB",
                alpha="yes",
                tiled=False,
            )
            visual_profile.pop("blockxsize", None)
            visual_profile.pop("blockysize", None)
    
            with MemoryFile() as memory_file:
                with memory_file.open(**visual_profile) as destination:
                    destination.write(rgba)
                    destination.colorinterp = (
                        ColorInterp.red,
                        ColorInterp.green,
                        ColorInterp.blue,
                        ColorInterp.alpha,
                    )
                    for band_index, description in enumerate(
                        ("Red", "Green", "Blue", "Alpha"),
                        1,
                    ):
                        destination.set_band_description(band_index, description)
                return memory_file.read()
    
    def crop_tile(self, crop_id: str, z: int, x: int, y: int) -> bytes:
        geom = self.crop_geometries.get(crop_id)
        if geom is None:
            raise ValueError("El recorte ya no está disponible. Selecciona el ROI nuevamente.")
        variant = hashlib.sha256(geom.wkb).hexdigest()
        cache_path = self._tile_cache_path(
            "crop-rgb", self.tile_cache_version(), z, x, y, variant=variant,
        )
        cached = self._read_tile_cache(cache_path)
        if cached is not None:
            return cached
        with Image.open(io.BytesIO(self.tile("rgb", z, x, y))) as tile:
            rgba = np.array(tile.convert("RGBA"))
        mercator_geom = project_geometry(
            pyproj.Transformer.from_crs(
                "EPSG:4326", "EPSG:3857", always_xy=True,
            ).transform,
            geom,
        )
        dst_transform = rasterio.transform.from_bounds(
            *self.tile_bounds_mercator(z, x, y), self.RGB_TILE_SIZE, self.RGB_TILE_SIZE,
        )
        roi_mask = geometry_mask(
            [mapping(mercator_geom)], out_shape=rgba.shape[:2],
            transform=dst_transform, invert=True,
        )
        rgba[~roi_mask, 3] = 0
        output = io.BytesIO()
        Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
        content = output.getvalue()
        self._write_tile_cache(cache_path, content)
        return content
    
    def _equalization_response(
        self,
        name: str,
        crop_id: str | None,
    ) -> dict[str, Any]:
        if crop_id is None:
            return self.ndvi_data() if name == "NDVI" else self.vegetation_index_data(name)
        geom = self.crop_geometries.get(crop_id)
        if geom is None:
            raise ValueError("El recorte ya no estÃ¡ disponible. Selecciona el ROI nuevamente.")
        return self.roi_ndvi(geom) if name == "NDVI" else self.roi_vegetation_index(geom, name)
    
    def _render_index_tile(
        self,
        name: str,
        z: int,
        x: int,
        y: int,
        *,
        low: float | None = None,
        high: float | None = None,
        crop_id: str | None = None,
        equalized: bool = False,
        fill_mode: str = "transparent",
    ) -> bytes:
        cache_variant = (
            f"{name.lower()}-"
            f"{crop_id or 'full'}-"
            f"{'eq' if equalized else 'linear'}-"
            f"{fill_mode}-"
            f"{'none' if low is None else f'{float(low):.4f}'}-"
            f"{'none' if high is None else f'{float(high):.4f}'}"
        )
        cache_path = self._tile_cache_path(
            "crop-index" if crop_id is not None else "index",
            self.index_tile_cache_version(),
            z,
            x,
            y,
            variant=cache_variant,
        )
        cached = self._read_tile_cache(cache_path)
        if cached is not None:
            return cached
        equalization_cdf: np.ndarray | None = None
        if fill_mode not in {"transparent", "solid"}:
            raise ValueError("fill_mode no soportado.")
        if equalized:
            equalization_cdf = self._cached_equalization_cdf(
                name,
                crop_id,
                low,
                high,
            )
        bands = self._index_bands(name)
        if not bands:
            raise ValueError("El Ã­ndice requiere un ortomosaico multiespectral compatible.")
        with rasterio.open(self._path()) as src:
            values, valid, dst_transform = self._reproject_index_matrix(src, name, z, x, y)
            if crop_id is not None:
                geom = self.crop_geometries.get(crop_id)
                if geom is None:
                    raise ValueError("El recorte ya no estÃ¡ disponible. Selecciona el ROI nuevamente.")
                mercator_geom = project_geometry(
                    pyproj.Transformer.from_crs(
                        "EPSG:4326",
                        "EPSG:3857",
                        always_xy=True,
                    ).transform,
                    geom,
                )
                roi_mask = geometry_mask(
                    [mapping(mercator_geom)],
                    out_shape=(self.RGB_TILE_SIZE, self.RGB_TILE_SIZE),
                    transform=dst_transform,
                    invert=True,
                )
                valid = valid & roi_mask
            rgba = self._colorize_index(
                name,
                values,
                valid,
                low,
                high,
                equalized=equalized,
                fill_mode=fill_mode,
                equalization_cdf=equalization_cdf,
            )
            output = io.BytesIO()
            Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
            content = output.getvalue()
            self._write_tile_cache(cache_path, content)
            return content
    
    def crop_index_tile(self, name: str, crop_id: str, z: int, x: int, y: int, low: float | None = None, high: float | None = None, equalized: bool = False, fill_mode: str = "transparent") -> bytes:
        return self._render_index_tile(
            name,
            z,
            x,
            y,
            low=low,
            high=high,
            crop_id=crop_id,
            equalized=equalized,
            fill_mode=fill_mode,
        )
        geom = self.crop_geometries.get(crop_id)
        if geom is None:
            raise ValueError("El recorte ya no está disponible. Selecciona el ROI nuevamente.")
        bands = self._index_bands(name)
        if not bands:
            raise ValueError("El índice requiere un ortomosaico multiespectral compatible.")
        with rasterio.open(self._path()) as src:
            values, valid, dst_transform = self._reproject_index_matrix(
                src,
                name,
                z,
                x,
                y,
            )
            mercator_geom = project_geometry(
                pyproj.Transformer.from_crs(
                    "EPSG:4326",
                    "EPSG:3857",
                    always_xy=True,
                ).transform,
                geom,
            )
            mask = geometry_mask(
                [mapping(mercator_geom)],
                out_shape=(self.RGB_TILE_SIZE, self.RGB_TILE_SIZE),
                transform=dst_transform,
                invert=True,
            )
            # Debe usar la misma regla que el índice completo: NoData y
            # reflectancias inválidas no se interpretan como suelo rojo.
            rgba = self._colorize_index(name, values, valid & mask, low, high)
            output = io.BytesIO()
            Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
            return output.getvalue()
    
    def index_tile(
        self,
        name: str,
        z: int,
        x: int,
        y: int,
        low: float | None = None,
        high: float | None = None,
        equalized: bool = False,
        fill_mode: str = "transparent",
    ) -> bytes:
        return self._render_index_tile(
            name,
            z,
            x,
            y,
            low=low,
            high=high,
            equalized=equalized,
            fill_mode=fill_mode,
        )
        bands = self._index_bands(name)
        if not bands:
            raise ValueError("El índice requiere un ortomosaico multiespectral compatible.")
        with rasterio.open(self._path()) as src:
            values, valid, _transform = self._reproject_index_matrix(
                src,
                name,
                z,
                x,
                y,
            )
            rgba = self._colorize_index(name, values, valid, low, high)
            output = io.BytesIO()
            Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
            return output.getvalue()
    
    def geometry_window(
        self,
        geom: Any,
        bands: list[int],
        *,
        resampling: Resampling = Resampling.average,
    ) -> tuple[np.ndarray, Affine, np.ndarray, dict[str, Any]] | None:
        with rasterio.open(self._path()) as src:
            if src.crs and src.crs.to_string() != "EPSG:4326":
                geom = project_geometry(pyproj.Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform, geom)
            bounds = geom.bounds
            if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]: return None
            try: window = from_bounds(*bounds, transform=src.transform).intersection(Window(0, 0, src.width, src.height))
            except Exception: return None
            if window.width <= 0 or window.height <= 0: return None
            scale = self.scale(src, self.settings.ndvi_max_pixels)
            width, height = max(1, round(window.width / scale)), max(1, round(window.height / scale))
            data = src.read(
                bands,
                window=window,
                out_shape=(len(bands), height, width),
                resampling=resampling,
            )
            transform = window_transform(window, src.transform) * Affine.scale(window.width / width, window.height / height)
            mask = geometry_mask(
                [mapping(geom)],
                out_shape=(height, width),
                transform=transform,
                invert=True,
                all_touched=True,
            )
            source_bounds = array_bounds(height, width, transform)
            response_bounds = transform_bounds(src.crs, "EPSG:4326", *source_bounds) if src.crs and src.crs.to_string() != "EPSG:4326" else source_bounds
            return data, transform, mask, {"col_off": window.col_off, "row_off": window.row_off, "scale": scale, "src_width": src.width, "src_height": src.height, "response_bounds": response_bounds}
    
    def _full_resolution_index_range(
        self,
        geom: Any,
        positive_band: int,
        negative_band: int,
    ) -> tuple[float | None, float | None]:
        with rasterio.open(self._path()) as src:
            source_geom = geom
            if src.crs and src.crs.to_string() != "EPSG:4326":
                source_geom = project_geometry(
                    pyproj.Transformer.from_crs(
                        "EPSG:4326",
                        src.crs,
                        always_xy=True,
                    ).transform,
                    geom,
                )
            bounds = source_geom.bounds
            if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                return None, None
            try:
                window = from_bounds(*bounds, transform=src.transform).intersection(
                    Window(0, 0, src.width, src.height),
                )
            except Exception:
                return None, None
            if window.width <= 0 or window.height <= 0:
                return None, None
            return raster_processing.index_range(
                src, window, source_geom, (positive_band, negative_band),
                self._calculate_index, self.settings.cache_dir,
            )
    
    def crop(self, geom: Any) -> dict[str, Any]:
        result = self.geometry_window(geom, list(self._rgb_bands()))
        if result is None: raise ValueError("El recorte no intersecta el raster.")
        data, transform, mask, meta = result
        # La máscara geométrica define el área del recorte. No se debe volver
        # transparente un píxel válido solo porque sus bandas RGB sean oscuras.
        rgba = np.dstack((*[self.normalize(data[i]) for i in range(3)], np.where(mask, 255, 0).astype(np.uint8)))
        Image.fromarray(rgba, mode="RGBA").save(self.settings.output_dir / "recorte_overlay.png")
        return self._bounds_response(transform, data.shape[1], data.shape[2], meta) | {"overlay_path": "/static/recorte_overlay.png"}
    
    def ndvi_data(self) -> dict[str, Any]:
        width, height, overlay_transform = self.ensure_overlay()
        red_band, nir_band = self._ndvi_bands()
        with rasterio.open(self._path()) as src:
            scale = self.scale(src, self.settings.ndvi_max_pixels)
            coarse_height, coarse_width = max(1, src.height // scale), max(1, src.width // scale)
            source_transform = src.transform * Affine.scale(src.width / coarse_width, src.height / coarse_height)
            # PIX4Dfields calcula los índices sobre valores espectrales por
            # píxel. Muestrear con nearest preserva ese comportamiento al
            # reducir resolución, mientras que average comprime el rango.
            red = src.read(
                red_band,
                out_shape=(coarse_height, coarse_width),
                resampling=Resampling.nearest,
            ).astype(np.float32)
            nir = src.read(
                nir_band,
                out_shape=(coarse_height, coarse_width),
                resampling=Resampling.nearest,
            ).astype(np.float32)
            if src.crs and src.crs.to_string() != "EPSG:4326":
                red_wgs84 = np.zeros((height, width), dtype=np.float32)
                nir_wgs84 = np.zeros((height, width), dtype=np.float32)
                for source, destination in ((red, red_wgs84), (nir, nir_wgs84)):
                    reproject(
                        source=source,
                        destination=destination,
                        src_transform=source_transform,
                        src_crs=src.crs,
                        dst_transform=overlay_transform,
                        dst_crs="EPSG:4326",
                        resampling=Resampling.nearest,
                    )
                red, nir = red_wgs84, nir_wgs84
            ndvi, valid = self._calculate_index(nir, red)
            bounds = array_bounds(height, width, overlay_transform)
            return {
                "status": "ok",
                "ndvi_matrix": (np.clip((ndvi + 1) / 2, 0, 1) * 255).astype(np.uint8).tolist(),
                "ndvi_mask": valid.astype(np.uint8).tolist(),
                "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
            }
    
    def vegetation_index_data(self, name: str) -> dict[str, Any]:
        if self.sensor == "mavic3m":
            bands = {"green": 1, "red": 2, "rededge": 3, "nir": 4}
        elif self.sensor == "micasense":
            bands = {"green": 2, "red": 4, "rededge": 5, "nir": 6}
        else:
            raise ValueError("NDWI y NDRE requieren un ortomosaico multiespectral compatible.")
        formulas = {"NDWI": ("green", "nir"), "NDRE": ("nir", "rededge")}
        if name not in formulas:
            raise ValueError("Índice no soportado. Usa NDWI o NDRE.")
        first_name, second_name = formulas[name]
        width, height, overlay_transform = self.ensure_overlay()
        with rasterio.open(self._path()) as src:
            scale = self.scale(src, self.settings.ndvi_max_pixels)
            coarse_height, coarse_width = max(1, src.height // scale), max(1, src.width // scale)
            source_transform = src.transform * Affine.scale(src.width / coarse_width, src.height / coarse_height)
            first = src.read(
                bands[first_name],
                out_shape=(coarse_height, coarse_width),
                resampling=Resampling.nearest,
            ).astype(np.float32)
            second = src.read(
                bands[second_name],
                out_shape=(coarse_height, coarse_width),
                resampling=Resampling.nearest,
            ).astype(np.float32)
            if src.crs and src.crs.to_string() != "EPSG:4326":
                projected = []
                for source in (first, second):
                    destination = np.zeros((height, width), dtype=np.float32)
                    reproject(
                        source=source,
                        destination=destination,
                        src_transform=source_transform,
                        src_crs=src.crs,
                        dst_transform=overlay_transform,
                        dst_crs="EPSG:4326",
                        resampling=Resampling.nearest,
                    )
                    projected.append(destination)
                first, second = projected
            values, valid = self._calculate_index(first, second)
            bounds = array_bounds(height, width, overlay_transform)
            return {
                "status": "ok",
                "matrix": values.tolist(),
                "mask": valid.astype(np.uint8).tolist(),
                "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
            }
    
    def roi_ndvi(self, geom: Any) -> dict[str, Any]:
        result = self.geometry_window(
            geom,
            list(self._ndvi_bands()),
            resampling=Resampling.nearest,
        )
        if result is None: raise ValueError("El ROI no intersecta el raster.")
        data, transform, mask, meta = result
        red, nir = data.astype(np.float32)
        ndvi, valid = self._calculate_index(nir, red)
        range_min, range_max = self._full_resolution_index_range(
            geom,
            self._ndvi_bands()[1],
            self._ndvi_bands()[0],
        )
        return {
            "status": "ok",
            "ndvi_matrix": (np.clip((ndvi + 1) / 2, 0, 1) * 255).astype(np.uint8).tolist(),
            "ndvi_mask": (valid & mask).astype(np.uint8).tolist(),
            "range_min": range_min,
            "range_max": range_max,
            **self._bounds_response(transform, data.shape[1], data.shape[2], meta),
        }
    
    def roi_vegetation_index(self, geom: Any, name: str) -> dict[str, Any]:
        """Calcula un índice únicamente dentro de una geometría de interés."""
        if name == "NDVI":
            return self.roi_ndvi(geom)
        if self.sensor == "mavic3m":
            bands = {"NDWI": (1, 4), "NDRE": (4, 3)}.get(name)
        elif self.sensor == "micasense":
            bands = {"NDWI": (2, 6), "NDRE": (6, 5)}.get(name)
        else:
            bands = None
        if not bands:
            raise ValueError(f"{name} requiere un ortomosaico multiespectral compatible.")
        result = self.geometry_window(
            geom,
            list(bands),
            resampling=Resampling.nearest,
        )
        if result is None:
            raise ValueError("El ROI no intersecta el raster.")
        data, transform, mask, meta = result
        first, second = data.astype(np.float32)
        values, valid = self._calculate_index(first, second)
        range_min, range_max = self._full_resolution_index_range(
            geom,
            bands[0],
            bands[1],
        )
        return {
            "status": "ok",
            "matrix": values.tolist(),
            "mask": (valid & mask).astype(np.uint8).tolist(),
            "range_min": range_min,
            "range_max": range_max,
            **self._bounds_response(transform, data.shape[1], data.shape[2], meta),
        }
    
    @staticmethod
    def _bounds_response(transform: Affine, height: int, width: int, meta: dict[str, Any]) -> dict[str, Any]:
        return raster_helpers.bounds_response(transform, height, width, meta)
    