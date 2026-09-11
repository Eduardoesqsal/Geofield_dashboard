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
from geofield.services.raster_classification_helpers import RasterClassificationHelperMixin


logger = logging.getLogger(__name__)



class RasterClassificationFilterMixin:
    """Filtros espaciales y regularizacion de zonas."""

    @classmethod
    def _spectral_zone_filter(
        cls,
        zones: np.ndarray,
        class_valid: np.ndarray,
        index_values: np.ndarray,
        breaks: np.ndarray,
        iterations: int,
    ) -> np.ndarray:
        """Simplify uncertain boundaries on the continuous index surface."""
        if iterations <= 0:
            return zones.copy()
        smoothed = index_values.astype(np.float32, copy=True)
        height, width = zones.shape
        kernel = (
            (-1, -1, 1.0), (-1, 0, 2.0), (-1, 1, 1.0),
            (0, -1, 2.0),  (0, 0, 4.0),  (0, 1, 2.0),
            (1, -1, 1.0),  (1, 0, 2.0),  (1, 1, 1.0),
        )
        for _iteration in range(iterations):
            sums = np.zeros_like(smoothed, dtype=np.float64)
            totals = np.zeros_like(smoothed, dtype=np.float32)
            for row_delta, column_delta, weight in kernel:
                source_rows = slice(max(0, -row_delta), min(height, height - row_delta))
                source_columns = slice(max(0, -column_delta), min(width, width - column_delta))
                target_rows = slice(max(0, row_delta), min(height, height + row_delta))
                target_columns = slice(max(0, column_delta), min(width, width + column_delta))
                source_valid = class_valid[source_rows, source_columns]
                sums[target_rows, target_columns] += np.where(
                    source_valid,
                    smoothed[source_rows, source_columns] * weight,
                    0.0,
                )
                totals[target_rows, target_columns] += source_valid.astype(np.float32) * weight
            np.divide(sums, totals, out=smoothed, where=class_valid & (totals > 0))
            smoothed[~class_valid] = np.nan
    
        raw_classes = np.zeros_like(zones, dtype=np.uint8)
        filtered_classes = np.zeros_like(zones, dtype=np.uint8)
        raw_classes[class_valid] = (
            np.digitize(index_values[class_valid], breaks[1:-1], right=False) + 1
        ).astype(np.uint8)
        filtered_classes[class_valid] = (
            np.digitize(smoothed[class_valid], breaks[1:-1], right=False) + 1
        ).astype(np.uint8)
    
        same_neighbors = np.zeros_like(zones, dtype=np.uint8)
        opposite_support = np.zeros_like(class_valid)
        cardinal_support = np.zeros_like(class_valid)
        for row_delta, column_delta in cls._neighbor_offsets():
            source_rows = slice(max(0, -row_delta), min(height, height - row_delta))
            source_columns = slice(max(0, -column_delta), min(width, width - column_delta))
            target_rows = slice(max(0, row_delta), min(height, height + row_delta))
            target_columns = slice(max(0, column_delta), min(width, width + column_delta))
            same_neighbors[target_rows, target_columns] += (
                class_valid[source_rows, source_columns]
                & (zones[source_rows, source_columns] == zones[target_rows, target_columns])
            ).astype(np.uint8)
            if row_delta == 0 or column_delta == 0:
                cardinal_support[target_rows, target_columns] |= (
                    class_valid[source_rows, source_columns]
                    & (zones[source_rows, source_columns] == zones[target_rows, target_columns])
                )
        opposite_support[:, 1:-1] |= (
            (zones[:, :-2] == zones[:, 1:-1]) & (zones[:, 2:] == zones[:, 1:-1])
        )
        opposite_support[1:-1, :] |= (
            (zones[:-2, :] == zones[1:-1, :]) & (zones[2:, :] == zones[1:-1, :])
        )
        thin_linear = (opposite_support | cardinal_support) & (same_neighbors <= 2)
        filtered_classes = np.clip(
            filtered_classes,
            np.maximum(zones.astype(np.int16) - 1, 1),
            zones.astype(np.int16) + 1,
        ).astype(np.uint8)
        component_sizes = np.zeros_like(zones, dtype=np.int32)
        visited = np.zeros_like(class_valid)
        for row in range(height):
            for column in range(width):
                if not class_valid[row, column] or visited[row, column]:
                    continue
                _class_id, component, _perimeter = cls._connected_component(
                    zones,
                    class_valid,
                    visited,
                    row,
                    column,
                    cls._component_connectivity_offsets(),
                    cls._neighbor_offsets(),
                )
                for component_row, component_column in component:
                    component_sizes[component_row, component_column] = len(component)
        change = (
            class_valid
            & (raw_classes == zones)
            & (filtered_classes != zones)
            & (component_sizes >= 9)
            & ~thin_linear
        )
        result = zones.copy()
        result[change] = filtered_classes[change]
        result[~class_valid] = 0
        return result
    
    @classmethod
    def _ordinal_envelope_filter(
        cls,
        zones: np.ndarray,
        class_valid: np.ndarray,
        zone_count: int,
        iterations: int,
    ) -> np.ndarray:
        """Insert intermediate classes where distant classes touch directly."""
        if iterations <= 0 or zone_count <= 2:
            return zones.copy()
        result = zones.copy()
        height, width = result.shape
        for _iteration in range(iterations):
            votes = np.zeros((zone_count + 1, height, width), dtype=np.uint8)
            available = np.zeros((height, width), dtype=np.uint8)
            same_class = np.zeros((height, width), dtype=np.uint8)
            for row_delta, column_delta in cls._neighbor_offsets():
                source_rows = slice(max(0, -row_delta), min(height, height - row_delta))
                source_columns = slice(max(0, -column_delta), min(width, width - column_delta))
                target_rows = slice(max(0, row_delta), min(height, height + row_delta))
                target_columns = slice(max(0, column_delta), min(width, width + column_delta))
                shifted_valid = class_valid[source_rows, source_columns]
                shifted_zones = result[source_rows, source_columns]
                target_zones = result[target_rows, target_columns]
                available[target_rows, target_columns] += shifted_valid.astype(np.uint8)
                same_class[target_rows, target_columns] += (
                    shifted_valid & (shifted_zones == target_zones)
                ).astype(np.uint8)
                for class_id in range(1, zone_count + 1):
                    votes[class_id, target_rows, target_columns] += (
                        shifted_valid & (shifted_zones == class_id)
                    ).astype(np.uint8)
    
            next_result = result.copy()
            for class_id in range(1, zone_count + 1):
                current = class_valid & (result == class_id)
                if not np.any(current):
                    continue
                lower_target = 0
                upper_target = 0
                lower_votes = np.zeros((height, width), dtype=np.uint8)
                upper_votes = np.zeros((height, width), dtype=np.uint8)
                for neighbor_class in range(1, zone_count + 1):
                    distance = neighbor_class - class_id
                    if abs(distance) <= 1:
                        continue
                    if distance > 0 and votes[neighbor_class].max() > 0:
                        candidate_votes = votes[neighbor_class]
                        replace = candidate_votes > upper_votes
                        upper_votes[replace] = candidate_votes[replace]
                        upper_target = max(upper_target, class_id + 1)
                    elif distance < 0 and votes[neighbor_class].max() > 0:
                        candidate_votes = votes[neighbor_class]
                        replace = candidate_votes > lower_votes
                        lower_votes[replace] = candidate_votes[replace]
                        lower_target = min(lower_target or class_id - 1, class_id - 1)
    
                promote = (
                    current
                    & (upper_target > 0)
                    & (upper_votes >= 1)
                    & (same_class <= 5)
                )
                demote = (
                    current
                    & (lower_target > 0)
                    & (lower_votes >= 1)
                    & (same_class <= 5)
                    & ~promote
                )
                next_result[promote] = upper_target
                next_result[demote] = lower_target
            if np.array_equal(next_result, result):
                break
            result = next_result
        result[~class_valid] = 0
        return result
    
    @staticmethod
    def _component_span(component: list[tuple[int, int]]) -> tuple[int, int]:
        return raster_helpers.component_span(component)
    
    @classmethod
    def _preserve_linear_component(
        cls,
        component: list[tuple[int, int]],
        component_area_m2: float,
        minimum_region_area_m2: float,
        nominal_cell_area_m2: float,
    ) -> bool:
        """Keep credible crop-row/band structures despite a small footprint."""
        if len(component) < 3 or component_area_m2 < minimum_region_area_m2 * 0.30:
            return False
        row_span, column_span = cls._component_span(component)
        major_span = max(row_span, column_span)
        minor_span = max(1, min(row_span, column_span))
        target_span = np.sqrt(minimum_region_area_m2 / nominal_cell_area_m2)
        return major_span / minor_span >= 3.0 and major_span >= target_span
    
    @staticmethod
    def _connected_component(
        zones: np.ndarray,
        class_valid: np.ndarray,
        visited: np.ndarray,
        start_row: int,
        start_column: int,
        connectivity_offsets: tuple[tuple[int, int], ...],
        perimeter_offsets: tuple[tuple[int, int], ...],
    ) -> tuple[int, list[tuple[int, int]], dict[int, int]]:
        class_id = int(zones[start_row, start_column])
        component: list[tuple[int, int]] = []
        perimeter_counts: dict[int, int] = {}
        queue = deque([(start_row, start_column)])
        visited[start_row, start_column] = True
        while queue:
            row, column = queue.popleft()
            component.append((row, column))
            for row_delta, column_delta in connectivity_offsets:
                next_row = row + row_delta
                next_column = column + column_delta
                if not (
                    0 <= next_row < zones.shape[0]
                    and 0 <= next_column < zones.shape[1]
                    and class_valid[next_row, next_column]
                ):
                    continue
                next_class = int(zones[next_row, next_column])
                if next_class == class_id:
                    if not visited[next_row, next_column]:
                        visited[next_row, next_column] = True
                        queue.append((next_row, next_column))
        for row, column in component:
            for row_delta, column_delta in perimeter_offsets:
                next_row = row + row_delta
                next_column = column + column_delta
                if not (
                    0 <= next_row < zones.shape[0]
                    and 0 <= next_column < zones.shape[1]
                    and class_valid[next_row, next_column]
                ):
                    continue
                next_class = int(zones[next_row, next_column])
                if next_class > 0 and next_class != class_id:
                    perimeter_counts[next_class] = perimeter_counts.get(next_class, 0) + 1
        return class_id, component, perimeter_counts
    
    @staticmethod
    def _select_component_target(
        perimeter_counts: dict[int, int],
        class_id: int,
        component: list[tuple[int, int]],
        zones: np.ndarray,
        index_values: np.ndarray,
        cell_areas_m2: np.ndarray,
        class_areas_m2: dict[int, float],
        breaks: np.ndarray,
        component_region_areas_m2: np.ndarray | None = None,
        minimum_target_area_m2: float = 0.0,
    ) -> int | None:
        """Choose a merge target from boundary, spectral and continuity evidence."""
        if not perimeter_counts:
            return None
        rows = np.asarray([row for row, _column in component], dtype=np.intp)
        columns = np.asarray([column for _row, column in component], dtype=np.intp)
        component_weights = cell_areas_m2[rows, columns].astype(np.float64)
        component_values = index_values[rows, columns].astype(np.float64)
        component_mean = RasterClassificationHelperMixin._weighted_mean(component_values, component_weights)
        if component_mean is None:
            component_mean = float((breaks[class_id - 1] + breaks[class_id]) / 2)
    
        component_area = float(np.sum(component_weights))
        total_boundary = max(1, sum(perimeter_counts.values()))
        value_span = max(float(breaks[-1] - breaks[0]), 1e-9)
        class_center = len(breaks) / 2.0
        maximum_class_distance = max(class_center - 1.0, 1.0)
        cardinal_offsets = RasterClassificationHelperMixin._component_connectivity_offsets()
        boundary_values: dict[int, list[tuple[float, float]]] = {}
        neighboring_region_areas: dict[int, float] = {}
        for row, column in component:
            for row_delta, column_delta in cardinal_offsets:
                next_row = row + row_delta
                next_column = column + column_delta
                if not (0 <= next_row < zones.shape[0] and 0 <= next_column < zones.shape[1]):
                    continue
                candidate = int(zones[next_row, next_column])
                if candidate <= 0 or candidate == class_id or not np.isfinite(index_values[next_row, next_column]):
                    continue
                boundary_values.setdefault(candidate, []).append(
                    (float(index_values[next_row, next_column]), float(cell_areas_m2[next_row, next_column])),
                )
                if component_region_areas_m2 is not None:
                    neighboring_region_areas[candidate] = max(
                        neighboring_region_areas.get(candidate, 0.0),
                        float(component_region_areas_m2[next_row, next_column]),
                    )
    
        scores: dict[int, float] = {}
        for candidate, shared_boundary in perimeter_counts.items():
            candidate_region_area = neighboring_region_areas.get(
                candidate,
                class_areas_m2.get(candidate, 0.0),
            )
            if (
                component_region_areas_m2 is not None
                and candidate_region_area < component_area
                and candidate_region_area < minimum_target_area_m2
            ):
                continue
            samples = boundary_values.get(candidate, [])
            if samples:
                sample_values = np.asarray([value for value, _weight in samples], dtype=np.float64)
                sample_weights = np.asarray([weight for _value, weight in samples], dtype=np.float64)
                candidate_mean = RasterClassificationHelperMixin._weighted_mean(sample_values, sample_weights)
            else:
                candidate_mean = None
            if candidate_mean is None:
                candidate_mean = float((breaks[candidate - 1] + breaks[candidate]) / 2)
            shared_score = shared_boundary / total_boundary
            spectral_score = 1.0 - min(1.0, abs(component_mean - candidate_mean) / value_span)
            continuity_score = candidate_region_area / max(candidate_region_area + component_area, 1e-9)
            centrality_score = 1.0 - min(
                1.0,
                abs(candidate - class_center) / maximum_class_distance,
            )
            scores[candidate] = (
                0.45 * shared_score
                + 0.35 * spectral_score
                + 0.05 * continuity_score
                + 0.15 * centrality_score
            )
        if not scores:
            return None
        return max(
            scores,
            key=lambda candidate: (
                scores[candidate],
                perimeter_counts[candidate],
                -abs(candidate - class_id),
                -candidate,
            ),
        )
    
    @staticmethod
    def _component_class_areas(
        zones: np.ndarray,
        class_valid: np.ndarray,
        cell_areas_m2: np.ndarray,
    ) -> dict[int, float]:
        return {
            int(class_id): float(np.sum(cell_areas_m2[(zones == class_id) & class_valid]))
            for class_id in np.unique(zones[class_valid])
            if int(class_id) > 0
        }
    
    @classmethod
    def _categorical_majority_filter(
        cls,
        zones: np.ndarray,
        class_valid: np.ndarray,
        zone_count: int,
        iterations: int,
        support_fraction: float,
    ) -> np.ndarray:
        """Remove weak categorical noise without averaging class identifiers."""
        result = zones.copy()
        height, width = result.shape
        stable_linear_support = np.zeros_like(class_valid)
        stable_linear_support[:, 1:-1] |= (
            (result[:, :-2] == result[:, 1:-1])
            & (result[:, 2:] == result[:, 1:-1])
            & class_valid[:, :-2]
            & class_valid[:, 2:]
        )
        stable_linear_support[1:-1, :] |= (
            (result[:-2, :] == result[1:-1, :])
            & (result[2:, :] == result[1:-1, :])
            & class_valid[:-2, :]
            & class_valid[2:, :]
        )
        for _iteration in range(iterations):
            votes = np.zeros((zone_count + 1, height, width), dtype=np.uint8)
            available = np.zeros((height, width), dtype=np.uint8)
            for row_delta, column_delta in cls._neighbor_offsets():
                source_rows = slice(max(0, -row_delta), min(height, height - row_delta))
                source_columns = slice(max(0, -column_delta), min(width, width - column_delta))
                target_rows = slice(max(0, row_delta), min(height, height + row_delta))
                target_columns = slice(max(0, column_delta), min(width, width + column_delta))
                shifted_valid = class_valid[source_rows, source_columns]
                shifted_zones = result[source_rows, source_columns]
                available[target_rows, target_columns] += shifted_valid.astype(np.uint8)
                for class_id in range(1, zone_count + 1):
                    votes[class_id, target_rows, target_columns] += (
                        shifted_valid & (shifted_zones == class_id)
                    ).astype(np.uint8)
            winner = np.argmax(votes, axis=0).astype(np.uint8)
            winner_votes = np.take_along_axis(votes, winner[None, ...], axis=0)[0]
            current_votes = np.take_along_axis(votes, result[None, ...], axis=0)[0]
            required_votes = np.ceil(available * support_fraction).astype(np.uint8)
            change = (
                class_valid
                & (available >= 3)
                & (winner > 0)
                & (winner != result)
                & (winner_votes >= required_votes)
                & (winner_votes >= current_votes + 2)
                & ~stable_linear_support
            )
            if not np.any(change):
                break
            next_result = result.copy()
            next_result[change] = winner[change]
            result = next_result
        result[~class_valid] = 0
        return result
    
    def _merge_small_components(
        self,
        zones: np.ndarray,
        class_valid: np.ndarray,
        index_values: np.ndarray,
        breaks: np.ndarray,
        cell_areas_m2: np.ndarray,
        minimum_region_area_m2: float,
        nominal_cell_area_m2: float,
    ) -> tuple[np.ndarray, int]:
        result = zones.copy()
        visited = np.zeros(result.shape, dtype=bool)
        connectivity_offsets = self._component_connectivity_offsets()
        class_areas = self._component_class_areas(result, class_valid, cell_areas_m2)
        component_region_areas = np.zeros(result.shape, dtype=np.float64)
        component_records: list[
            tuple[int, list[tuple[int, int]], dict[int, int], float]
        ] = []
        components_to_absorb: list[tuple[list[tuple[int, int]], int, int]] = []
    
        for start_row, start_column in zip(*np.nonzero(class_valid), strict=True):
            if visited[start_row, start_column]:
                continue
            class_id, component, perimeter_counts = self._connected_component(
                result,
                class_valid,
                visited,
                start_row,
                start_column,
                connectivity_offsets,
                connectivity_offsets,
            )
            rows = np.asarray([row for row, _column in component], dtype=np.intp)
            columns = np.asarray([column for _row, column in component], dtype=np.intp)
            component_area = float(np.sum(cell_areas_m2[rows, columns]))
            component_region_areas[rows, columns] = component_area
            component_records.append((class_id, component, perimeter_counts, component_area))
    
        for class_id, component, perimeter_counts, component_area in component_records:
            if class_id <= 0:
                continue
            if component_area >= minimum_region_area_m2:
                continue
            # Do not erase an entire statistically meaningful class. This is
            # especially important for Fine/Quantile maps and narrow fields.
            if (
                component_area >= class_areas.get(class_id, 0.0) - 1e-9
                and component_area >= minimum_region_area_m2 * 0.5
            ):
                continue
            if self._preserve_linear_component(
                component,
                component_area,
                minimum_region_area_m2,
                nominal_cell_area_m2,
            ):
                continue
            target_class = self._select_component_target(
                perimeter_counts,
                class_id,
                component,
                result,
                index_values,
                cell_areas_m2,
                class_areas,
                breaks,
                component_region_areas,
                minimum_region_area_m2,
            )
            if target_class is None or target_class == class_id:
                continue
            components_to_absorb.append((component, class_id, target_class))
    
        for component, class_id, target_class in sorted(
            components_to_absorb,
            key=lambda item: (len(item[0]), item[1]),
        ):
            for row, column in component:
                if result[row, column] != class_id:
                    continue
                result[row, column] = target_class
    
        return result, len(components_to_absorb)
    
    @classmethod
    def _zone_debug_snapshot(
        cls,
        zones: np.ndarray,
        class_valid: np.ndarray,
        index_values: np.ndarray,
        cell_areas_m2: np.ndarray,
        zone_count: int,
        minimum_region_area_m2: float = 0.0,
    ) -> dict[str, Any]:
        connectivity_offsets = cls._component_connectivity_offsets()
        visited = np.zeros(zones.shape, dtype=bool)
        component_count = 0
        isolated_cells = 0
        enclosed_components = 0
        component_sizes: list[int] = []
        component_areas_m2: list[float] = []
        small_components = 0
        valid_area_m2 = float(np.sum(cell_areas_m2[class_valid]))
        zones_summary: list[dict[str, Any]] = []
    
        for row, column in zip(*np.nonzero(class_valid), strict=True):
            class_id = int(zones[row, column])
            if class_id <= 0 or visited[row, column]:
                visited[row, column] = True
                continue
            component_count += 1
            queue = deque([(row, column)])
            visited[row, column] = True
            component_size = 0
            component_area_m2 = 0.0
            touches_mask_edge = False
            neighboring_classes: set[int] = set()
            while queue:
                current_row, current_column = queue.popleft()
                component_size += 1
                component_area_m2 += float(cell_areas_m2[current_row, current_column])
                for row_delta, column_delta in connectivity_offsets:
                    next_row = current_row + row_delta
                    next_column = current_column + column_delta
                    if not (0 <= next_row < zones.shape[0] and 0 <= next_column < zones.shape[1]):
                        touches_mask_edge = True
                        continue
                    if not class_valid[next_row, next_column]:
                        touches_mask_edge = True
                        continue
                    neighboring_class = int(zones[next_row, next_column])
                    if neighboring_class != class_id:
                        if neighboring_class > 0:
                            neighboring_classes.add(neighboring_class)
                        continue
                    if visited[next_row, next_column]:
                        continue
                    visited[next_row, next_column] = True
                    queue.append((next_row, next_column))
            if component_size == 1:
                isolated_cells += 1
            if not touches_mask_edge and len(neighboring_classes) == 1:
                enclosed_components += 1
            component_sizes.append(component_size)
            component_areas_m2.append(component_area_m2)
            if minimum_region_area_m2 > 0 and component_area_m2 < minimum_region_area_m2:
                small_components += 1
    
        nominal_area = float(np.percentile(cell_areas_m2[class_valid], 75)) if np.any(class_valid) else 1.0
        edge_length_m = float(np.sqrt(max(nominal_area, 1e-9)))
        horizontal_edges = np.count_nonzero(
            class_valid[:, 1:] & class_valid[:, :-1] & (zones[:, 1:] != zones[:, :-1]),
        )
        vertical_edges = np.count_nonzero(
            class_valid[1:, :] & class_valid[:-1, :] & (zones[1:, :] != zones[:-1, :]),
        )
    
        for zone_index in range(1, zone_count + 1):
            zone_mask = (zones == zone_index) & class_valid
            zone_values = index_values[zone_mask & np.isfinite(index_values)]
            zone_weights = cell_areas_m2[zone_mask & np.isfinite(index_values)]
            mean_value = cls._weighted_mean(
                zone_values.astype(np.float64),
                zone_weights.astype(np.float64),
            )
            zone_area_m2 = float(np.sum(cell_areas_m2[zone_mask]))
            coverage_percent = (
                zone_area_m2 / valid_area_m2 * 100 if valid_area_m2 > 0 else 0.0
            )
            zones_summary.append(
                {
                    "class_id": zone_index,
                    "cell_count": int(np.count_nonzero(zone_mask)),
                    "area_hectares": zone_area_m2 / 10_000,
                    "coverage_percent": float(coverage_percent),
                    "mean": float(mean_value) if mean_value is not None else None,
                },
            )
    
        return {
            "connected_components": int(component_count),
            "isolated_cells": int(isolated_cells),
            "enclosed_components": int(enclosed_components),
            "small_components": int(small_components),
            "mean_component_cells": float(np.mean(component_sizes)) if component_sizes else 0.0,
            "maximum_component_cells": int(max(component_sizes, default=0)),
            "mean_component_area_m2": float(np.mean(component_areas_m2)) if component_areas_m2 else 0.0,
            "maximum_component_area_m2": float(max(component_areas_m2, default=0.0)),
            "internal_perimeter_m": float((horizontal_edges + vertical_edges) * edge_length_m),
            "zones": zones_summary,
        }
    
    def _regularize_zones(
        self,
        initial_zones: np.ndarray,
        class_valid: np.ndarray,
        index_values: np.ndarray,
        breaks: np.ndarray,
        detail_level: float,
        cell_areas_m2: np.ndarray | None = None,
    ) -> np.ndarray:
        if detail_level >= 0.999:
            # Fine is the statistical classification itself. In particular,
            # Quantile retains its near-equal coverage at this endpoint.
            return initial_zones.copy()
        if cell_areas_m2 is None:
            cell_areas_m2 = class_valid.astype(np.float32)
        parameters = self._spatial_detail_parameters(
            detail_level,
            class_valid,
            cell_areas_m2,
        )
        result = self._spectral_zone_filter(
            initial_zones,
            class_valid,
            index_values,
            breaks,
            int(parameters["spectral_iterations"]),
        )
        result = self._ordinal_envelope_filter(
            result,
            class_valid,
            len(breaks) - 1,
            int(parameters["envelope_iterations"]),
        )
        result = self._categorical_majority_filter(
            result,
            class_valid,
            len(breaks) - 1,
            int(parameters["neighborhood_iterations"]),
            float(parameters["neighbor_support_fraction"]),
        )
        target_area = float(parameters["minimum_region_area_m2"])
        for fraction in (0.35, 0.60, 0.80, 1.0):
            for _pass in range(4):
                result, merged_count = self._merge_small_components(
                    result,
                    class_valid,
                    index_values,
                    breaks,
                    cell_areas_m2,
                    target_area * fraction,
                    float(parameters["nominal_cell_area_m2"]),
                )
                if merged_count == 0:
                    break
        return result
    
