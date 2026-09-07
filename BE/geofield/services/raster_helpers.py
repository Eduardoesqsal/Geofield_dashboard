"""Funciones puras reutilizadas por `RasterService`.

Separamos aquí la lógica sin estado para que el servicio principal se quede
más cerca de una capa de orquestación.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


def neutral_zone_label(zone_index: int, zone_count: int) -> str:
    if zone_count == 4:
        return [
            "NDVI muy bajo",
            "NDVI bajo",
            "NDVI medio-alto",
            "NDVI alto",
        ][zone_index - 1]
    if zone_index == 1:
        return "NDVI muy bajo"
    if zone_index == zone_count:
        return "NDVI alto"
    return f"NDVI nivel {zone_index}"


def normalize_index_name(name: str | None) -> str:
    normalized = (name or "NDVI").upper()
    if normalized not in {"NDVI", "NDWI", "NDRE"}:
        raise ValueError("Indice no soportado. Usa NDVI, NDWI o NDRE.")
    return normalized


def index_zone_label(name: str, zone_index: int, zone_count: int) -> str:
    if name == "NDVI":
        return neutral_zone_label(zone_index, zone_count)
    if zone_count == 4:
        return [
            f"{name} muy bajo",
            f"{name} bajo",
            f"{name} medio-alto",
            f"{name} alto",
        ][zone_index - 1]
    if zone_index == 1:
        return f"{name} muy bajo"
    if zone_index == zone_count:
        return f"{name} alto"
    return f"{name} nivel {zone_index}"


def class_percentiles(zone_count: int, zone_index: int) -> tuple[float, float]:
    return (
        100.0 * (zone_index - 1) / zone_count,
        100.0 * zone_index / zone_count,
    )


def ramp_stops(index_name: str, vegetation_color_stops: np.ndarray, index_ramps: dict[str, list[str]]) -> np.ndarray:
    if index_name in {"NDVI", "NDRE"}:
        return vegetation_color_stops
    ramp = index_ramps[index_name]
    return np.linspace(0.0, 1.0, len(ramp), dtype=np.float32)


def sample_ramp(
    index_name: str,
    positions: np.ndarray,
    vegetation_color_stops: np.ndarray,
    index_ramps: dict[str, list[str]],
) -> np.ndarray:
    ramp = np.asarray(
        [
            [int(color[index : index + 2], 16) for index in (0, 2, 4)]
            for color in index_ramps[index_name]
        ],
        dtype=np.uint8,
    )
    stops = ramp_stops(index_name, vegetation_color_stops, index_ramps)
    sampled = np.empty((len(positions), 3), dtype=np.uint8)
    for channel in range(3):
        sampled[:, channel] = np.round(
            np.interp(positions, stops, ramp[:, channel].astype(np.float32)),
        ).astype(np.uint8)
    return sampled


def zone_palette(
    index_name: str,
    zone_count: int,
    vegetation_color_stops: np.ndarray,
    index_ramps: dict[str, list[str]],
    zone_display_palettes: dict[tuple[str, int], list[str]],
) -> np.ndarray:
    palette = zone_display_palettes.get((index_name, zone_count))
    if palette:
        return np.asarray(
            [
                [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                for color in palette
            ],
            dtype=np.uint8,
        )
    positions = np.linspace(0.0, 1.0, max(zone_count, 1), dtype=np.float32)
    return sample_ramp(index_name, positions, vegetation_color_stops, index_ramps)


def zone_display_palette(
    index_name: str,
    zone_count: int,
    vegetation_color_stops: np.ndarray,
    index_ramps: dict[str, list[str]],
    zone_display_palettes: dict[tuple[str, int], list[str]],
) -> np.ndarray:
    return zone_palette(
        index_name,
        zone_count,
        vegetation_color_stops,
        index_ramps,
        zone_display_palettes,
    )


def dose_ramp(
    index_name: str,
    count: int,
    vegetation_color_stops: np.ndarray,
    index_ramps: dict[str, list[str]],
) -> np.ndarray:
    if count <= 1:
        return sample_ramp(index_name, np.asarray([1.0], dtype=np.float32), vegetation_color_stops, index_ramps)
    positions = np.linspace(0.0, 1.0, count, dtype=np.float32)
    return sample_ramp(index_name, positions, vegetation_color_stops, index_ramps)


def fill_unclassified_cells(zones: np.ndarray, target_mask: np.ndarray) -> np.ndarray:
    """Extend the nearest classified zone so every target cell is covered."""
    filled = zones.copy()
    visited = zones > 0
    queue = deque(zip(*np.nonzero(visited), strict=True))
    height, width = zones.shape
    neighbours = (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1), (0, 1),
        (1, -1), (1, 0), (1, 1),
    )
    while queue:
        row, column = queue.popleft()
        for row_delta, column_delta in neighbours:
            next_row = row + row_delta
            next_column = column + column_delta
            if (
                0 <= next_row < height
                and 0 <= next_column < width
                and not visited[next_row, next_column]
            ):
                visited[next_row, next_column] = True
                filled[next_row, next_column] = filled[row, column]
                queue.append((next_row, next_column))
    filled[~target_mask] = 0
    return filled


def export_prescription_dosage(dosage: float | int | None, scale: float) -> float:
    if dosage is None:
        return 0.0
    return round(float(dosage) * scale, 3)


def normalize_classification_method(method: str | None) -> str:
    normalized = (method or "quantiles").strip().lower()
    aliases = {
        "quantile": "quantiles",
        "quantiles": "quantiles",
        "equal": "equal_intervals",
        "equal_interval": "equal_intervals",
        "equal_intervals": "equal_intervals",
        "manual": "manual",
    }
    result = aliases.get(normalized)
    if not result:
        raise ValueError(
            "Metodo de clasificacion no soportado. Usa quantiles, equal_intervals o manual.",
        )
    return result


def normalize_cell_value_mode(mode: str | None) -> str:
    normalized = (mode or "mean").strip().lower()
    aliases = {
        "mean": "mean",
        "avg": "mean",
        "average": "mean",
        "min": "min",
        "minimum": "min",
        "max": "max",
        "maximum": "max",
    }
    result = aliases.get(normalized)
    if not result:
        raise ValueError("Valor de celda no soportado. Usa mean, min o max.")
    return result


def normalize_detail_level(detail_level: float | None) -> float:
    if detail_level is None:
        return 1.0
    detail = float(detail_level)
    if not 0 <= detail <= 1:
        raise ValueError("El detalle espacial debe estar entre 0 y 1.")
    return detail


def validate_manual_breaks(
    manual_breaks: list[float] | tuple[float, ...] | None,
    zone_count: int,
    analysis_min: float,
    analysis_max: float,
) -> np.ndarray:
    if manual_breaks is None:
        raise ValueError("Los intervalos manuales requieren una lista de cortes.")
    if len(manual_breaks) != zone_count - 1:
        raise ValueError("La cantidad de cortes manuales debe ser igual a zonas menos uno.")
    breaks = np.asarray(manual_breaks, dtype=np.float32)
    if not np.all(np.isfinite(breaks)):
        raise ValueError("Los cortes manuales deben ser numericos.")
    if np.any(np.diff(breaks) <= 0):
        raise ValueError("Los cortes manuales deben estar ordenados y no repetirse.")
    if breaks[0] <= analysis_min or breaks[-1] >= analysis_max:
        raise ValueError("Los cortes manuales deben quedar dentro del rango activo.")
    return breaks


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> float | None:
    if not values.size:
        return None
    total_weight = float(np.sum(weights))
    if total_weight <= 0:
        return None
    return float(np.sum(values * weights) / total_weight)


def neighbor_offsets() -> tuple[tuple[int, int], ...]:
    return (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1),           (0, 1),
        (1, -1),  (1, 0),  (1, 1),
    )


def component_connectivity_offsets() -> tuple[tuple[int, int], ...]:
    return (
        (-1, 0),
        (0, -1), (0, 1),
        (1, 0),
    )


def detail_strength(detail_level: float) -> float:
    return (1.0 - detail_level) ** 1.10


def interpolate_detail(detail_level: float, maximum: float, minimum: float) -> float:
    strength = detail_strength(detail_level)
    return maximum + (minimum - maximum) * strength


def component_span(component: list[tuple[int, int]]) -> tuple[int, int]:
    row_values = [row for row, _ in component]
    column_values = [column for _, column in component]
    return max(row_values) - min(row_values) + 1, max(column_values) - min(column_values) + 1


def compact_cache_component(component: str, *, prefix_length: int = 48) -> str:
    if not component:
        return "empty"
    component = component.replace(" ", "_")
    if len(component) <= prefix_length:
        return component
    return f"{component[:prefix_length]}-{len(component)}"


def bounds_response(transform: Any, height: int, width: int, meta: dict[str, Any]) -> dict[str, Any]:
    from rasterio.transform import array_bounds

    minx, miny, maxx, maxy = meta.get("response_bounds", array_bounds(height, width, transform))
    result = {
        "bounds": [[miny, minx], [maxy, maxx]],
        "offset_x": round(meta["col_off"] / meta["scale"]),
        "offset_y": round(meta["row_off"] / meta["scale"]),
        "base_width": max(1, round(meta["src_width"] / meta["scale"])),
        "base_height": max(1, round(meta["src_height"] / meta["scale"])),
    }
    return result


def scale(width: int, height: int, max_pixels: int) -> int:
    return max(1, int((width * height / max_pixels) ** 0.5))


def normalize_band(band: np.ndarray) -> np.ndarray:
    band = band.astype(np.float32)
    valid = band > 0
    if not np.any(valid):
        return np.zeros_like(band, dtype=np.uint8)
    low, high = np.nanmin(band[valid]), np.nanmax(band[valid])
    return np.zeros_like(band, dtype=np.uint8) if low == high else ((band - low) / (high - low) * 255).clip(0, 255).astype(np.uint8)


def calculate_index(positive: np.ndarray, negative: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    positive = positive.astype(np.float32, copy=False)
    negative = negative.astype(np.float32, copy=False)
    denominator = positive + negative
    valid = (positive > 0) & (negative > 0) & np.isfinite(positive) & np.isfinite(negative) & (denominator != 0)
    values = np.divide(positive - negative, denominator, out=np.zeros_like(denominator), where=valid)
    return values, valid


def response_index_values(name: str, response: dict[str, Any]) -> np.ndarray:
    matrix_key = "ndvi_matrix" if name == "NDVI" else "matrix"
    mask_key = "ndvi_mask" if name == "NDVI" else "mask"
    matrix = np.asarray(response.get(matrix_key), dtype=np.float32)
    mask = np.asarray(response.get(mask_key), dtype=bool)
    if matrix.size == 0 or mask.size == 0:
        return np.asarray([], dtype=np.float32)
    values = ((matrix / 255.0) * 2.0 - 1.0) if name == "NDVI" else matrix
    return values[np.isfinite(values) & mask]


def build_equalization_cdf(
    values: np.ndarray,
    minimum: float,
    maximum: float,
    *,
    bin_count: int = 256,
) -> np.ndarray | None:
    if values.size == 0 or not np.isfinite(minimum) or not np.isfinite(maximum):
        return None
    safe_minimum = min(minimum, maximum)
    safe_maximum = max(minimum, maximum)
    value_range = safe_maximum - safe_minimum
    if value_range <= np.finfo(np.float32).eps:
        return None
    histogram = np.zeros(bin_count, dtype=np.float32)
    sample_values = values[
        np.isfinite(values) & (values >= safe_minimum) & (values <= safe_maximum)
    ]
    if sample_values.size == 0:
        return None
    positions = np.clip(
        np.floor(((sample_values - safe_minimum) / value_range) * (bin_count - 1)).astype(int),
        0,
        bin_count - 1,
    )
    np.add.at(histogram, positions, 1.0)
    cumulative = np.cumsum(histogram)
    first_non_zero = cumulative[np.flatnonzero(cumulative)[0]]
    denominator = max(float(sample_values.size) - float(first_non_zero), 1.0)
    cdf = np.clip((cumulative - first_non_zero) / denominator, 0.0, 1.0)
    return cdf.astype(np.float32)
