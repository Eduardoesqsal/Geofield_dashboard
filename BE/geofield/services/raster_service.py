"""Servicio principal de procesamiento raster.

Encapsula lectura de ortomosaicos, tiles, recortes, reproyección y cálculo de
índices espectrales completos o acotados al ROI.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pyproj
import rasterio
from affine import Affine
from PIL import Image
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import Window, from_bounds, transform as window_transform
from shapely.geometry import mapping
from shapely.ops import transform as project_geometry

from geofield.config import Settings
from geofield.errors import RasterNotConfiguredError


class RasterService:
    """Procesamiento geoespacial; no conoce detalles de FastAPI."""

    INDEX_RAMPS = {
        "NDVI": ["ff7a00", "ff9500", "ffb000", "ffc400", "e4d200", "acf404", "57f20a", "27e833", "00b824", "009e1f"],
        "NDWI": ["c0003a", "e01a00", "ff5500", "ffaa00", "ffe066", "a8e6a0", "4dd4e0", "2b9aff", "1a4fff", "0000ff"],
        "NDRE": ["000000", "1b0a2a", "3d0965", "6b0d8a", "9b1f9e", "c43c7e", "e06030", "f08c00", "f5b800", "ffe000"],
    }
    PRESCRIPTION_ZONE_PALETTE = ["ff7a00", "ffc400", "acf404", "00b824"]
    INDEX_DOMAINS = {"NDVI": (-0.2, 0.8), "NDWI": (-0.5, 0.5), "NDRE": (-0.2, 0.8)}

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rgb_stretch: tuple[float, float] | None = None
        self.overlay: tuple[int, int, Affine] | None = None
        self.active_path: Path | None = None
        self.sensor: str | None = None
        self.crop_geometries: dict[str, Any] = {}

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
    def _class_percentiles(zone_count: int, zone_index: int) -> tuple[float, float]:
        return (
            100.0 * (zone_index - 1) / zone_count,
            100.0 * zone_index / zone_count,
        )

    def _zone_palette(self, zone_count: int) -> np.ndarray:
        ramp = np.asarray(
            [
                [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                for color in self.INDEX_RAMPS["NDVI"]
            ],
            dtype=np.uint8,
        )
        if zone_count == len(self.PRESCRIPTION_ZONE_PALETTE):
            return np.asarray(
                [
                    [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                    for color in self.PRESCRIPTION_ZONE_PALETTE
                ],
                dtype=np.uint8,
            )
        ramp_positions = np.floor(np.linspace(0, len(ramp) - 1, zone_count) + 0.5).astype(int)
        return ramp[ramp_positions]

    @staticmethod
    def _dose_ramp(count: int) -> np.ndarray:
        ramp = np.asarray(
            [
                [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                for color in RasterService.INDEX_RAMPS["NDVI"]
            ],
            dtype=np.uint8,
        )
        if count <= 1:
            return ramp[-1:].copy()
        positions = np.floor(np.linspace(0, len(ramp) - 1, count) + 0.5).astype(int)
        return ramp[positions]

    def _prepare_ndvi_classification(
        self,
        geom: Any,
        zone_count: int = 4,
        cell_size_m: float = 3.0,
        analysis_min: float | None = None,
        analysis_max: float | None = None,
    ) -> dict[str, Any]:
        if not 2 <= zone_count <= 10:
            raise ValueError("El mapa de prescripcion admite entre 2 y 10 zonas.")
        if not 1 <= cell_size_m <= 50:
            raise ValueError("El tamano de celda debe estar entre 1 y 50 metros.")

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
            left, bottom, right, top = metric_geometry.bounds
            width = max(1, int(np.ceil((right - left) / cell_size_m)))
            height = max(1, int(np.ceil((top - bottom) / cell_size_m)))
            destination_transform = Affine(cell_size_m, 0, left, 0, -cell_size_m, top)
            total_cells = width * height
            if total_cells > 150_000:
                minimum_size = cell_size_m * (total_cells / 150_000) ** 0.5
                raise ValueError(
                    "La grilla generaria demasiadas celdas. "
                    f"Usa un tamano de al menos {minimum_size:.1f} metros.",
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
        roi_valid = (
            roi_mask
            & np.isfinite(red)
            & np.isfinite(nir)
            & (red > 0)
            & (nir > 0)
        )
        denominator = nir + red
        roi_valid &= np.isfinite(denominator) & (denominator != 0)
        ndvi = np.full_like(red, np.nan, dtype=np.float32)
        ndvi[roi_valid] = (nir[roi_valid] - red[roi_valid]) / denominator[roi_valid]
        class_valid = roi_valid.copy()
        if analysis_min is not None:
            class_valid &= ndvi >= analysis_min
        if analysis_max is not None:
            class_valid &= ndvi <= analysis_max
        values = ndvi[class_valid]
        if not values.size:
            raise ValueError("El ROI no contiene celdas NDVI validas dentro del filtro de analisis.")

        breaks = np.quantile(values, np.linspace(0, 1, zone_count + 1))
        zones = np.zeros((height, width), dtype=np.uint8)
        zones[class_valid] = (
            np.digitize(ndvi[class_valid], breaks[1:-1], right=True) + 1
        ).astype(np.uint8)
        colors = self._zone_palette(zone_count)
        projected_bounds = array_bounds(height, width, destination_transform)
        west, south, east, north = transform_bounds(
            metric_crs,
            "EPSG:4326",
            *projected_bounds,
            densify_pts=21,
        )
        legend: list[dict[str, Any]] = []
        for zone_index, color in enumerate(colors, 1):
            zone_mask = zones == zone_index
            zone_values = ndvi[zone_mask]
            percentile_min, percentile_max = self._class_percentiles(zone_count, zone_index)
            legend.append(
                {
                    "class_id": zone_index,
                    "label": self._neutral_zone_label(zone_index, zone_count),
                    "ndvi_min": float(breaks[zone_index - 1]),
                    "ndvi_max": float(breaks[zone_index]),
                    "percentile_min": percentile_min,
                    "percentile_max": percentile_max,
                    "mean": float(np.mean(zone_values))
                    if zone_values.size
                    else float((breaks[zone_index - 1] + breaks[zone_index]) / 2),
                    "color": "#" + "".join(f"{channel:02x}" for channel in color),
                    "cell_count": int(np.count_nonzero(zone_mask)),
                    "area_hectares": float(np.count_nonzero(zone_mask) * cell_size_m**2 / 10_000),
                }
            )
        return {
            "zone_count": zone_count,
            "cell_size_m": cell_size_m,
            "bounds": [[south, west], [north, east]],
            "valid_cell_count": int(np.count_nonzero(class_valid)),
            "area_hectares": float(np.count_nonzero(class_valid) * cell_size_m**2 / 10_000),
            "legend": legend,
            "zones": zones,
            "colors": colors,
        }

    def ndvi_zoning_map(
        self,
        geom: Any,
        zone_count: int = 4,
        cell_size_m: float = 3.0,
    ) -> dict[str, Any]:
        data = self._prepare_ndvi_classification(geom, zone_count, cell_size_m)
        rgba = np.zeros((data["zones"].shape[0], data["zones"].shape[1], 4), dtype=np.uint8)
        for zone_index, color in enumerate(data["colors"], 1):
            zone_mask = data["zones"] == zone_index
            rgba[zone_mask, :3] = color
            rgba[zone_mask, 3] = 255
        render_scale = 12
        rendered = np.repeat(np.repeat(rgba, render_scale, axis=0), render_scale, axis=1)
        for grid_edge in (rendered[::render_scale, :, :], rendered[:, ::render_scale, :]):
            visible_edge = grid_edge[..., 3] > 0
            grid_edge[visible_edge, :3] = (75, 81, 77)
            grid_edge[visible_edge, 3] = 255
        zoning_id = uuid4().hex
        zoning_dir = self.settings.output_dir / "prescriptions"
        zoning_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rendered, mode="RGBA").save(zoning_dir / f"{zoning_id}.png")
        return {
            "status": "ok",
            "stage": "zoning",
            "title": "Zonificacion NDVI",
            "zoning_id": zoning_id,
            "image_url": f"/static/prescriptions/{zoning_id}.png",
            "bounds": data["bounds"],
            "zone_count": data["zone_count"],
            "cell_size_m": data["cell_size_m"],
            "valid_cell_count": data["valid_cell_count"],
            "area_hectares": data["area_hectares"],
            "legend": data["legend"],
        }

    def _dose_mapping(self, zone_count: int, doses: list[dict[str, Any]]) -> dict[int, float]:
        if len(doses) != zone_count:
            raise ValueError(
                f"Debes asignar una dosis a cada una de las {zone_count} clases.",
            )
        mapping: dict[int, float] = {}
        seen: set[int] = set()
        for item in doses:
            if not isinstance(item, dict):
                raise ValueError("Cada dosis debe enviarse como un objeto JSON.")
            try:
                class_id = int(item.get("class_id"))
                dose = float(item.get("dose"))
            except (TypeError, ValueError) as exc:
                raise ValueError("Las dosis deben ser numericas.") from exc
            if not 1 <= class_id <= zone_count:
                raise ValueError("El identificador de clase no es valido.")
            if class_id in seen:
                raise ValueError("No puedes repetir la misma clase.")
            if dose < 0:
                raise ValueError("La dosis no puede ser negativa.")
            mapping[class_id] = dose
            seen.add(class_id)
        if len(mapping) != zone_count:
            raise ValueError("Faltan dosis para una o mas clases.")
        return mapping

    def prescription_map_with_doses(
        self,
        geom: Any,
        zone_count: int = 4,
        cell_size_m: float = 3.0,
        doses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not doses:
            raise ValueError("Primero genera la zonificacion y asigna una dosis a cada clase.")
        data = self._prepare_ndvi_classification(geom, zone_count, cell_size_m)
        dose_mapping = self._dose_mapping(zone_count, doses)
        class_doses = {class_id: dose_mapping[class_id] for class_id in range(1, zone_count + 1)}
        unique_doses = sorted(set(class_doses.values()))
        dose_colors = self._dose_ramp(len(unique_doses))
        dose_color_map = {dose: dose_colors[index] for index, dose in enumerate(unique_doses)}
        rgba = np.zeros((data["zones"].shape[0], data["zones"].shape[1], 4), dtype=np.uint8)
        for class_id in range(1, zone_count + 1):
            zone_mask = data["zones"] == class_id
            color = dose_color_map[class_doses[class_id]]
            rgba[zone_mask, :3] = color
            rgba[zone_mask, 3] = 255
        render_scale = 12
        rendered = np.repeat(np.repeat(rgba, render_scale, axis=0), render_scale, axis=1)
        for grid_edge in (rendered[::render_scale, :, :], rendered[:, ::render_scale, :]):
            visible_edge = grid_edge[..., 3] > 0
            grid_edge[visible_edge, :3] = (75, 81, 77)
            grid_edge[visible_edge, 3] = 255
        prescription_id = uuid4().hex
        prescription_dir = self.settings.output_dir / "prescriptions"
        prescription_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rendered, mode="RGBA").save(prescription_dir / f"{prescription_id}.png")
        legend = []
        for zone in data["legend"]:
            class_id = int(zone["class_id"])
            dose = class_doses[class_id]
            legend.append(
                {
                    **zone,
                    "dose": dose,
                    "dose_color": "#" + "".join(f"{channel:02x}" for channel in dose_color_map[dose]),
                }
            )
        return {
            "status": "ok",
            "stage": "prescription",
            "title": "Mapa de Prescripcion",
            "prescription_id": prescription_id,
            "image_url": f"/static/prescriptions/{prescription_id}.png",
            "bounds": data["bounds"],
            "zone_count": zone_count,
            "cell_size_m": cell_size_m,
            "valid_cell_count": data["valid_cell_count"],
            "area_hectares": data["area_hectares"],
            "legend": legend,
        }

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
        ramp = np.asarray(
            [
                [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                for color in self.INDEX_RAMPS["NDVI"]
            ],
            dtype=np.uint8,
        )
        if zone_count == len(self.PRESCRIPTION_ZONE_PALETTE):
            colors = np.asarray(
                [
                    [int(color[index : index + 2], 16) for index in (0, 2, 4)]
                    for color in self.PRESCRIPTION_ZONE_PALETTE
                ],
                dtype=np.uint8,
            )
        else:
            ramp_positions = np.floor(
                np.linspace(0, len(ramp) - 1, zone_count) + 0.5,
            ).astype(int)
            colors = ramp[ramp_positions]
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        for zone_index, color in enumerate(colors, 1):
            zone_mask = zones == zone_index
            rgba[zone_mask, :3] = color
            rgba[zone_mask, 3] = 255

        # Cada celda métrica se amplía únicamente para visualización. Un borde
        # carbón de un píxel marca el límite compartido sin introducir huecos
        # y ocupa una proporción pequeña frente al relleno NDVI.
        render_scale = 12
        rendered = np.repeat(
            np.repeat(rgba, render_scale, axis=0),
            render_scale,
            axis=1,
        )
        for grid_edge in (
            rendered[::render_scale, :, :],
            rendered[:, ::render_scale, :],
        ):
            visible_edge = grid_edge[..., 3] > 0
            grid_edge[visible_edge, :3] = (75, 81, 77)
            grid_edge[visible_edge, 3] = 255

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
                return (3, 5) if src.count >= 5 else (2, 4)
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

    def _rgb_bands(self) -> tuple[int, int, int]:
        """Return raster bands in display order: Red, Green, Blue."""
        if self.sensor == "micasense":
            return 4, 2, 1
        return 1, 2, 3

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
    def _colorize_index(
        cls,
        name: str,
        values: np.ndarray,
        valid: np.ndarray,
        low: float | None = None,
        high: float | None = None,
    ) -> np.ndarray:
        colors = np.array(
            [[int(color[i:i + 2], 16) for i in (0, 2, 4)] for color in cls.INDEX_RAMPS[name]],
            dtype=np.uint8,
        )
        minimum, maximum = cls.INDEX_DOMAINS[name]
        position = np.clip(
            ((values - minimum) / (maximum - minimum) * (len(colors) - 1)).round().astype(np.int16),
            0,
            len(colors) - 1,
        )
        visible = valid & np.isfinite(values)
        if low is not None or high is not None:
            range_low = -np.inf if low is None else low
            range_high = np.inf if high is None else high
            range_low, range_high = sorted((range_low, range_high))
            visible &= (values >= range_low) & (values <= range_high)
        return np.dstack((colors[position], np.where(visible, 255, 0).astype(np.uint8)))

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
                rgb = np.stack([src.read(index, out_shape=(source_height, source_width), resampling=Resampling.average) for index in self._rgb_bands()]).astype(np.float32)
                red, green, blue = self.stretch_rgb(*rgb)
                mask = np.any(rgb > 0, axis=0)
                if src.crs and src.crs.to_string() != "EPSG:4326":
                    transform, width, height = calculate_default_transform(src.crs, "EPSG:4326", width, height, *src.bounds)
                    projected = []
                    for band in (red, green, blue):
                        destination = np.zeros((height, width), dtype=np.uint8)
                        reproject(band, destination, src_transform=source_transform, src_crs=src.crs, dst_transform=transform, dst_crs="EPSG:4326", resampling=Resampling.bilinear)
                        projected.append(destination)
                    red, green, blue = projected
                    mask = np.any(np.stack(projected) > 0, axis=0)
                bounds = array_bounds(height, width, transform if src.crs and src.crs.to_string() != "EPSG:4326" else src.transform * Affine.scale(src.width / width, src.height / height))
                response: dict[str, Any] = {
                    "status": "ok",
                    "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
                    "rgb_matrix": np.moveaxis(np.stack((red, green, blue)), 0, -1).tolist(),
                    "mask": mask.astype(np.uint8).tolist(),
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
        if self.overlay and self.rgb_stretch:
            return self.overlay
        with rasterio.open(self._path()) as src:
            scale = self.scale(src, self.settings.rgb_max_pixels)
            height, width = max(1, src.height // scale), max(1, src.width // scale)
            bands = np.stack([src.read(i, out_shape=(height, width), resampling=Resampling.average) for i in self._rgb_bands()]).astype(np.float32)
            valid = np.any(bands > 0, axis=0)
            self.rgb_stretch = tuple(np.percentile(bands[:, valid].reshape(-1), [2, 98])) if np.any(valid) else (0, 1)
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

    def tile(self, kind: str, z: int, x: int, y: int, low: float = -0.05, high: float = 1.0) -> bytes:
        with rasterio.open(self._path()) as src:
            bounds = self.tile_bounds(z, x, y)
            if src.crs and src.crs.to_string() != "EPSG:4326":
                bounds = transform_bounds("EPSG:4326", src.crs, *bounds, densify_pts=21)
            window = from_bounds(*bounds, transform=src.transform)
            size, resampling = (512, Resampling.bilinear) if kind == "rgb" else (512, Resampling.nearest)
            if window.width <= 0 or window.height <= 0:
                rgba = np.zeros((size, size, 4), dtype=np.uint8)
            elif kind == "rgb":
                rgb = [src.read(i, window=window, out_shape=(size, size), resampling=resampling, boundless=True, fill_value=0) for i in self._rgb_bands()]
                r, g, b = self.stretch_rgb(*rgb, self.rgb_stretch)
                rgba = np.dstack((r, g, b, np.where((r == 0) & (g == 0) & (b == 0), 0, 255).astype(np.uint8)))
            else:
                positive_band, negative_band = self._index_bands("NDVI")
                positive, negative = [src.read(i, window=window, out_shape=(size, size), resampling=resampling, boundless=True, fill_value=0).astype(np.float32) for i in (positive_band, negative_band)]
                ndvi, valid = self._calculate_index(positive, negative)
                rgba = self._colorize_index("NDVI", ndvi, valid, low, high)
            output = io.BytesIO()
            Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
            return output.getvalue()

    def begin_crop_tiles(self, geom: Any) -> dict[str, Any]:
        """Registra una ROI para enmascarar tiles RGB sin remuestrear el raster."""
        crop_id = uuid4().hex
        self.crop_geometries[crop_id] = geom
        minx, miny, maxx, maxy = geom.bounds
        return {"crop_id": crop_id, "bounds": [[miny, minx], [maxy, maxx]]}

    def crop_tile(self, crop_id: str, z: int, x: int, y: int) -> bytes:
        geom = self.crop_geometries.get(crop_id)
        if geom is None:
            raise ValueError("El recorte ya no está disponible. Selecciona el ROI nuevamente.")
        with rasterio.open(self._path()) as src:
            bounds = self.tile_bounds(z, x, y)
            source_geom = geom
            if src.crs and src.crs.to_string() != "EPSG:4326":
                bounds = transform_bounds("EPSG:4326", src.crs, *bounds, densify_pts=21)
                source_geom = project_geometry(pyproj.Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform, geom)
            window = from_bounds(*bounds, transform=src.transform)
            size = 512
            if window.width <= 0 or window.height <= 0:
                rgba = np.zeros((size, size, 4), dtype=np.uint8)
            else:
                rgb = [src.read(i, window=window, out_shape=(size, size), resampling=Resampling.bilinear, boundless=True, fill_value=0) for i in self._rgb_bands()]
                r, g, b = self.stretch_rgb(*rgb, self.rgb_stretch)
                transform = window_transform(window, src.transform) * Affine.scale(window.width / size, window.height / size)
                mask = geometry_mask([mapping(source_geom)], out_shape=(size, size), transform=transform, invert=True)
                rgba = np.dstack((r, g, b, np.where(mask, 255, 0).astype(np.uint8)))
            output = io.BytesIO()
            Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
            return output.getvalue()

    def crop_index_tile(self, name: str, crop_id: str, z: int, x: int, y: int, low: float | None = None, high: float | None = None) -> bytes:
        geom = self.crop_geometries.get(crop_id)
        if geom is None:
            raise ValueError("El recorte ya no está disponible. Selecciona el ROI nuevamente.")
        bands = self._index_bands(name)
        if not bands:
            raise ValueError("El índice requiere un ortomosaico multiespectral compatible.")
        with rasterio.open(self._path()) as src:
            bounds = self.tile_bounds(z, x, y)
            source_geom = geom
            if src.crs and src.crs.to_string() != "EPSG:4326":
                bounds = transform_bounds("EPSG:4326", src.crs, *bounds, densify_pts=21)
                source_geom = project_geometry(pyproj.Transformer.from_crs("EPSG:4326", src.crs, always_xy=True).transform, geom)
            window = from_bounds(*bounds, transform=src.transform)
            size = 512
            positive, negative = [src.read(i, window=window, out_shape=(size, size), resampling=Resampling.nearest, boundless=True, fill_value=0).astype(np.float32) for i in bands]
            transform = window_transform(window, src.transform) * Affine.scale(window.width / size, window.height / size)
            mask = geometry_mask([mapping(source_geom)], out_shape=(size, size), transform=transform, invert=True)
            values, valid = self._calculate_index(positive, negative)
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
    ) -> bytes:
        bands = self._index_bands(name)
        if not bands:
            raise ValueError("El índice requiere un ortomosaico multiespectral compatible.")
        with rasterio.open(self._path()) as src:
            bounds = self.tile_bounds(z, x, y)
            if src.crs and src.crs.to_string() != "EPSG:4326": bounds = transform_bounds("EPSG:4326", src.crs, *bounds, densify_pts=21)
            window = from_bounds(*bounds, transform=src.transform)
            positive, negative = [src.read(i, window=window, out_shape=(512, 512), resampling=Resampling.nearest, boundless=True, fill_value=0).astype(np.float32) for i in bands]
            values, valid = self._calculate_index(positive, negative)
            rgba = self._colorize_index(name, values, valid, low, high)
            output = io.BytesIO(); Image.fromarray(rgba, mode="RGBA").save(output, format="PNG")
            return output.getvalue()

    def geometry_window(self, geom: Any, bands: list[int]) -> tuple[np.ndarray, Affine, np.ndarray, dict[str, Any]] | None:
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
            data = src.read(bands, window=window, out_shape=(len(bands), height, width), resampling=Resampling.average)
            transform = window_transform(window, src.transform) * Affine.scale(window.width / width, window.height / height)
            mask = geometry_mask([mapping(geom)], out_shape=(height, width), transform=transform, invert=True)
            source_bounds = array_bounds(height, width, transform)
            response_bounds = transform_bounds(src.crs, "EPSG:4326", *source_bounds) if src.crs and src.crs.to_string() != "EPSG:4326" else source_bounds
            return data, transform, mask, {"col_off": window.col_off, "row_off": window.row_off, "scale": scale, "src_width": src.width, "src_height": src.height, "response_bounds": response_bounds}

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
            red = src.read(red_band, out_shape=(coarse_height, coarse_width), resampling=Resampling.average).astype(np.float32)
            nir = src.read(nir_band, out_shape=(coarse_height, coarse_width), resampling=Resampling.average).astype(np.float32)
            if src.crs and src.crs.to_string() != "EPSG:4326":
                red_wgs84 = np.zeros((height, width), dtype=np.float32)
                nir_wgs84 = np.zeros((height, width), dtype=np.float32)
                for source, destination in ((red, red_wgs84), (nir, nir_wgs84)):
                    reproject(source=source, destination=destination, src_transform=source_transform, src_crs=src.crs, dst_transform=overlay_transform, dst_crs="EPSG:4326", resampling=Resampling.average)
                red, nir = red_wgs84, nir_wgs84
            ndvi = (nir - red) / (nir + red + 1e-6)
            bounds = array_bounds(height, width, overlay_transform)
            return {"status": "ok", "ndvi_matrix": (np.clip((ndvi + 1) / 2, 0, 1) * 255).astype(np.uint8).tolist(), "ndvi_mask": ((red > 0) & (nir > 0)).astype(np.uint8).tolist(), "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]}

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
            first = src.read(bands[first_name], out_shape=(coarse_height, coarse_width), resampling=Resampling.average).astype(np.float32)
            second = src.read(bands[second_name], out_shape=(coarse_height, coarse_width), resampling=Resampling.average).astype(np.float32)
            if src.crs and src.crs.to_string() != "EPSG:4326":
                projected = []
                for source in (first, second):
                    destination = np.zeros((height, width), dtype=np.float32)
                    reproject(source=source, destination=destination, src_transform=source_transform, src_crs=src.crs, dst_transform=overlay_transform, dst_crs="EPSG:4326", resampling=Resampling.average)
                    projected.append(destination)
                first, second = projected
            values = (first - second) / (first + second + 1e-6)
            bounds = array_bounds(height, width, overlay_transform)
            return {"status": "ok", "matrix": values.tolist(), "mask": ((first > 0) & (second > 0)).astype(np.uint8).tolist(), "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]}

    def roi_ndvi(self, geom: Any) -> dict[str, Any]:
        result = self.geometry_window(geom, list(self._ndvi_bands()))
        if result is None: raise ValueError("El ROI no intersecta el raster.")
        data, transform, mask, meta = result
        red, nir = data.astype(np.float32)
        ndvi = (nir - red) / (nir + red + 1e-6)
        return {"status": "ok", "ndvi_matrix": (np.clip((ndvi + 1) / 2, 0, 1) * 255).astype(np.uint8).tolist(), "ndvi_mask": ((red > 0) & (nir > 0) & mask).astype(np.uint8).tolist(), **self._bounds_response(transform, data.shape[1], data.shape[2], meta)}

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
        result = self.geometry_window(geom, list(bands))
        if result is None:
            raise ValueError("El ROI no intersecta el raster.")
        data, transform, mask, meta = result
        first, second = data.astype(np.float32)
        values = (first - second) / (first + second + 1e-6)
        return {"status": "ok", "matrix": values.tolist(), "mask": ((first > 0) & (second > 0) & mask).astype(np.uint8).tolist(), **self._bounds_response(transform, data.shape[1], data.shape[2], meta)}

    @staticmethod
    def _bounds_response(transform: Affine, height: int, width: int, meta: dict[str, Any]) -> dict[str, Any]:
        minx, miny, maxx, maxy = meta.get("response_bounds", array_bounds(height, width, transform))
        return {"bounds": [[miny, minx], [maxy, maxx]], "offset_x": round(meta["col_off"] / meta["scale"]), "offset_y": round(meta["row_off"] / meta["scale"]), "base_width": max(1, round(meta["src_width"] / meta["scale"])), "base_height": max(1, round(meta["src_height"] / meta["scale"]))}
