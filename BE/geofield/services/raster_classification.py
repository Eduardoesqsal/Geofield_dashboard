"""Zonificacion, prescripcion y pipeline de clasificacion raster."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pyproj
import rasterio
from affine import Affine
from PIL import Image
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import array_bounds
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds
from shapely.affinity import rotate as rotate_geometry
from shapely.geometry import Polygon, mapping
from shapely.ops import transform as project_geometry

from geofield.services.raster_classification_artifacts import RasterClassificationArtifactMixin
from geofield.services.raster_classification_filters import RasterClassificationFilterMixin
from geofield.services.raster_classification_helpers import RasterClassificationHelperMixin
from geofield.services import raster_processing


logger = logging.getLogger(__name__)


class RasterClassificationMixin(
    RasterClassificationArtifactMixin,
    RasterClassificationHelperMixin,
    RasterClassificationFilterMixin,
):
    """Zonificacion, prescripcion y artefactos derivados de clasificacion."""

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
            grid_footprint = Polygon(
                [
                    destination_transform * (0, 0),
                    destination_transform * (width, 0),
                    destination_transform * (width, height),
                    destination_transform * (0, height),
                ]
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
                *grid_footprint.bounds,
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
            index_values, valid_fraction, sample_stats = raster_processing.classification_grid(
                src, sample_window, source_geometry, (first_band, second_band),
                self._calculate_index, destination_transform, metric_crs,
                height, width, cell_value_mode, analysis_min, analysis_max,
                self.settings.cache_dir,
            )
        effective_cell_areas = self._effective_cell_areas(
            metric_geometry,
            height,
            width,
            destination_transform,
            cell_size_m,
        )
        cell_areas_m2 = np.minimum(
            np.clip(valid_fraction, 0.0, 1.0) * np.float32(cell_size_m**2),
            effective_cell_areas,
        ).astype(np.float32)
        roi_mask = effective_cell_areas > 0
        roi_valid = roi_mask & np.isfinite(index_values) & (cell_areas_m2 > 0)
        class_valid = roi_valid.copy()
        values = index_values[class_valid]
        if not values.size:
            raise ValueError(
                f"El ROI no contiene celdas {index_name} validas dentro del filtro de analisis.",
            )
        active_min = float(sample_stats[0]) if analysis_min is None else float(analysis_min)
        active_max = float(sample_stats[1]) if analysis_max is None else float(analysis_max)
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
        spatial_parameters = self._spatial_detail_parameters(
            detail_level,
            class_valid,
            cell_areas_m2,
        )
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
            float(spatial_parameters["minimum_region_area_m2"]),
        )
        debug_after = self._zone_debug_snapshot(
            final_zones,
            class_valid,
            index_values,
            cell_areas_m2,
            zone_count,
            float(spatial_parameters["minimum_region_area_m2"]),
        )
        colors = self._zone_display_palette(index_name, zone_count)
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
            field_mean = float(sample_stats[2])
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
                "spatial_detail": spatial_parameters,
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
