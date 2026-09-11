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
from typing import TYPE_CHECKING, Any, ClassVar
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

if TYPE_CHECKING:
    from geofield.services.raster_service import RasterContext



class RasterClassificationArtifactMixin:
    """Render y persistencia de artefactos de clasificacion."""

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
    
    def _path(self, context: RasterContext | None = None) -> Path:
        path = context.path if context else self.active_path or self.settings.raster_path
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
    
