"""Servicio principal de procesamiento raster.

Encapsula lectura de ortomosaicos, tiles, recortes, reproyección y cálculo de
índices espectrales completos o acotados al ROI.
"""

from __future__ import annotations

import io
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
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import Window, from_bounds, transform as window_transform
from shapely.affinity import rotate as rotate_geometry
from shapely.geometry import MultiLineString, Polygon, mapping
from shapely.ops import transform as project_geometry

from geofield.config import Settings
from geofield.errors import RasterNotConfiguredError


logger = logging.getLogger(__name__)


class RasterService:
    """Procesamiento geoespacial; no conoce detalles de FastAPI."""

    VEGETATION_COLOR_RAMP = [
        "ff1f1f", "ff4a1f", "ff741f", "ff9b1f", "ffc21f",
        "ffdd1f", "f3eb23", "d6e428", "a9d83a", "6ccf45",
    ]
    VEGETATION_COLOR_STOPS = np.asarray(
        [0.0, 0.12, 0.24, 0.38, 0.50, 0.60, 0.68, 0.76, 0.88, 1.0],
        dtype=np.float32,
    )
    INDEX_RAMPS = {
        "NDVI": VEGETATION_COLOR_RAMP,
        "NDWI": ["0000ff", "1a4fff", "2b9aff", "4dd4e0", "a8e6a0", "ffe066", "ffaa00", "ff5500", "e01a00", "c0003a"],
        "NDRE": VEGETATION_COLOR_RAMP,
    }
    PIX4D_ZONE_DISPLAY_PALETTES = {
        ("NDVI", 4): ["ff1f1f", "ff9b1f", "d6f01f", "30df1f"],
        ("NDVI", 5): ["ff1f1f", "ffb31f", "fff01f", "b7ef1f", "18e61f"],
        ("NDWI", 4): ["c0003a", "ffaa00", "4dd4e0", "0000ff"],
        ("NDRE", 4): ["ff1f1f", "ff9b1f", "d6f01f", "30df1f"],
        ("NDRE", 5): ["ff1f1f", "ffb31f", "fff01f", "b7ef1f", "18e61f"],
    }
    INDEX_DOMAINS = {"NDVI": (-0.2, 0.8), "NDWI": (-0.5, 0.5), "NDRE": (-0.2, 0.8)}
    RGB_RENDER_VERSION = "webmercator-v3"
    INDEX_RENDER_VERSION = "index-matrix-webmercator-v6"
    RGB_TILE_SIZE = 256
    EAVISION_DOSAGE_EXPORT_SCALE = 0.1
    _rgb_profile_cache: ClassVar[
        dict[tuple[str, int, int], dict[str, Any]]
    ] = {}
    _index_lut_cache: ClassVar[dict[str, np.ndarray]] = {}
    _equalization_cache_limit = 32

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Conservado como estado compatible; ahora contiene rangos globales por
        # canal y nunca percentiles calculados dentro de un tile.
        self.rgb_stretch: Any = None
        self.overlay: tuple[int, int, Affine] | None = None
        self.active_path: Path | None = None
        self.sensor: str | None = None
        self.crop_geometries: dict[str, Any] = {}
        self.equalization_cache: dict[tuple[Any, ...], np.ndarray | None] = {}

    def _render_classification_artifact(
        self,
        artifact_id: str,
        rgba: np.ndarray,
        transform: Affine,
        crs: Any,
        clip_geometry: Any,
    ) -> str:
        """Persist a classified grid with the georeferencing needed by XYZ tiles."""
        # El borde conserva un solo pixel, pero cada celda se representa con
        # mayor resolucion para que la reticula se perciba fina. En mapas muy
        # grandes se limita el escalado para controlar memoria y peso.
        cell_count = max(1, rgba.shape[0] * rgba.shape[1])
        render_scale = max(
            16,
            min(32, int(np.sqrt(36_000_000 / cell_count))),
        )
        rendered = np.repeat(np.repeat(rgba, render_scale, axis=0), render_scale, axis=1)
        rendered_transform = transform * Affine.scale(1 / render_scale, 1 / render_scale)
        # La celda del borde participa en la prescripcion, pero su pintura se
        # corta contra el poligono real para no sobresalir del cultivo.
        exact_mask = geometry_mask(
            [mapping(clip_geometry)],
            out_shape=rendered.shape[:2],
            transform=rendered_transform,
            invert=True,
        )
        rendered[~exact_mask] = 0
        artifact_dir = self.settings.output_dir / "prescriptions"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rendered, mode="RGBA").save(artifact_dir / f"{artifact_id}.png")
        with rasterio.open(
            artifact_dir / f"{artifact_id}.tif",
            "w",
            driver="GTiff",
            width=rendered.shape[1],
            height=rendered.shape[0],
            count=4,
            dtype="uint8",
            crs=crs,
            transform=rendered_transform,
            compress="deflate",
        ) as destination:
            destination.write(np.moveaxis(rendered, -1, 0))
        return f"/tiles/prescription/{artifact_id}/{{z}}/{{x}}/{{y}}.png"

    def _save_classification_grid_geojson(
        self,
        artifact_id: str,
        valid_mask: np.ndarray,
        transform: Affine,
        crs: Any,
    ) -> str:
        def segment_key(
            start: tuple[float, float],
            end: tuple[float, float],
        ) -> tuple[tuple[float, float], tuple[float, float]]:
            normalized_start = (round(start[0], 9), round(start[1], 9))
            normalized_end = (round(end[0], 9), round(end[1], 9))
            return (
                (normalized_start, normalized_end)
                if normalized_start <= normalized_end
                else (normalized_end, normalized_start)
            )

        height, width = valid_mask.shape
        if not np.any(valid_mask):
            geometry = {"type": "MultiLineString", "coordinates": []}
        else:
            if crs:
                crs_value = pyproj.CRS.from_user_input(crs)
                if crs_value.to_string() != "EPSG:4326":
                    to_wgs84 = pyproj.Transformer.from_crs(
                        crs_value,
                        "EPSG:4326",
                        always_xy=True,
                    ).transform
                else:
                    to_wgs84 = None
            else:
                to_wgs84 = None

            segments: list[list[tuple[float, float]]] = []
            seen_segments: set[
                tuple[tuple[float, float], tuple[float, float]]
            ] = set()
            for row in range(height):
                for column in range(width):
                    if not valid_mask[row, column]:
                        continue
                    top_left = transform * (column, row)
                    top_right = transform * (column + 1, row)
                    bottom_left = transform * (column, row + 1)
                    bottom_right = transform * (column + 1, row + 1)
                    for start, end in (
                        (top_left, top_right),
                        (top_left, bottom_left),
                        (bottom_left, bottom_right),
                        (top_right, bottom_right),
                    ):
                        key = segment_key(start, end)
                        if key in seen_segments:
                            continue
                        seen_segments.add(key)
                        segments.append([start, end])
            multiline = MultiLineString(segments)
            if to_wgs84 is not None:
                multiline = project_geometry(to_wgs84, multiline)
            geometry = mapping(multiline)

        artifact_dir = self.settings.output_dir / "prescriptions"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path = artifact_dir / f"{artifact_id}_grid.geojson"
        output_path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"artifact_id": artifact_id},
                            "geometry": geometry,
                        },
                    ],
                },
            ),
            encoding="utf-8",
        )
        return f"/static/prescriptions/{artifact_id}_grid.geojson"

    def _save_classification_fill_geojson(
        self,
        artifact_id: str,
        zones: np.ndarray,
        index_values: np.ndarray,
        transform: Affine,
        crs: Any,
        clip_geometry: Any,
        colors: list[np.ndarray] | np.ndarray,
        index_name: str,
    ) -> tuple[str, int]:
        crs_value = pyproj.CRS.from_user_input(crs)
        to_wgs84 = (
            pyproj.Transformer.from_crs(
                crs_value,
                "EPSG:4326",
                always_xy=True,
            ).transform
            if crs_value.to_string() != "EPSG:4326"
            else None
        )
        features: list[dict[str, Any]] = []
        for row, column in zip(*np.nonzero(zones > 0), strict=True):
            class_id = int(zones[row, column])
            if class_id <= 0:
                continue
            cell = Polygon(
                [
                    transform * (column, row),
                    transform * (column + 1, row),
                    transform * (column + 1, row + 1),
                    transform * (column, row + 1),
                ]
            )
            clipped = cell.intersection(clip_geometry)
            if clipped.is_empty:
                continue
            if not clipped.is_valid:
                clipped = clipped.buffer(0)
            if clipped.is_empty:
                continue
            geometry = project_geometry(to_wgs84, clipped) if to_wgs84 is not None else clipped
            if geometry.is_empty:
                continue
            color = colors[class_id - 1]
            value = float(index_values[row, column]) if np.isfinite(index_values[row, column]) else None
            features.append(
                {
                    "type": "Feature",
                    "id": f"{artifact_id}:{row}:{column}",
                    "properties": {
                        "artifact_id": artifact_id,
                        "zone": class_id,
                        "class_id": class_id,
                        "index_name": index_name,
                        "value": value,
                        "mean": value,
                        "color": "#" + "".join(f"{channel:02x}" for channel in color),
                        "row": int(row),
                        "column": int(column),
                    },
                    "geometry": mapping(geometry),
                }
            )

        artifact_dir = self.settings.output_dir / "prescriptions"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path = artifact_dir / f"{artifact_id}_fill.geojson"
        output_path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": features,
                },
            ),
            encoding="utf-8",
        )
        return f"/static/prescriptions/{artifact_id}_fill.geojson", len(features)

    @staticmethod
    def _apply_crisp_grid_lines(
        rendered: np.ndarray,
        render_scale: int,
        color: tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        line_width = 2 if render_scale >= 16 else 1
        edge_slices = [
            rendered[::render_scale, :, :],
            rendered[:, ::render_scale, :],
            rendered[-1:, :, :],
            rendered[:, -1:, :],
        ]
        if line_width > 1:
            edge_slices.extend(
                [
                    rendered[1::render_scale, :, :],
                    rendered[:, 1::render_scale, :],
                ],
            )
        for grid_edge in edge_slices:
            visible_edge = grid_edge[..., 3] > 0
            grid_edge[visible_edge, :3] = color
            grid_edge[visible_edge, 3] = 255

    def prescription_tile(self, artifact_id: str, z: int, x: int, y: int) -> bytes:
        """Warp a zoning/prescription artifact onto the exact Leaflet XYZ grid."""
        if not re.fullmatch(r"[0-9a-f]{32}", artifact_id):
            raise ValueError("El mapa de prescripcion solicitado no es valido.")
        artifact_path = self.settings.output_dir / "prescriptions" / f"{artifact_id}.tif"
        if not artifact_path.is_file():
            raise ValueError("El mapa de prescripcion ya no esta disponible.")

        size = self.RGB_TILE_SIZE
        destination = np.zeros((4, size, size), dtype=np.uint8)
        dst_transform = rasterio.transform.from_bounds(
            *self.tile_bounds_mercator(z, x, y),
            size,
            size,
        )
        with rasterio.open(artifact_path) as source:
            for band_index in range(1, 5):
                reproject(
                    source=rasterio.band(source, band_index),
                    destination=destination[band_index - 1],
                    src_transform=source.transform,
                    src_crs=source.crs,
                    dst_transform=dst_transform,
                    dst_crs="EPSG:3857",
                    dst_nodata=0,
                    resampling=Resampling.nearest,
                )
        output = io.BytesIO()
        Image.fromarray(np.moveaxis(destination, 0, -1), mode="RGBA").save(
            output,
            format="PNG",
        )
        return output.getvalue()

    def _path(self) -> Path:
        path = self.active_path or self.settings.raster_path
        if not path:
            raise RasterNotConfiguredError("No se encontro un raster GeoTIFF")
        return path

    def _validate_dataset(self, src: Any) -> None:
        if src.count < 3:
            raise ValueError("El ortomosaico debe contener al menos tres bandas.")
        scale = self.scale(src, self.settings.rgb_max_pixels)
        height = max(1, src.height // scale)
        width = max(1, src.width // scale)
        # Leer cada banda obliga a GDAL a recorrer los tiles internos. Abrir
        # sólo el encabezado no detecta TIFF truncados o bloques dañados.
        for band_index in range(1, src.count + 1):
            src.read(
                band_index,
                out_shape=(height, width),
                resampling=Resampling.average,
            )

    def validate_uploaded(self, content: bytes) -> None:
        try:
            with MemoryFile(content) as memory_file:
                with memory_file.open() as src:
                    self._validate_dataset(src)
        except RasterioIOError as exc:
            raise ValueError(
                "El GeoTIFF está incompleto o dañado: no se pudieron leer todos sus bloques internos.",
            ) from exc

    def validate_path(self, path: Path) -> None:
        try:
            with rasterio.open(path) as src:
                self._validate_dataset(src)
        except RasterioIOError as exc:
            raise ValueError(
                "El GeoTIFF guardado está incompleto o dañado y no puede activarse.",
            ) from exc

    @staticmethod
    def _neutral_zone_label(zone_index: int, zone_count: int) -> str:
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

    @staticmethod
    def _normalize_index_name(name: str | None) -> str:
        normalized = (name or "NDVI").upper()
        if normalized not in {"NDVI", "NDWI", "NDRE"}:
            raise ValueError("Indice no soportado. Usa NDVI, NDWI o NDRE.")
        return normalized

    def _index_zone_label(self, name: str, zone_index: int, zone_count: int) -> str:
        if name == "NDVI":
            return self._neutral_zone_label(zone_index, zone_count)
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

    @staticmethod
    def _class_percentiles(zone_count: int, zone_index: int) -> tuple[float, float]:
        return (
            100.0 * (zone_index - 1) / zone_count,
            100.0 * zone_index / zone_count,
        )

    @classmethod
    def _ramp_stops(cls, index_name: str) -> np.ndarray:
        if index_name in {"NDVI", "NDRE"}:
            return cls.VEGETATION_COLOR_STOPS
        ramp = cls.INDEX_RAMPS[index_name]
        return np.linspace(0.0, 1.0, len(ramp), dtype=np.float32)

    @classmethod
    def _sample_ramp(cls, index_name: str, positions: np.ndarray) -> np.ndarray:
        ramp = np.asarray(
            [
                [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                for color in cls.INDEX_RAMPS[index_name]
            ],
            dtype=np.uint8,
        )
        stops = cls._ramp_stops(index_name)
        sampled = np.empty((len(positions), 3), dtype=np.uint8)
        for channel in range(3):
            sampled[:, channel] = np.round(
                np.interp(positions, stops, ramp[:, channel].astype(np.float32)),
            ).astype(np.uint8)
        return sampled

    def _zone_palette(self, index_name: str, zone_count: int) -> np.ndarray:
        palette = self.PIX4D_ZONE_DISPLAY_PALETTES.get((index_name, zone_count))
        if palette:
            return np.asarray(
                [
                    [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                    for color in palette
                ],
                dtype=np.uint8,
            )
        positions = np.linspace(0.0, 1.0, max(zone_count, 1), dtype=np.float32)
        return self._sample_ramp(index_name, positions)

    @classmethod
    def _zone_display_palette(cls, index_name: str, zone_count: int) -> np.ndarray:
        palette = cls.PIX4D_ZONE_DISPLAY_PALETTES.get((index_name, zone_count))
        if palette:
            return np.asarray(
                [
                    [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                    for color in palette
                ],
                dtype=np.uint8,
            )
        positions = np.linspace(0.0, 1.0, max(zone_count, 1), dtype=np.float32)
        return cls._sample_ramp(index_name, positions)

    @classmethod
    def _dose_ramp(cls, index_name: str, count: int) -> np.ndarray:
        if count <= 1:
            return cls._sample_ramp(index_name, np.asarray([1.0], dtype=np.float32))
        positions = np.linspace(0.0, 1.0, count, dtype=np.float32)
        return cls._sample_ramp(index_name, positions)

    @staticmethod
    def _fill_unclassified_cells(zones: np.ndarray, target_mask: np.ndarray) -> np.ndarray:
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

    @classmethod
    def _export_prescription_dosage(cls, dosage: float | int | None) -> float:
        # EAVision interpreta el JSON Pix4D-style con una escala 10x respecto
        # a la dosis capturada en pantalla. Se exporta en decenas para que la
        # plataforma muestre la misma unidad ingresada por el usuario.
        if dosage is None:
            return 0.0
        return round(float(dosage) * cls.EAVISION_DOSAGE_EXPORT_SCALE, 3)

    @staticmethod
    def _normalize_classification_method(method: str | None) -> str:
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

    @staticmethod
    def _normalize_cell_value_mode(mode: str | None) -> str:
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

    @staticmethod
    def _normalize_detail_level(detail_level: float | None) -> float:
        if detail_level is None:
            return 1.0
        detail = float(detail_level)
        if not 0 <= detail <= 1:
            raise ValueError("El detalle espacial debe estar entre 0 y 1.")
        return detail

    @staticmethod
    def _validate_manual_breaks(
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
        internal_breaks = RasterService._validate_manual_breaks(
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
        if not values.size:
            return None
        total_weight = float(np.sum(weights))
        if total_weight <= 0:
            return None
        return float(np.sum(values * weights) / total_weight)

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
        return (
            (-1, -1), (-1, 0), (-1, 1),
            (0, -1),           (0, 1),
            (1, -1),  (1, 0),  (1, 1),
        )

    @staticmethod
    def _detail_strength(detail_level: float) -> float:
        # PIX4Dfields conserva gran parte de la microvariacion durante buena
        # parte del recorrido y concentra la simplificacion fuerte cerca del
        # extremo "Simple". Esta curva replica mejor ese comportamiento que
        # una interpolacion lineal.
        return (1.0 - detail_level) ** 1.65

    @staticmethod
    def _interpolate_detail(
        detail_level: float,
        maximum: float,
        minimum: float,
    ) -> float:
        strength = RasterService._detail_strength(detail_level)
        return maximum + (minimum - maximum) * strength

    @classmethod
    def _minimum_component_cells(cls, detail_level: float) -> int:
        if detail_level >= 0.99:
            return 1
        if detail_level >= 0.8:
            return 2
        if detail_level >= 0.6:
            return 3
        if detail_level >= 0.4:
            return 6
        if detail_level >= 0.2:
            return 10
        return 20

    @classmethod
    def _detail_window_radius(cls, detail_level: float) -> int:
        if detail_level >= 0.99:
            return 1
        if detail_level >= 0.8:
            return 1
        if detail_level >= 0.6:
            return 2
        if detail_level >= 0.4:
            return 3
        if detail_level >= 0.2:
            return 4
        return 5

    @staticmethod
    def _component_span(component: list[tuple[int, int]]) -> tuple[int, int]:
        rows = [row for row, _column in component]
        columns = [column for _row, column in component]
        return (
            max(rows) - min(rows) + 1,
            max(columns) - min(columns) + 1,
        )

    @classmethod
    def _preserve_component_shape(
        cls,
        component: list[tuple[int, int]],
        detail_level: float,
    ) -> bool:
        if not component:
            return False
        row_span, column_span = cls._component_span(component)
        major_span = max(row_span, column_span)
        minor_span = min(row_span, column_span)
        if major_span <= 2:
            return False
        if len(component) < max(4, cls._minimum_component_cells(detail_level)):
            return False
        max_minor_span = 1 if detail_level <= 0.35 else 2
        minimum_major_span = 4 if detail_level <= 0.35 else 5
        return minor_span <= max_minor_span and major_span >= minimum_major_span

    @classmethod
    def _zone_debug_snapshot(
        cls,
        zones: np.ndarray,
        class_valid: np.ndarray,
        index_values: np.ndarray,
        cell_areas_m2: np.ndarray,
        zone_count: int,
    ) -> dict[str, Any]:
        offsets = cls._neighbor_offsets()
        visited = np.zeros(zones.shape, dtype=bool)
        component_count = 0
        isolated_cells = 0
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
            while queue:
                current_row, current_column = queue.popleft()
                component_size += 1
                for row_delta, column_delta in offsets:
                    next_row = current_row + row_delta
                    next_column = current_column + column_delta
                    if not (
                        0 <= next_row < zones.shape[0]
                        and 0 <= next_column < zones.shape[1]
                        and class_valid[next_row, next_column]
                    ):
                        continue
                    if visited[next_row, next_column]:
                        continue
                    if int(zones[next_row, next_column]) != class_id:
                        continue
                    visited[next_row, next_column] = True
                    queue.append((next_row, next_column))
            if component_size == 1:
                isolated_cells += 1

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
        if detail_level >= 0.99:
            return initial_zones.copy()

        strength = self._detail_strength(detail_level)
        threshold = self._interpolate_detail(detail_level, 0.88, 0.44)
        local_threshold = self._interpolate_detail(detail_level, 0.75, 0.34)
        tolerance_alpha = self._interpolate_detail(detail_level, 0.12, 0.95)
        gain_threshold = self._interpolate_detail(detail_level, 0.22, 0.06)
        max_jump = 1 if detail_level >= 0.3 else 2
        max_iterations = max(1, int(round(2 + strength * 12)))
        if max_iterations <= 0:
            return initial_zones.copy()
        result = initial_zones.copy()
        zone_count = len(breaks) - 1
        class_centers = np.asarray(
            [
                0.0,
                *[
                    float((breaks[class_id - 1] + breaks[class_id]) / 2)
                    for class_id in range(1, zone_count + 1)
                ],
            ],
            dtype=np.float32,
        )
        offsets = self._neighbor_offsets()
        radius = self._detail_window_radius(detail_level)
        window_offsets = [
            (row_delta, column_delta)
            for row_delta in range(-radius, radius + 1)
            for column_delta in range(-radius, radius + 1)
            if row_delta != 0 or column_delta != 0
        ]

        for _iteration in range(max_iterations):
            changes: list[tuple[int, int, int]] = []
            for row, column in zip(*np.nonzero(class_valid), strict=True):
                current_class = int(result[row, column])
                if current_class <= 0:
                    continue
                local_counts = np.zeros(zone_count + 1, dtype=np.float32)
                local_neighbors = 0.0
                for row_delta, column_delta in offsets:
                    next_row = row + row_delta
                    next_column = column + column_delta
                    if (
                        0 <= next_row < result.shape[0]
                        and 0 <= next_column < result.shape[1]
                        and class_valid[next_row, next_column]
                    ):
                        neighbor_class = int(result[next_row, next_column])
                        if neighbor_class > 0:
                            local_neighbors += 1.0
                            local_counts[neighbor_class] += 1.0
                counts = np.zeros(zone_count + 1, dtype=np.float32)
                valid_neighbors = 0.0
                for row_delta, column_delta in window_offsets:
                    next_row = row + row_delta
                    next_column = column + column_delta
                    if (
                        0 <= next_row < result.shape[0]
                        and 0 <= next_column < result.shape[1]
                        and class_valid[next_row, next_column]
                    ):
                        neighbor_class = int(result[next_row, next_column])
                        if neighbor_class > 0:
                            distance = max(abs(row_delta), abs(column_delta))
                            weight = 1.0 / max(distance, 1)
                            valid_neighbors += weight
                            counts[neighbor_class] += weight
                if not valid_neighbors:
                    continue
                majority_class = int(np.argmax(counts[1:]) + 1)
                majority_count = float(counts[majority_class])
                if majority_class == current_class or majority_count <= 0:
                    continue
                majority_ratio = majority_count / valid_neighbors
                local_majority_class = int(np.argmax(local_counts[1:]) + 1)
                local_majority_ratio = (
                    float(local_counts[local_majority_class]) / local_neighbors
                    if local_neighbors > 0
                    else 0.0
                )
                local_current_ratio = (
                    float(local_counts[current_class]) / local_neighbors
                    if local_neighbors > 0
                    else 0.0
                )
                candidate_class = majority_class
                candidate_ratio = majority_ratio
                if (
                    local_neighbors >= 3
                    and local_majority_class != current_class
                    and local_majority_ratio >= local_threshold
                    and local_majority_ratio - local_current_ratio >= gain_threshold
                ):
                    candidate_class = local_majority_class
                    candidate_ratio = local_majority_ratio
                elif majority_ratio < threshold:
                    continue
                class_jump = abs(current_class - candidate_class)
                if class_jump > max_jump and candidate_ratio < min(1.0, threshold + 0.10):
                    continue
                current_ratio = float(counts[current_class]) / valid_neighbors
                if candidate_class == majority_class and majority_ratio - current_ratio < gain_threshold:
                    continue
                class_width = max(
                    float(breaks[candidate_class] - breaks[candidate_class - 1]),
                    1e-6,
                )
                tolerance = tolerance_alpha * class_width
                current_mean = float(class_centers[current_class])
                candidate_mean = float(class_centers[candidate_class])
                current_error = abs(float(index_values[row, column]) - current_mean)
                candidate_error = abs(
                    float(index_values[row, column]) - candidate_mean,
                )
                if candidate_error - current_error > tolerance:
                    continue
                changes.append((row, column, candidate_class))

            if not changes:
                break
            for row, column, new_class in changes:
                result[row, column] = new_class

        return self._remove_small_components(
            result,
            class_valid,
            index_values,
            breaks,
            detail_level,
            cell_areas_m2,
        )

    def _remove_small_components(
        self,
        zones: np.ndarray,
        class_valid: np.ndarray,
        index_values: np.ndarray,
        breaks: np.ndarray,
        detail_level: float,
        cell_areas_m2: np.ndarray | None = None,
    ) -> np.ndarray:
        min_component_cells = self._minimum_component_cells(detail_level)
        if min_component_cells <= 1:
            return zones

        result = zones.copy()
        visited = np.zeros(result.shape, dtype=bool)
        offsets = self._neighbor_offsets()
        minimum_contact_ratio = self._interpolate_detail(detail_level, 0.92, 0.45)

        for start_row, start_column in zip(*np.nonzero(class_valid), strict=True):
            if visited[start_row, start_column]:
                continue
            class_id = int(result[start_row, start_column])
            if class_id <= 0:
                visited[start_row, start_column] = True
                continue
            component: list[tuple[int, int]] = []
            perimeter_counts: dict[int, int] = {}
            neighbor_values: dict[int, list[float]] = {}
            queue = deque([(start_row, start_column)])
            visited[start_row, start_column] = True
            while queue:
                row, column = queue.popleft()
                component.append((row, column))
                for row_delta, column_delta in offsets:
                    next_row = row + row_delta
                    next_column = column + column_delta
                    if not (
                        0 <= next_row < result.shape[0]
                        and 0 <= next_column < result.shape[1]
                    ):
                        continue
                    if not class_valid[next_row, next_column]:
                        continue
                    next_class = int(result[next_row, next_column])
                    if next_class == class_id and not visited[next_row, next_column]:
                        visited[next_row, next_column] = True
                        queue.append((next_row, next_column))
                    elif next_class > 0 and next_class != class_id:
                        perimeter_counts[next_class] = perimeter_counts.get(next_class, 0) + 1
                        neighbor_values.setdefault(next_class, []).append(
                            float(index_values[next_row, next_column]),
                        )
            if len(component) >= min_component_cells or not perimeter_counts:
                continue
            if self._preserve_component_shape(component, detail_level):
                continue
            perimeter_total = sum(perimeter_counts.values())
            dominant_perimeter = max(perimeter_counts.values())
            if perimeter_total <= 0:
                continue
            if dominant_perimeter <= len(component):
                continue
            if dominant_perimeter / perimeter_total < minimum_contact_ratio:
                continue
            component_mean = float(
                np.mean([index_values[row, column] for row, column in component]),
            )
            candidate_class = min(
                perimeter_counts,
                key=lambda candidate: (
                    -perimeter_counts[candidate],
                    abs(
                        component_mean
                        - float(np.mean(neighbor_values.get(candidate, [component_mean]))),
                    ),
                    abs(
                        component_mean
                        - float((breaks[candidate - 1] + breaks[candidate]) / 2),
                    ),
                    abs(candidate - class_id),
                ),
            )
            for row, column in component:
                result[row, column] = candidate_class
        return result

    def _index_band_pair(
        self,
        index_name: str,
        raster_path: Path,
    ) -> tuple[int, int]:
        if index_name == "NDVI":
            red_band, nir_band = self._ndvi_bands(raster_path, self.sensor)
            return nir_band, red_band
        if self.sensor in {"mavic3m", "micasense"}:
            roles = self._multispectral_band_roles(path=raster_path, sensor=self.sensor)
            formulas = {"NDWI": ("green", "nir"), "NDRE": ("nir", "rededge")}
            names = formulas.get(index_name)
            bands = (roles[names[0]], roles[names[1]]) if names else None
        else:
            bands = None
        if not bands:
            raise ValueError(
                f"{index_name} requiere un ortomosaico multiespectral compatible.",
            )
        return bands

    def _prepare_index_classification(
        self,
        index_name: str,
        geom: Any,
        zone_count: int = 4,
        cell_size_m: float = 3.0,
        grid_angle_deg: float = 0.0,
        analysis_min: float | None = None,
        analysis_max: float | None = None,
        classification_method: str = "quantiles",
        cell_value_mode: str = "mean",
        manual_breaks: list[float] | tuple[float, ...] | None = None,
        detail_level: float = 1.0,
    ) -> dict[str, Any]:
        index_name = self._normalize_index_name(index_name)
        classification_method = self._normalize_classification_method(classification_method)
        cell_value_mode = self._normalize_cell_value_mode(cell_value_mode)
        detail_level = self._normalize_detail_level(detail_level)
        if not 2 <= zone_count <= 10:
            raise ValueError("El mapa de prescripcion admite entre 2 y 10 zonas.")
        if not 1 <= cell_size_m <= 50:
            raise ValueError("El tamano de celda debe estar entre 1 y 50 metros.")
        if not -90 <= grid_angle_deg <= 90:
            raise ValueError("La rotacion de la grilla debe estar entre -90 y 90 grados.")

        raster_path = self._path()
        with rasterio.open(raster_path) as src:
            if not src.crs:
                raise ValueError("El ortomosaico necesita un CRS para construir una grilla metrica.")
            source_crs = pyproj.CRS.from_user_input(src.crs)
            uses_meters = source_crs.is_projected and all(
                abs((axis.unit_conversion_factor or 0) - 1) < 1e-9
                for axis in source_crs.axis_info
            )
            if uses_meters:
                metric_crs = source_crs
            else:
                to_wgs84 = pyproj.Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
                center_x = (src.bounds.left + src.bounds.right) / 2
                center_y = (src.bounds.bottom + src.bounds.top) / 2
                longitude, latitude = to_wgs84.transform(center_x, center_y)
                utm_zone = max(1, min(60, int((longitude + 180) // 6) + 1))
                metric_crs = pyproj.CRS.from_epsg((32600 if latitude >= 0 else 32700) + utm_zone)

            metric_geometry = project_geometry(
                pyproj.Transformer.from_crs("EPSG:4326", metric_crs, always_xy=True).transform,
                geom,
            )
            if metric_geometry.is_empty or not metric_geometry.is_valid:
                raise ValueError("El ROI seleccionado no contiene una geometria valida.")
            center_x = metric_geometry.centroid.x
            center_y = metric_geometry.centroid.y
            grid_frame_geometry = rotate_geometry(
                metric_geometry,
                -grid_angle_deg,
                origin=(center_x, center_y),
            )
            left, bottom, right, top = grid_frame_geometry.bounds
            width = max(1, int(np.ceil((right - left) / cell_size_m - 1e-9)))
            height = max(1, int(np.ceil((top - bottom) / cell_size_m - 1e-9)))
            destination_transform = (
                Affine.translation(center_x, center_y)
                * Affine.rotation(grid_angle_deg)
                * Affine.translation(-center_x, -center_y)
                * Affine.translation(left, top)
                * Affine.scale(cell_size_m, -cell_size_m)
            )
            total_cells = width * height
            if total_cells > 150_000:
                minimum_size = cell_size_m * (total_cells / 150_000) ** 0.5
                raise ValueError(
                    "La grilla generaria demasiadas celdas. "
                    f"Usa un tamano de al menos {minimum_size:.1f} metros.",
                )

            first_band, second_band = self._index_band_pair(index_name, raster_path)
            source_geometry = project_geometry(
                pyproj.Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform,
                geom,
            )
            source_bounds = transform_bounds(
                metric_crs,
                src.crs,
                left,
                bottom,
                right,
                top,
                densify_pts=21,
            )
            try:
                source_window = from_bounds(*source_bounds, transform=src.transform).intersection(
                    Window(0, 0, src.width, src.height),
                )
            except Exception:
                source_window = None
            if source_window is None or source_window.width <= 0 or source_window.height <= 0:
                raise ValueError("El ROI no intersecta el ortomosaico activo.")

            sample_col_off = int(np.floor(source_window.col_off))
            sample_row_off = int(np.floor(source_window.row_off))
            sample_col_end = int(np.ceil(source_window.col_off + source_window.width))
            sample_row_end = int(np.ceil(source_window.row_off + source_window.height))
            sample_window = Window(
                sample_col_off,
                sample_row_off,
                max(1, sample_col_end - sample_col_off),
                max(1, sample_row_end - sample_row_off),
            ).intersection(Window(0, 0, src.width, src.height))
            sample_width = max(1, int(sample_window.width))
            sample_height = max(1, int(sample_window.height))
            sample_positive, sample_negative = src.read(
                [first_band, second_band],
                window=sample_window,
            ).astype(np.float32)
            sample_band_masks = src.read_masks(
                [first_band, second_band],
                window=sample_window,
            )
            sample_dataset_mask = src.dataset_mask(
                window=sample_window,
            )
            sample_transform = window_transform(sample_window, src.transform)
            sample_index_values, sample_valid_source = self._calculate_index(
                sample_positive,
                sample_negative,
            )
            sample_valid_source &= (
                np.all(sample_band_masks > 0, axis=0) & (sample_dataset_mask > 0)
            )
            sample_roi_mask = geometry_mask(
                [mapping(source_geometry)],
                out_shape=(sample_height, sample_width),
                transform=sample_transform,
                invert=True,
                all_touched=True,
            )
            analysis_sample_valid = (
                sample_roi_mask
                & np.isfinite(sample_index_values)
                & sample_valid_source
            )
            if analysis_min is not None:
                analysis_sample_valid &= sample_index_values >= analysis_min
            if analysis_max is not None:
                analysis_sample_valid &= sample_index_values <= analysis_max
            sample_values = sample_index_values[analysis_sample_valid]
            if not sample_values.size:
                raise ValueError(
                    f"El ROI no contiene muestras {index_name} validas dentro del filtro de analisis.",
                )

            source_width = max(width * 4, int(np.ceil(source_window.width)))
            source_height = max(height * 4, int(np.ceil(source_window.height)))
            positive, negative = src.read(
                [first_band, second_band],
                window=source_window,
                out_shape=(2, source_height, source_width),
                resampling=Resampling.average,
            ).astype(np.float32)
            band_masks = src.read_masks(
                [first_band, second_band],
                window=source_window,
                out_shape=(2, source_height, source_width),
                resampling=Resampling.nearest,
            )
            dataset_mask = src.dataset_mask(
                window=source_window,
                out_shape=(source_height, source_width),
                resampling=Resampling.nearest,
            )
            source_transform = window_transform(source_window, src.transform) * Affine.scale(
                source_window.width / source_width,
                source_window.height / source_height,
            )
            positive_values, valid_source = self._calculate_index(positive, negative)
            valid_source &= np.all(band_masks > 0, axis=0) & (dataset_mask > 0)
            source_values = np.where(valid_source, positive_values, np.nan).astype(np.float32)
            oversample = 4
            fine_height = height * oversample
            fine_width = width * oversample
            fine_transform = destination_transform * Affine.scale(1 / oversample, 1 / oversample)
            fine_index = np.full((fine_height, fine_width), np.nan, dtype=np.float32)
            fine_valid = np.zeros((fine_height, fine_width), dtype=np.uint8)
            reproject(
                source=source_values,
                destination=fine_index,
                src_transform=source_transform,
                src_crs=src.crs,
                src_nodata=np.nan,
                dst_transform=fine_transform,
                dst_crs=metric_crs,
                dst_nodata=np.nan,
                # Preserve the source index samples; aggregation to cells
                # happens explicitly below over the aligned subgrid.
                resampling=Resampling.nearest,
            )
            reproject(
                source=valid_source.astype(np.uint8),
                destination=fine_valid,
                src_transform=source_transform,
                src_crs=src.crs,
                dst_transform=fine_transform,
                dst_crs=metric_crs,
                dst_nodata=0,
                resampling=Resampling.nearest,
            )
        fine_roi_mask = geometry_mask(
            [mapping(metric_geometry)],
            out_shape=(fine_height, fine_width),
            transform=fine_transform,
            invert=True,
            all_touched=True,
        )
        fine_sample_valid = (
            fine_roi_mask
            & np.isfinite(fine_index)
            & (fine_valid > 0)
        )
        if analysis_min is not None:
            fine_sample_valid &= fine_index >= analysis_min
        if analysis_max is not None:
            fine_sample_valid &= fine_index <= analysis_max
        index_values, cell_areas_m2 = self._aggregate_cell_values(
            fine_index,
            fine_sample_valid,
            height,
            width,
            oversample,
            cell_value_mode,
            cell_size_m,
        )
        roi_mask = self._effective_cell_areas(
            metric_geometry,
            height,
            width,
            destination_transform,
            cell_size_m,
        ) > 0
        roi_valid = roi_mask & np.isfinite(index_values) & (cell_areas_m2 > 0)
        class_valid = roi_valid.copy()
        values = index_values[class_valid]
        if not values.size:
            raise ValueError(
                f"El ROI no contiene celdas {index_name} validas dentro del filtro de analisis.",
            )
        active_min = float(np.min(sample_values)) if analysis_min is None else float(analysis_min)
        active_max = float(np.max(sample_values)) if analysis_max is None else float(analysis_max)
        if active_max <= active_min:
            raise ValueError("El rango activo del indice debe tener amplitud positiva.")

        classification_values = values
        breaks = self._classification_breaks(
            classification_values,
            zone_count,
            classification_method,
            active_min,
            active_max,
            manual_breaks,
        )
        initial_zones = np.zeros((height, width), dtype=np.uint8)
        initial_zones[class_valid] = (
            np.digitize(index_values[class_valid], breaks[1:-1], right=False) + 1
        ).astype(np.uint8)
        final_zones = self._regularize_zones(
            initial_zones,
            class_valid,
            index_values,
            breaks,
            detail_level,
            cell_areas_m2,
        )
        debug_before = self._zone_debug_snapshot(
            initial_zones,
            class_valid,
            index_values,
            cell_areas_m2,
            zone_count,
        )
        debug_after = self._zone_debug_snapshot(
            final_zones,
            class_valid,
            index_values,
            cell_areas_m2,
            zone_count,
        )
        colors = self._zone_display_palette(index_name, zone_count)
        grid_footprint = Polygon(
            [
                destination_transform * (0, 0),
                destination_transform * (width, 0),
                destination_transform * (width, height),
                destination_transform * (0, height),
            ]
        )
        wgs84_footprint = project_geometry(
            pyproj.Transformer.from_crs(
                metric_crs,
                "EPSG:4326",
                always_xy=True,
            ).transform,
            grid_footprint,
        )
        west, south, east, north = wgs84_footprint.bounds
        valid_area_m2 = float(np.sum(cell_areas_m2[class_valid]))
        # El histograma de la prescripcion debe reflejar la distribucion de los
        # valores de celda que realmente alimentan la zonificacion final.
        field_mean = self._weighted_mean(
            index_values[class_valid].astype(np.float64),
            cell_areas_m2[class_valid].astype(np.float64),
        )
        if field_mean is None:
            field_mean = float(np.mean(sample_values, dtype=np.float64))
        legend: list[dict[str, Any]] = []
        for zone_index, color in enumerate(colors, 1):
            zone_mask = final_zones == zone_index
            zone_values = index_values[zone_mask & np.isfinite(index_values)]
            zone_weights = cell_areas_m2[zone_mask & np.isfinite(index_values)]
            initial_mask = initial_zones == zone_index
            mean_value = self._weighted_mean(
                zone_values.astype(np.float64),
                zone_weights.astype(np.float64),
            )
            if mean_value is None:
                mean_value = float((breaks[zone_index - 1] + breaks[zone_index]) / 2)
            percentile_min, percentile_max = self._class_percentiles(zone_count, zone_index)
            zone_area_m2 = float(np.sum(cell_areas_m2[zone_mask]))
            coverage_percent = (zone_area_m2 / valid_area_m2 * 100) if valid_area_m2 > 0 else 0.0
            deviation_percent = (
                ((mean_value - field_mean) / field_mean) * 100
                if field_mean not in (None, 0)
                else 0.0
            )
            legend.append(
                {
                    "class_id": zone_index,
                    "label": self._index_zone_label(index_name, zone_index, zone_count),
                    "ndvi_min": float(breaks[zone_index - 1]),
                    "ndvi_max": float(breaks[zone_index]),
                    "percentile_min": percentile_min,
                    "percentile_max": percentile_max,
                    "mean": float(mean_value),
                    "color": "#" + "".join(f"{channel:02x}" for channel in color),
                    "cell_count": int(np.count_nonzero(zone_mask)),
                    "initial_cell_count": int(np.count_nonzero(initial_mask)),
                    "area_hectares": zone_area_m2 / 10_000,
                    "coverage_percent": float(coverage_percent),
                    "deviation_percent": float(deviation_percent),
                }
            )
        first_cell = destination_transform * (0, 0)
        last_cell = destination_transform * (width, height)
        return {
            "index_name": index_name,
            "zone_count": zone_count,
            "cell_size_m": cell_size_m,
            "grid_angle_deg": grid_angle_deg,
            "classification_method": classification_method,
            "cell_value_mode": cell_value_mode,
            "detail_level": detail_level,
            "field_mean": float(field_mean) if field_mean is not None else None,
            "bounds": [[south, west], [north, east]],
            "valid_cell_count": int(np.count_nonzero(class_valid)),
            "area_hectares": valid_area_m2 / 10_000,
            "legend": legend,
            "zones": final_zones,
            "initial_zones": initial_zones,
            "final_zones": final_zones,
            "index_values": index_values,
            "cell_areas_m2": cell_areas_m2,
            "histogram": self._classification_histogram(
                classification_values,
                breaks,
                display_minimum=active_min,
                display_maximum=active_max,
            ),
            "debug": {
                "alignment": {
                    "roi_input_crs": "EPSG:4326",
                    "raster_crs": source_crs.to_string(),
                    "grid_crs": metric_crs.to_string(),
                    "raster_transform": tuple(src.transform) if "src" in locals() else None,
                    "raster_width": int(src.width) if "src" in locals() else None,
                    "raster_height": int(src.height) if "src" in locals() else None,
                    "raster_bounds": [
                        float(src.bounds.left),
                        float(src.bounds.bottom),
                        float(src.bounds.right),
                        float(src.bounds.top),
                    ]
                    if "src" in locals()
                    else None,
                    "roi_bounds_wgs84": [float(value) for value in geom.bounds],
                    "roi_bounds_raster": [float(value) for value in source_geometry.bounds],
                    "grid_bounds": [float(left), float(bottom), float(right), float(top)],
                    "grid_first_cell_origin": [float(first_cell[0]), float(first_cell[1])],
                    "grid_last_cell_corner": [float(last_cell[0]), float(last_cell[1])],
                },
                "before": debug_before,
                "after": debug_after,
            },
            "thresholds": [float(value) for value in breaks],
            "colors": colors,
            "transform": destination_transform,
            "crs": metric_crs,
            "geometry": metric_geometry,
        }

    def ndvi_zoning_map(
        self,
        geom: Any,
        index_name: str = "NDVI",
        zone_count: int = 4,
        cell_size_m: float = 3.0,
        grid_angle_deg: float = 0.0,
        classification_method: str = "quantiles",
        cell_value_mode: str = "mean",
        manual_breaks: list[float] | tuple[float, ...] | None = None,
        detail_level: float = 1.0,
        analysis_min: float | None = None,
        analysis_max: float | None = None,
    ) -> dict[str, Any]:
        data = self._prepare_index_classification(
            index_name,
            geom,
            zone_count,
            cell_size_m,
            grid_angle_deg,
            analysis_min,
            analysis_max,
            classification_method,
            cell_value_mode,
            manual_breaks,
            detail_level,
        )
        rgba = np.zeros((data["zones"].shape[0], data["zones"].shape[1], 4), dtype=np.uint8)
        for zone_index, color in enumerate(data["colors"], 1):
            zone_mask = data["zones"] == zone_index
            rgba[zone_mask, :3] = color
            rgba[zone_mask, 3] = 255
        zoning_id = uuid4().hex
        tile_url = self._render_classification_artifact(
            zoning_id,
            rgba,
            data["transform"],
            data["crs"],
            data["geometry"],
        )
        grid_url = self._save_classification_grid_geojson(
            zoning_id,
            data["zones"] > 0,
            data["transform"],
            data["crs"],
        )
        geojson_url, feature_count = self._save_classification_fill_geojson(
            zoning_id,
            data["zones"],
            data["index_values"],
            data["transform"],
            data["crs"],
            data["geometry"],
            data["colors"],
            data["index_name"],
        )
        data["debug"]["alignment"]["feature_count"] = int(feature_count)
        logger.warning(
            "[zoning-alignment] raster_crs=%s grid_crs=%s roi_bounds_raster=%s grid_bounds=%s features=%s",
            data["debug"]["alignment"]["raster_crs"],
            data["debug"]["alignment"]["grid_crs"],
            data["debug"]["alignment"]["roi_bounds_raster"],
            data["debug"]["alignment"]["grid_bounds"],
            feature_count,
        )
        return {
            "status": "ok",
            "stage": "zoning",
            "title": f"Zonificacion {data['index_name']}",
            "index_name": data["index_name"],
            "zoning_id": zoning_id,
            "image_url": f"/static/prescriptions/{zoning_id}.png",
            "tile_url": tile_url,
            "grid_url": grid_url,
            "geojson_url": geojson_url,
            "bounds": data["bounds"],
            "zone_count": data["zone_count"],
            "cell_size_m": data["cell_size_m"],
            "grid_angle_deg": data["grid_angle_deg"],
            "classification_method": data["classification_method"],
            "cell_value_mode": data["cell_value_mode"],
            "detail_level": data["detail_level"],
            "field_mean": data["field_mean"],
            "histogram": data["histogram"],
            "thresholds": data["thresholds"],
            "valid_cell_count": data["valid_cell_count"],
            "area_hectares": data["area_hectares"],
            "legend": data["legend"],
            "debug": data["debug"],
        }

    def prescription_map_with_doses(
        self,
        geom: Any,
        index_name: str = "NDVI",
        zone_count: int = 4,
        cell_size_m: float = 3.0,
        grid_angle_deg: float = 0.0,
        classification_method: str = "quantiles",
        cell_value_mode: str = "mean",
        manual_breaks: list[float] | tuple[float, ...] | None = None,
        detail_level: float = 1.0,
        analysis_min: float | None = None,
        analysis_max: float | None = None,
        doses: list[float] | tuple[float, ...] | None = None,
    ) -> dict[str, Any]:
        data = self._prepare_index_classification(
            index_name,
            geom,
            zone_count,
            cell_size_m,
            grid_angle_deg,
            analysis_min,
            analysis_max,
            classification_method,
            cell_value_mode,
            manual_breaks,
            detail_level,
        )
        rgba = np.zeros((data["zones"].shape[0], data["zones"].shape[1], 4), dtype=np.uint8)
        for class_id, color in enumerate(data["colors"], 1):
            zone_mask = data["zones"] == class_id
            rgba[zone_mask, :3] = color
            rgba[zone_mask, 3] = 255
        prescription_id = uuid4().hex
        tile_url = self._render_classification_artifact(
            prescription_id,
            rgba,
            data["transform"],
            data["crs"],
            data["geometry"],
        )
        grid_url = self._save_classification_grid_geojson(
            prescription_id,
            data["zones"] > 0,
            data["transform"],
            data["crs"],
        )
        geojson_url, feature_count = self._save_classification_fill_geojson(
            prescription_id,
            data["zones"],
            data["index_values"],
            data["transform"],
            data["crs"],
            data["geometry"],
            data["colors"],
            data["index_name"],
        )
        data["debug"]["alignment"]["feature_count"] = int(feature_count)
        logger.warning(
            "[prescription-alignment] raster_crs=%s grid_crs=%s roi_bounds_raster=%s grid_bounds=%s features=%s",
            data["debug"]["alignment"]["raster_crs"],
            data["debug"]["alignment"]["grid_crs"],
            data["debug"]["alignment"]["roi_bounds_raster"],
            data["debug"]["alignment"]["grid_bounds"],
            feature_count,
        )
        legend = [dict(zone) for zone in data["legend"]]
        if doses is not None:
            if len(doses) != len(legend):
                raise ValueError(
                    f"Debes enviar exactamente {len(legend)} dosis, una por cada zona.",
                )
            try:
                normalized_doses = [float(value) for value in doses]
            except (TypeError, ValueError) as exc:
                raise ValueError("Cada dosis debe ser numerica.") from exc
            for zone, dosage in zip(legend, normalized_doses, strict=True):
                zone["dosage"] = dosage
        else:
            for zone in legend:
                zone["dosage"] = 0.0
        json_url = self._save_prescription_geojson(
            prescription_id,
            data,
            legend,
        )
        return {
            "status": "ok",
            "stage": "prescription",
            "title": f"Mapa de Prescripcion {data['index_name']}",
            "index_name": data["index_name"],
            "prescription_id": prescription_id,
            "image_url": f"/static/prescriptions/{prescription_id}.png",
            "tile_url": tile_url,
            "grid_url": grid_url,
            "geojson_url": geojson_url,
            "json_url": json_url,
            "bounds": data["bounds"],
            "zone_count": zone_count,
            "cell_size_m": cell_size_m,
            "grid_angle_deg": data["grid_angle_deg"],
            "classification_method": data["classification_method"],
            "cell_value_mode": data["cell_value_mode"],
            "detail_level": data["detail_level"],
            "field_mean": data["field_mean"],
            "histogram": data["histogram"],
            "thresholds": data["thresholds"],
            "valid_cell_count": data["valid_cell_count"],
            "area_hectares": data["area_hectares"],
            "legend": legend,
            "debug": data["debug"],
        }

    def _save_prescription_geojson(
        self,
        prescription_id: str,
        data: dict[str, Any],
        legend: list[dict[str, Any]],
    ) -> str:
        """Persist the prescription using the external Pix4D-style JSON contract."""
        zones = data["zones"]
        legend_by_class = {int(item["class_id"]): item for item in legend}
        exported_zones = sorted(
            (
                int(class_id),
                {
                    "zone": int(class_id),
                    "mean": float(zone["mean"]),
                    "label": str(zone["label"]),
                    "dosage": self._export_prescription_dosage(zone.get("dosage", 0.0)),
                    "level": int(class_id),
                },
            )
            for class_id, zone in legend_by_class.items()
            if int(class_id) > 0
        )
        data_type_level = [
            {
                "dosage": zone["dosage"],
                "level": zone["level"],
            }
            for _class_id, zone in exported_zones
        ]
        rows, cols = zones.shape
        flattened_weights = zones.astype(np.int16).ravel(order="C").tolist()
        grid_transform = data["transform"]
        bottom_left_x, bottom_left_y = grid_transform * (0, rows)
        top_right_x, top_right_y = grid_transform * (cols, 0)
        to_wgs84 = pyproj.Transformer.from_crs(
            data["crs"],
            "EPSG:4326",
            always_xy=True,
        )
        west, south = to_wgs84.transform(bottom_left_x, bottom_left_y)
        east, north = to_wgs84.transform(top_right_x, top_right_y)
        self._validate_prescription_weight_data(
            flattened_weights,
            rows,
            cols,
            len(data_type_level),
        )
        collection = {
            "cellSize": data["cell_size_m"],
            "columns": cols,
            "dataType": len(data_type_level),
            "dataTypeLevel": data_type_level,
            "guid": str(UUID(hex=prescription_id)),
            "name": f"prescripcion_{prescription_id[:8]}",
            "originEndLat": north,
            "originEndLng": east,
            "originLat": south,
            "originLng": west,
            "rotation": data["grid_angle_deg"],
            "rows": rows,
            "source": "Pix4D",
            "version": 1,
            "weightData": flattened_weights,
            "workType": 1,
        }
        output_path = self.settings.output_dir / "prescriptions" / f"{prescription_id}.json"
        output_path.write_text(
            json.dumps(collection, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        return f"/prescriptions/{prescription_id}/download.json"

    def prescription_map(
        self,
        geom: Any,
        zone_count: int = 4,
        cell_size_m: float = 3.0,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> dict[str, Any]:
        if not 2 <= zone_count <= 10:
            raise ValueError("El mapa de prescripción admite entre 2 y 10 zonas.")
        if not 1 <= cell_size_m <= 50:
            raise ValueError("El tamaño de celda debe estar entre 1 y 50 metros.")

        raster_path = self._path()
        with rasterio.open(raster_path) as src:
            if not src.crs:
                raise ValueError(
                    "El ortomosaico necesita un CRS para construir una grilla métrica.",
                )
            source_crs = pyproj.CRS.from_user_input(src.crs)
            uses_meters = source_crs.is_projected and all(
                abs((axis.unit_conversion_factor or 0) - 1) < 1e-9
                for axis in source_crs.axis_info
            )
            if uses_meters:
                metric_crs = source_crs
            else:
                to_wgs84 = pyproj.Transformer.from_crs(
                    source_crs,
                    "EPSG:4326",
                    always_xy=True,
                )
                center_x = (src.bounds.left + src.bounds.right) / 2
                center_y = (src.bounds.bottom + src.bounds.top) / 2
                longitude, latitude = to_wgs84.transform(center_x, center_y)
                utm_zone = max(1, min(60, int((longitude + 180) // 6) + 1))
                metric_crs = pyproj.CRS.from_epsg(
                    (32600 if latitude >= 0 else 32700) + utm_zone,
                )

            metric_geometry = project_geometry(
                pyproj.Transformer.from_crs(
                    "EPSG:4326",
                    metric_crs,
                    always_xy=True,
                ).transform,
                geom,
            )
            if metric_geometry.is_empty or not metric_geometry.is_valid:
                raise ValueError("El ROI seleccionado no contiene una geometría válida.")
            left, bottom, right, top = metric_geometry.bounds
            width = max(1, int(np.ceil((right - left) / cell_size_m)))
            height = max(1, int(np.ceil((top - bottom) / cell_size_m)))
            destination_transform = Affine(
                cell_size_m,
                0,
                left,
                0,
                -cell_size_m,
                top,
            )
            total_cells = width * height
            if total_cells > 150_000:
                minimum_size = cell_size_m * (total_cells / 150_000) ** 0.5
                raise ValueError(
                    "La grilla generaría demasiadas celdas. "
                    f"Usa un tamaño de al menos {minimum_size:.1f} metros.",
                )

            red_band, nir_band = self._ndvi_bands(raster_path, self.sensor)
            red = np.full((height, width), np.nan, dtype=np.float32)
            nir = np.full((height, width), np.nan, dtype=np.float32)
            for band_index, destination in ((red_band, red), (nir_band, nir)):
                reproject(
                    source=rasterio.band(src, band_index),
                    destination=destination,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    src_nodata=src.nodata,
                    dst_transform=destination_transform,
                    dst_crs=metric_crs,
                    dst_nodata=np.nan,
                    resampling=Resampling.average,
                )

        roi_mask = geometry_mask(
            [mapping(metric_geometry)],
            out_shape=(height, width),
            transform=destination_transform,
            invert=True,
        )
        valid = (
            roi_mask
            & np.isfinite(red)
            & np.isfinite(nir)
            & (red > 0)
            & (nir > 0)
        )
        denominator = nir + red
        valid &= np.isfinite(denominator) & (denominator != 0)
        ndvi = np.full_like(red, np.nan, dtype=np.float32)
        ndvi[valid] = (nir[valid] - red[valid]) / denominator[valid]
        if minimum is not None:
            valid &= ndvi >= minimum
        if maximum is not None:
            valid &= ndvi <= maximum
        values = ndvi[valid]
        if not values.size:
            raise ValueError(
                "El ROI no contiene celdas NDVI válidas dentro del rango del histograma.",
            )

        breaks = np.quantile(values, np.linspace(0, 1, zone_count + 1))
        zones = np.zeros((height, width), dtype=np.uint8)
        zones[valid] = (
            np.digitize(ndvi[valid], breaks[1:-1], right=True) + 1
        ).astype(np.uint8)
        colors = self._zone_palette("NDVI", zone_count)
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        for zone_index, color in enumerate(colors, 1):
            zone_mask = zones == zone_index
            rgba[zone_mask, :3] = color
            rgba[zone_mask, 3] = 255

        # Cada celda métrica se amplía únicamente para visualización. Un borde
        # carbón de un píxel marca el límite compartido sin introducir huecos
        # y ocupa una proporción pequeña frente al relleno NDVI.
        render_scale = 16
        rendered = np.repeat(
            np.repeat(rgba, render_scale, axis=0),
            render_scale,
            axis=1,
        )
        prescription_id = uuid4().hex
        prescription_dir = self.settings.output_dir / "prescriptions"
        prescription_dir.mkdir(parents=True, exist_ok=True)
        image_path = prescription_dir / f"{prescription_id}.png"
        Image.fromarray(rendered, mode="RGBA").save(image_path)

        projected_bounds = array_bounds(height, width, destination_transform)
        west, south, east, north = transform_bounds(
            metric_crs,
            "EPSG:4326",
            *projected_bounds,
            densify_pts=21,
        )
        legend = []
        five_zone_labels = [
            "Severo",
            "Deficiente",
            "Moderado",
            "Bueno",
            "Excelente",
        ]
        four_zone_labels = ["Severo", "Moderado", "Bueno", "Excelente"]
        for zone_index, color in enumerate(colors, 1):
            zone_mask = zones == zone_index
            zone_values = ndvi[zone_mask]
            legend.append(
                {
                    "zone": zone_index,
                    "label": (
                        four_zone_labels[zone_index - 1]
                        if zone_count == 4
                        else five_zone_labels[zone_index - 1]
                        if zone_count == 5
                        else "Severo"
                        if zone_index == 1
                        else "Excelente"
                        if zone_index == zone_count
                        else f"Nivel {zone_index}"
                    ),
                    "minimum": float(breaks[zone_index - 1]),
                    "maximum": float(breaks[zone_index]),
                    "mean": float(np.mean(zone_values))
                    if zone_values.size
                    else float(
                        (breaks[zone_index - 1] + breaks[zone_index]) / 2,
                    ),
                    "color": "#" + "".join(f"{channel:02x}" for channel in color),
                    "cell_count": int(np.count_nonzero(zone_mask)),
                    "area_hectares": float(
                        np.count_nonzero(zone_mask) * cell_size_m**2 / 10_000,
                    ),
                },
            )
        return {
            "status": "ok",
            "prescription_id": prescription_id,
            "image_url": f"/static/prescriptions/{prescription_id}.png",
            "bounds": [[south, west], [north, east]],
            "zone_count": zone_count,
            "cell_size_m": cell_size_m,
            "range_min": float(minimum) if minimum is not None else None,
            "range_max": float(maximum) if maximum is not None else None,
            "valid_cell_count": int(np.count_nonzero(valid)),
            "area_hectares": float(
                np.count_nonzero(valid) * cell_size_m**2 / 10_000,
            ),
            "legend": legend,
        }

    def _ndvi_bands(self, path: Path | None = None, sensor: str | None = None) -> tuple[int, int]:
        """Return the red and NIR band indexes configured in the raster."""
        selected_sensor = sensor or self.sensor
        if selected_sensor == "mavic3m":
            with rasterio.open(path or self._path()) as src:
                if src.count < 4:
                    raise ValueError("DJI Mavic 3M requiere al menos 4 bandas: Green, Red, Red Edge y NIR.")
                # Exportación DJI/Pix4D habitual: Blue, Green, Red, RedEdge, NIR.
                # Algunos mosaicos omiten Blue y conservan: Green, Red, RedEdge, NIR.
                return 2, 4
        if selected_sensor == "micasense":
            with rasterio.open(path or self._path()) as src:
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
        with rasterio.open(path or self._path()) as src:
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
                    f"El raster '{(path or self._path()).name}' no contiene bandas Red y NIR; "
                    f"tiene {src.count} banda(s): {', '.join(src.descriptions)}. "
                    "Para NDVI se requiere un GeoTIFF multiespectral."
                )
            return red, nir

    @staticmethod
    def _wavelength_nm(value: str) -> float | None:
        numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", value)
        if not numbers:
            return None
        wavelength = float(numbers[0])
        return wavelength * 1000 if 0 < wavelength < 10 else wavelength

    @classmethod
    def _band_role_from_text(cls, value: str) -> str | None:
        normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        # Red Edge must be rejected before looking for the generic word Red.
        if re.search(r"\b(red edge|rededge|re)\b", normalized):
            return "rededge"
        for role, pattern in (
            ("blue", r"\b(blue|azul|b02)\b"),
            ("green", r"\b(green|verde|b03)\b"),
            ("red", r"\b(red|rojo|b04)\b"),
        ):
            if re.search(pattern, normalized):
                return role
        return None

    @staticmethod
    def _band_role_from_wavelength(wavelength_nm: float | None) -> str | None:
        if wavelength_nm is None:
            return None
        if 430 <= wavelength_nm < 510:
            return "blue"
        if 510 <= wavelength_nm < 600:
            return "green"
        if 600 <= wavelength_nm < 700:
            return "red"
        if 700 <= wavelength_nm < 760:
            return "rededge"
        if wavelength_nm >= 760:
            return "nir"
        return None

    @classmethod
    def _dataset_wavelengths(cls, src: Any) -> list[float] | None:
        for key, value in src.tags().items():
            if "wavelength" not in key.lower():
                continue
            numbers = re.findall(r"\d+(?:\.\d+)?", str(value))
            if len(numbers) < src.count:
                continue
            wavelengths = [float(number) for number in numbers[: src.count]]
            return [number * 1000 if 0 < number < 10 else number for number in wavelengths]
        return None

    def _rgb_bands(
        self,
        src: Any | None = None,
        *,
        path: Path | None = None,
        sensor: str | None = None,
    ) -> tuple[int, int, int]:
        """Resolve display bands from color interpretation and band metadata."""
        if src is None:
            with rasterio.open(path or self._path()) as dataset:
                return self._rgb_bands(dataset, sensor=sensor)

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

        selected_sensor = sensor or self.sensor
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
    ) -> dict[str, int]:
        """Resolve multispectral semantic roles for NDWI/NDRE style formulas."""
        if src is None:
            with rasterio.open(path or self._path()) as dataset:
                return self._multispectral_band_roles(dataset, sensor=sensor)

        roles: dict[str, int] = {}
        dataset_wavelengths = self._dataset_wavelengths(src)
        for index in range(1, src.count + 1):
            description = src.descriptions[index - 1] or ""
            tags = src.tags(index)
            metadata_text = " ".join(
                [description, *[f"{key} {value}" for key, value in tags.items()]],
            )
            role = self._band_role_from_text(metadata_text)
            if role not in {"blue", "green", "red", "rededge", "nir"}:
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
            if role in {"blue", "green", "red", "rededge", "nir"}:
                roles.setdefault(role, index)

        selected_sensor = sensor or self.sensor
        if selected_sensor == "mavic3m" and src.count >= 4:
            roles.setdefault("green", 1)
            roles.setdefault("red", 2)
            roles.setdefault("rededge", 3)
            roles.setdefault("nir", 4)
        elif selected_sensor == "micasense":
            if src.count >= 6:
                roles.setdefault("blue", 1)
                roles.setdefault("green", 2)
                roles.setdefault("red", 4)
                roles.setdefault("rededge", 5)
                roles.setdefault("nir", 6)
            elif src.count >= 5:
                roles.setdefault("blue", 1)
                roles.setdefault("green", 2)
                roles.setdefault("red", 3)
                roles.setdefault("nir", 4)
                roles.setdefault("rededge", 5)

        missing = [role for role in ("green", "rededge", "nir") if role not in roles]
        if missing:
            details = ", ".join(
                f"banda {index}: {src.descriptions[index - 1] or 'sin descripcion'}; tags={src.tags(index)}"
                for index in range(1, src.count + 1)
            )
            message = (
                f"No se pudieron identificar las bandas multiespectrales del raster '{Path(src.name).name}'. "
                f"Faltan metadatos para: {', '.join(missing)}. {details}"
            )
            logger.error(message)
            raise ValueError(message)
        return roles

    def _index_bands(self, name: str) -> tuple[int, int]:
        """Return bands as (positive, negative) for the normalized difference."""
        if name == "NDVI":
            red, nir = self._ndvi_bands()
            return nir, red
        if self.sensor == "mavic3m":
            bands = {"NDWI": (1, 4), "NDRE": (4, 3)}.get(name)
        elif self.sensor == "micasense":
            bands = {"NDWI": (2, 6), "NDRE": (6, 5)}.get(name)
        else:
            bands = None
        if not bands:
            raise ValueError("El indice requiere un ortomosaico multiespectral compatible.")
        return bands

    @staticmethod
    def _calculate_index(positive: np.ndarray, negative: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        positive = positive.astype(np.float32, copy=False)
        negative = negative.astype(np.float32, copy=False)
        denominator = positive + negative
        valid = (positive > 0) & (negative > 0) & np.isfinite(positive) & np.isfinite(negative) & (denominator != 0)
        values = np.divide(positive - negative, denominator, out=np.zeros_like(denominator), where=valid)
        return values, valid

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
        matrix_key = "ndvi_matrix" if name == "NDVI" else "matrix"
        mask_key = "ndvi_mask" if name == "NDVI" else "mask"
        matrix = np.asarray(response.get(matrix_key), dtype=np.float32)
        mask = np.asarray(response.get(mask_key), dtype=bool)
        if matrix.size == 0 or mask.size == 0:
            return np.asarray([], dtype=np.float32)
        values = ((matrix / 255.0) * 2.0 - 1.0) if name == "NDVI" else matrix
        return values[np.isfinite(values) & mask]

    @staticmethod
    def _build_equalization_cdf(
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
        return max(1, int((src.width * src.height / max_pixels) ** 0.5))

    @staticmethod
    def normalize(band: np.ndarray) -> np.ndarray:
        band = band.astype(np.float32)
        valid = band > 0
        if not np.any(valid):
            return np.zeros_like(band, dtype=np.uint8)
        low, high = np.nanmin(band[valid]), np.nanmax(band[valid])
        return np.zeros_like(band, dtype=np.uint8) if low == high else ((band - low) / (high - low) * 255).clip(0, 255).astype(np.uint8)

    def _rgb_profile_key(self, path: Path | None = None) -> tuple[str, int, int]:
        raster_path = (path or self._path()).resolve()
        stat = raster_path.stat()
        return str(raster_path), stat.st_size, stat.st_mtime_ns

    def tile_cache_version(self, path: Path | None = None) -> str:
        """Return a browser cache key tied to both the file and renderer."""
        _, _, mtime_ns = self._rgb_profile_key(path)
        return f"{mtime_ns}-{self.RGB_RENDER_VERSION}"

    def index_tile_cache_version(self, path: Path | None = None) -> str:
        _, _, mtime_ns = self._rgb_profile_key(path)
        return f"{mtime_ns}-{self.INDEX_RENDER_VERSION}"

    def _tile_cache_path(
        self,
        kind: str,
        version: str,
        z: int,
        x: int,
        y: int,
        variant: str = "default",
    ) -> Path:
        raster_path = self._path().resolve()
        raster_scope = f"{raster_path.stem}-{version}"
        safe_variant = re.sub(r"[^0-9A-Za-z._-]+", "_", variant)
        return (
            self.settings.cache_dir
            / "tiles"
            / kind
            / raster_scope
            / str(z)
            / str(x)
            / f"{y}-{safe_variant}.png"
        )

    @staticmethod
    def _read_tile_cache(cache_path: Path) -> bytes | None:
        try:
            return cache_path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            return None

    @staticmethod
    def _write_tile_cache(cache_path: Path, content: bytes) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=cache_path.parent,
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_path = Path(temporary_file.name)
        temporary_path.replace(cache_path)

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
        n = 2 ** z
        left, right = x / n * 360 - 180, (x + 1) / n * 360 - 180
        top = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y / n))))
        bottom = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + 1) / n))))
        return left, bottom, right, top

    @staticmethod
    def tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
        """Return exact XYZ tile bounds in the native Leaflet grid."""
        origin = 20_037_508.342789244
        span = (origin * 2) / (2**z)
        left = -origin + x * span
        right = left + span
        top = origin - y * span
        bottom = top - span
        return left, bottom, right, top

    def _reproject_rgb_tile(
        self,
        src: Any,
        z: int,
        x: int,
        y: int,
    ) -> tuple[np.ndarray, np.ndarray, Affine]:
        """Warp RGB and validity into one exact 256 px Web Mercator tile."""
        if not src.crs:
            raise ValueError("El ortomosaico no tiene CRS y no puede reproyectarse a Web Mercator.")
        size = self.RGB_TILE_SIZE
        mercator_bounds = self.tile_bounds_mercator(z, x, y)
        dst_transform = rasterio.transform.from_bounds(*mercator_bounds, size, size)
        profile = self.rgb_render_profile(src)
        bands = profile["bands"]
        destination_dtype = np.result_type(
            *(np.dtype(src.dtypes[index - 1]) for index in bands),
        )
        rgb = np.zeros((3, size, size), dtype=destination_dtype)
        for destination, band_index in zip(rgb, bands):
            options: dict[str, Any] = {
                "source": rasterio.band(src, band_index),
                "destination": destination,
                "src_transform": src.transform,
                "src_crs": src.crs,
                "dst_transform": dst_transform,
                "dst_crs": "EPSG:3857",
                "resampling": Resampling.nearest,
            }
            nodata = src.nodatavals[band_index - 1]
            if nodata is not None:
                options["src_nodata"] = nodata
            reproject(**options)

        destination_mask = np.zeros((size, size), dtype=np.uint8)
        source_bounds = transform_bounds(
            "EPSG:3857",
            src.crs,
            *mercator_bounds,
            densify_pts=21,
        )
        try:
            source_window = from_bounds(*source_bounds, transform=src.transform).intersection(
                Window(0, 0, src.width, src.height),
            )
        except Exception:
            source_window = None
        if source_window is not None and source_window.width > 0 and source_window.height > 0:
            sample_scale = max(1.0, max(source_window.width, source_window.height) / 2048)
            source_width = max(1, int(np.ceil(source_window.width / sample_scale)))
            source_height = max(1, int(np.ceil(source_window.height / sample_scale)))
            source_rgb = src.read(
                list(bands),
                window=source_window,
                out_shape=(3, source_height, source_width),
                resampling=Resampling.nearest,
            )
            source_valid = self._rgb_valid_mask(
                src,
                bands,
                source_rgb,
                window=source_window,
            )
            source_transform = window_transform(source_window, src.transform) * Affine.scale(
                source_window.width / source_width,
                source_window.height / source_height,
            )
            reproject(
                source=source_valid.astype(np.uint8),
                destination=destination_mask,
                src_transform=source_transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs="EPSG:3857",
                resampling=Resampling.nearest,
            )

        valid = (
            (destination_mask > 0)
            & np.all(np.isfinite(rgb), axis=0)
            & np.any(rgb != 0, axis=0)
        )
        return self._render_rgb_values(rgb, profile), valid, dst_transform

    def _reproject_index_matrix(
        self,
        src: Any,
        name: str,
        z: int,
        x: int,
        y: int,
    ) -> tuple[np.ndarray, np.ndarray, Affine]:
        """Calculate the native index, then warp its float matrix to one XYZ tile."""
        if not src.crs:
            raise ValueError("El ortomosaico no tiene CRS y no puede reproyectar el indice.")
        size = self.RGB_TILE_SIZE
        mercator_bounds = self.tile_bounds_mercator(z, x, y)
        dst_transform = rasterio.transform.from_bounds(*mercator_bounds, size, size)
        tile_values = np.full((size, size), np.nan, dtype=np.float32)
        tile_valid = np.zeros((size, size), dtype=np.uint8)
        source_bounds = transform_bounds(
            "EPSG:3857",
            src.crs,
            *mercator_bounds,
            densify_pts=21,
        )
        try:
            source_window = from_bounds(*source_bounds, transform=src.transform).intersection(
                Window(0, 0, src.width, src.height),
            )
        except Exception:
            source_window = None
        if source_window is None or source_window.width <= 0 or source_window.height <= 0:
            return tile_values, tile_valid.astype(bool), dst_transform

        sample_scale = max(1.0, max(source_window.width, source_window.height) / 2048)
        source_width = max(1, int(np.ceil(source_window.width / sample_scale)))
        source_height = max(1, int(np.ceil(source_window.height / sample_scale)))
        bands = self._index_bands(name)
        positive, negative = src.read(
            list(bands),
            window=source_window,
            out_shape=(2, source_height, source_width),
            # Preserve local spectral contrast so the overlay reads with more
            # color intensity on top of the RGB base layer.
            resampling=Resampling.nearest,
        ).astype(np.float32)
        values, valid = self._calculate_index(positive, negative)
        mask_options = {
            "window": source_window,
            "out_shape": (2, source_height, source_width),
            "resampling": Resampling.nearest,
        }
        band_masks = src.read_masks(list(bands), **mask_options)
        dataset_mask = src.dataset_mask(
            window=source_window,
            out_shape=(source_height, source_width),
            resampling=Resampling.nearest,
        )
        valid &= np.all(band_masks > 0, axis=0) & (dataset_mask > 0)
        source_values = np.where(valid, values, np.nan).astype(np.float32)
        source_transform = window_transform(source_window, src.transform) * Affine.scale(
            source_window.width / source_width,
            source_window.height / source_height,
        )
        reproject(
            source=source_values,
            destination=tile_values,
            src_transform=source_transform,
            src_crs=src.crs,
            src_nodata=np.nan,
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            dst_nodata=np.nan,
            # Avoid smoothing the computed index during tile reprojection.
            resampling=Resampling.nearest,
        )
        reproject(
            source=valid.astype(np.uint8),
            destination=tile_valid,
            src_transform=source_transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            resampling=Resampling.nearest,
        )
        return tile_values, (tile_valid > 0) & np.isfinite(tile_values), dst_transform

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
                cropped, cropped_transform = raster_mask(
                    source,
                    [mapping(source_geometry)],
                    crop=True,
                    filled=False,
                )
            except ValueError as exc:
                raise ValueError("El ROI no intersecta el ortomosaico activo.") from exc

            profile = source.profile.copy()
            profile.update(
                driver="GTiff",
                width=cropped.shape[2],
                height=cropped.shape[1],
                transform=cropped_transform,
                compress="deflate",
                tiled=False,
            )
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            fill_value = source.nodata if source.nodata is not None else 0
            valid_mask = np.any(~np.ma.getmaskarray(cropped), axis=0)

            with MemoryFile() as memory_file:
                with memory_file.open(**profile) as destination:
                    destination.write(cropped.filled(fill_value))
                    destination.write_mask(valid_mask.astype(np.uint8) * 255)
                    destination.update_tags(**source.tags())
                    for band_index in range(1, source.count + 1):
                        description = source.descriptions[band_index - 1]
                        if description:
                            destination.set_band_description(band_index, description)
                        destination.update_tags(band_index, **source.tags(band_index))
                    destination.colorinterp = source.colorinterp
                return memory_file.read()

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
        with rasterio.open(self._path()) as src:
            rendered, raster_mask, dst_transform = self._reproject_rgb_tile(src, z, x, y)
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
            mask = raster_mask & roi_mask
            rgba = np.dstack(
                (*rendered, np.where(mask, 255, 0).astype(np.uint8)),
            )
            output = io.BytesIO()
            Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
            return output.getvalue()

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
            positive = src.read(positive_band, window=window).astype(np.float32)
            negative = src.read(negative_band, window=window).astype(np.float32)
            transform = window_transform(window, src.transform)
            mask = geometry_mask(
                [mapping(source_geom)],
                out_shape=positive.shape,
                transform=transform,
                invert=True,
                all_touched=True,
            )
            values, valid = self._calculate_index(positive, negative)
            visible_values = values[valid & mask]
            if visible_values.size == 0:
                return None, None
            return float(np.min(visible_values)), float(np.max(visible_values))

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
        minx, miny, maxx, maxy = meta.get("response_bounds", array_bounds(height, width, transform))
        return {"bounds": [[miny, minx], [maxy, maxx]], "offset_x": round(meta["col_off"] / meta["scale"]), "offset_y": round(meta["row_off"] / meta["scale"]), "base_width": max(1, round(meta["src_width"] / meta["scale"])), "base_height": max(1, round(meta["src_height"] / meta["scale"]))}
