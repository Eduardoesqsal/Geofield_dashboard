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



class RasterClassificationHelperMixin:
    """Helpers numericos y de leyenda para clasificacion."""

    @staticmethod
    def _neutral_zone_label(zone_index: int, zone_count: int) -> str:
        return raster_helpers.neutral_zone_label(zone_index, zone_count)
    
    @staticmethod
    def _normalize_index_name(name: str | None) -> str:
        return raster_helpers.normalize_index_name(name)
    
    def _index_zone_label(self, name: str, zone_index: int, zone_count: int) -> str:
        return raster_helpers.index_zone_label(name, zone_index, zone_count)
    
    @staticmethod
    def _class_percentiles(zone_count: int, zone_index: int) -> tuple[float, float]:
        return raster_helpers.class_percentiles(zone_count, zone_index)
    
    @classmethod
    def _ramp_stops(cls, index_name: str) -> np.ndarray:
        return raster_helpers.ramp_stops(
            index_name,
            cls.VEGETATION_COLOR_STOPS,
            cls.INDEX_RAMPS,
        )
    
    @classmethod
    def _sample_ramp(cls, index_name: str, positions: np.ndarray) -> np.ndarray:
        return raster_helpers.sample_ramp(
            index_name,
            positions,
            cls.VEGETATION_COLOR_STOPS,
            cls.INDEX_RAMPS,
        )
    
    def _zone_palette(self, index_name: str, zone_count: int) -> np.ndarray:
        return raster_helpers.zone_palette(
            index_name,
            zone_count,
            self.VEGETATION_COLOR_STOPS,
            self.INDEX_RAMPS,
            self.PIX4D_ZONE_DISPLAY_PALETTES,
        )
    
    @classmethod
    def _zone_display_palette(cls, index_name: str, zone_count: int) -> np.ndarray:
        return raster_helpers.zone_display_palette(
            index_name,
            zone_count,
            cls.VEGETATION_COLOR_STOPS,
            cls.INDEX_RAMPS,
            cls.PIX4D_ZONE_DISPLAY_PALETTES,
        )
    
    @classmethod
    def _dose_ramp(cls, index_name: str, count: int) -> np.ndarray:
        return raster_helpers.dose_ramp(
            index_name,
            count,
            cls.VEGETATION_COLOR_STOPS,
            cls.INDEX_RAMPS,
        )
    
    @staticmethod
    def _fill_unclassified_cells(zones: np.ndarray, target_mask: np.ndarray) -> np.ndarray:
        return raster_helpers.fill_unclassified_cells(zones, target_mask)
    
    @classmethod
    def _export_prescription_dosage(cls, dosage: float | int | None) -> float:
        return raster_helpers.export_prescription_dosage(
            dosage,
            cls.EAVISION_DOSAGE_EXPORT_SCALE,
        )
    
    @staticmethod
    def _normalize_classification_method(method: str | None) -> str:
        return raster_helpers.normalize_classification_method(method)
    
    @staticmethod
    def _normalize_cell_value_mode(mode: str | None) -> str:
        return raster_helpers.normalize_cell_value_mode(mode)
    
    @staticmethod
    def _normalize_detail_level(detail_level: float | None) -> float:
        return raster_helpers.normalize_detail_level(detail_level)
    
    @staticmethod
    def _validate_manual_breaks(
        manual_breaks: list[float] | tuple[float, ...] | None,
        zone_count: int,
        analysis_min: float,
        analysis_max: float,
    ) -> np.ndarray:
        return raster_helpers.validate_manual_breaks(
            manual_breaks,
            zone_count,
            analysis_min,
            analysis_max,
        )
    
    @staticmethod
    def _classification_breaks(
        values: np.ndarray,
        zone_count: int,
        classification_method: str,
        analysis_min: float,
        analysis_max: float,
        manual_breaks: list[float] | tuple[float, ...] | None,
    ) -> np.ndarray:
        if classification_method == "quantiles":
            internal_breaks = np.quantile(
                values,
                np.linspace(0, 1, zone_count + 1)[1:-1],
            ).astype(np.float32)
            return np.concatenate(
                (
                    np.asarray([analysis_min], dtype=np.float32),
                    internal_breaks,
                    np.asarray([analysis_max], dtype=np.float32),
                ),
            )
        if classification_method == "equal_intervals":
            return np.linspace(analysis_min, analysis_max, zone_count + 1, dtype=np.float32)
        internal_breaks = RasterClassificationHelperMixin._validate_manual_breaks(
            manual_breaks,
            zone_count,
            analysis_min,
            analysis_max,
        )
        return np.concatenate(
            (
                np.asarray([analysis_min], dtype=np.float32),
                internal_breaks,
                np.asarray([analysis_max], dtype=np.float32),
            ),
        )
    
    @staticmethod
    def _classification_histogram(
        values: np.ndarray,
        breaks: np.ndarray,
        bin_count: int = 48,
        display_minimum: float | None = None,
        display_maximum: float | None = None,
    ) -> dict[str, Any]:
        minimum = float(display_minimum) if display_minimum is not None else float(breaks[0])
        maximum = float(display_maximum) if display_maximum is not None else float(breaks[-1])
        if maximum <= minimum:
            bins = np.zeros(bin_count, dtype=np.int32)
            edges = np.linspace(minimum, minimum + 1e-6, bin_count + 1, dtype=np.float32)
        else:
            edges = np.linspace(minimum, maximum, bin_count + 1, dtype=np.float32)
            bins, _ = np.histogram(values, bins=edges)
        return {
            "minimum": minimum,
            "maximum": maximum,
            "bins": [int(value) for value in bins.tolist()],
            "breaks": [float(value) for value in breaks.tolist()],
        }
    
    @staticmethod
    def _effective_cell_areas(
        metric_geometry: Any,
        height: int,
        width: int,
        destination_transform: Affine,
        cell_size_m: float,
        oversample: int = 4,
    ) -> np.ndarray:
        oversampled_mask = geometry_mask(
            [mapping(metric_geometry)],
            out_shape=(height * oversample, width * oversample),
            transform=destination_transform * Affine.scale(1 / oversample, 1 / oversample),
            invert=True,
            all_touched=True,
        )
        coverage = oversampled_mask.reshape(
            height,
            oversample,
            width,
            oversample,
        ).mean(axis=(1, 3))
        return coverage.astype(np.float32) * np.float32(cell_size_m**2)
    
    @staticmethod
    def _aggregate_cell_values(
        fine_values: np.ndarray,
        fine_valid: np.ndarray,
        height: int,
        width: int,
        oversample: int,
        cell_value_mode: str,
        cell_size_m: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        reshaped_valid = fine_valid.reshape(height, oversample, width, oversample)
        valid_counts = reshaped_valid.sum(axis=(1, 3)).astype(np.float32)
        area_per_sample = np.float32(cell_size_m**2 / (oversample**2))
        cell_areas_m2 = valid_counts * area_per_sample
        index_values = np.full((height, width), np.nan, dtype=np.float32)
    
        if cell_value_mode == "mean":
            safe_values = np.where(fine_valid, fine_values, 0).reshape(
                height,
                oversample,
                width,
                oversample,
            )
            sums = safe_values.sum(axis=(1, 3), dtype=np.float64)
            np.divide(
                sums,
                valid_counts,
                out=index_values,
                where=valid_counts > 0,
            )
            return index_values, cell_areas_m2
    
        masked_values = np.where(fine_valid, fine_values, np.nan).reshape(
            height,
            oversample,
            width,
            oversample,
        )
        for row_index in range(height):
            for column_index in range(width):
                if valid_counts[row_index, column_index] <= 0:
                    continue
                cell_values = masked_values[row_index, :, column_index, :]
                if cell_value_mode == "min":
                    index_values[row_index, column_index] = np.nanmin(cell_values)
                else:
                    index_values[row_index, column_index] = np.nanmax(cell_values)
        return index_values, cell_areas_m2
    
    @staticmethod
    def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float | None:
        return raster_helpers.weighted_mean(values, weights)
    
    @staticmethod
    def _validate_prescription_weight_data(
        weight_data: list[int],
        rows: int,
        columns: int,
        data_type: int,
    ) -> None:
        expected_length = rows * columns
        if len(weight_data) != expected_length:
            raise ValueError(
                "La prescripcion JSON es invalida: weightData no coincide con rows * columns.",
            )
        allowed_values = set(range(data_type + 1))
        if not set(weight_data).issubset(allowed_values):
            raise ValueError(
                "La prescripcion JSON es invalida: weightData contiene niveles fuera de 0..dataType.",
            )
    
    @staticmethod
    def _neighbor_offsets() -> tuple[tuple[int, int], ...]:
        return raster_helpers.neighbor_offsets()
    
    @staticmethod
    def _component_connectivity_offsets() -> tuple[tuple[int, int], ...]:
        return raster_helpers.component_connectivity_offsets()
    
    @staticmethod
    def _detail_strength(detail_level: float) -> float:
        return raster_helpers.detail_strength(detail_level)
    
    @staticmethod
    def _interpolate_detail(
        detail_level: float,
        maximum: float,
        minimum: float,
    ) -> float:
        return raster_helpers.interpolate_detail(detail_level, maximum, minimum)
    
    @classmethod
    def _spatial_detail_parameters(
        cls,
        detail_level: float,
        class_valid: np.ndarray,
        cell_areas_m2: np.ndarray,
    ) -> dict[str, float | int]:
        """Translate Zone detail into physical, continuous spatial controls."""
        positive_areas = cell_areas_m2[class_valid & (cell_areas_m2 > 0)]
        nominal_cell_area_m2 = (
            float(np.percentile(positive_areas, 75)) if positive_areas.size else 1.0
        )
        total_area_m2 = float(np.sum(positive_areas))
        cell_width_m = float(np.sqrt(nominal_cell_area_m2))
        field_width_m = float(np.sqrt(max(total_area_m2, nominal_cell_area_m2)))
        strength = cls._detail_strength(detail_level)
    
        # The minimum mapping unit is expressed as an area. Its characteristic
        # width grows with both the requested simplification and the field's
        # physical scale, with a ceiling that avoids collapsing small fields.
        coarse_growth_m = max(cell_width_m * 2.0, field_width_m * 0.11)
        mapping_width_m = cell_width_m + strength * coarse_growth_m
        minimum_region_area_m2 = min(
            mapping_width_m**2,
            max(nominal_cell_area_m2 * 64.0, total_area_m2 * 0.02),
        )
        minimum_region_area_m2 = max(nominal_cell_area_m2, minimum_region_area_m2)
    
        return {
            "strength": float(strength),
            "nominal_cell_area_m2": nominal_cell_area_m2,
            "minimum_region_area_m2": minimum_region_area_m2,
            "envelope_iterations": (
                0 if detail_level >= 0.999 else max(1, int(np.ceil(strength * 3)))
            ),
            "spectral_iterations": (
                0 if detail_level >= 0.999 else max(1, int(np.ceil(strength * 10)))
            ),
            "neighborhood_iterations": (
                0 if detail_level >= 0.999 else max(1, int(np.ceil(strength * 5)))
            ),
            "neighbor_support_fraction": float(0.90 - strength * 0.20),
        }
    
