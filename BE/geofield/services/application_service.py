"""Servicios de aplicación para ortomosaicos y ROI.

Coordinan validaciones, flujos de persistencia y operaciones de alto nivel
entre las rutas HTTP y la infraestructura concreta.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from geofield.services.raster_service import RasterService
from geofield.services.supabase_service import SupabaseService


class OrthomosaicApplicationService:
    """Coordina flujos de negocio sin conocer HTTP."""

    def __init__(self, raster: RasterService, supabase: SupabaseService) -> None:
        self.raster = raster
        self.supabase = supabase

    @staticmethod
    def _kind_from_sensor(sensor_type: str) -> str:
        return "multispectral" if sensor_type in {"mavic3m", "micasense"} else "rgb"

    def upload_orthomosaic(
        self,
        *,
        content: bytes,
        filename: str,
        agricultural_cycle_id: str,
        capture_date: date,
        sensor_type: str,
        name: str | None,
        content_type: str | None,
        activate: bool,
    ) -> dict[str, Any]:
        # Validar los tiles internos antes de escribir el archivo o crear su
        # registro. Un TIFF puede tener encabezado válido y datos truncados.
        self.raster.validate_uploaded(content)
        record = self.supabase.upload_orthomosaic(
            content=content,
            filename=filename,
            agricultural_cycle_id=agricultural_cycle_id,
            capture_date=capture_date,
            sensor_type=sensor_type,
            name=name,
            content_type=content_type,
        )
        if activate:
            # El registro recién insertado ya contiene todo lo necesario para
            # activar el archivo. Evita una segunda lectura susceptible a una
            # conexión HTTP persistente rota después de reiniciar el backend.
            self.supabase.activate_orthomosaic_record(record, self.raster)
        analysis = self.raster.analyze_uploaded(
            content,
            self._kind_from_sensor(sensor_type),
            filename,
            sensor_type,
        )
        return {"orthomosaic": record, "analysis": analysis}

    def activate_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        return self.supabase.activate_orthomosaic(orthomosaic_id, self.raster)

    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        record = self.supabase.get_orthomosaic(orthomosaic_id)
        self.reset_active_orthomosaic(record)
        self.supabase.delete_orthomosaic(orthomosaic_id)
        return record

    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        for record in self.supabase.list_orthomosaics(500, cycle_id):
            self.reset_active_orthomosaic(record)
        return self.supabase.delete_agricultural_cycle(cycle_id)

    def update_orthomosaic_capture_date(
        self,
        orthomosaic_id: str,
        capture_date: date,
    ) -> dict[str, Any]:
        return self.supabase.update_orthomosaic_capture_date(
            orthomosaic_id,
            capture_date,
        )

    def reset_active_orthomosaic(self, record: dict[str, Any]) -> None:
        active_path = self.raster.active_path.resolve() if self.raster.active_path else None
        if not active_path:
            return
        file_path = record.get("file_path")
        if not file_path:
            return
        candidate_paths = {Path(str(file_path)).resolve()}
        original_filename = record.get("original_filename") or file_path
        suffix = Path(str(original_filename)).suffix or ".tif"
        candidate_paths.add((self.supabase.settings.cache_dir / f'{record["id"]}{suffix}').resolve())
        if active_path not in candidate_paths:
            return
        self.raster.active_path = None
        self.raster.sensor = None
        self.raster.rgb_stretch = None
        self.raster.overlay = None
        self.raster.crop_geometries.clear()


class RoiApplicationService:
    """Encapsula cÃ¡lculos y persistencia de ROI."""

    def __init__(self, raster: RasterService, supabase: SupabaseService) -> None:
        self.raster = raster
        self.supabase = supabase

    def create_roi(
        self,
        *,
        name: str,
        geojson: dict[str, Any],
        orthomosaic_id: str | None,
        agricultural_cycle_id: str | None,
    ) -> dict[str, Any]:
        return self.supabase.create_roi(
            name,
            geojson,
            orthomosaic_id,
            agricultural_cycle_id,
        )

    def save_roi_analysis(
        self,
        *,
        roi_id: str,
        orthomosaic_id: str,
        geometry: Any,
        selected_index: str | None = None,
        selected_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if selected_index and selected_stats:
            return self.supabase.save_roi_analysis(
                roi_id,
                orthomosaic_id,
                selected_index,
                self.normalize_roi_analysis_stats(selected_stats),
            )

        if not selected_index:
            raise ValueError("Selecciona un indice antes de guardar estadisticas.")

        return self.supabase.save_roi_analysis(
            roi_id,
            orthomosaic_id,
            selected_index,
            self._stats(selected_index, geometry),
        )

    @staticmethod
    def normalize_roi_analysis_stats(stats: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(stats, dict):
            raise ValueError("Las estadisticas del ROI deben enviarse como objeto.")

        def numeric(name: str) -> float | None:
            value = stats.get(name)
            if value is None:
                return None
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"El campo {name} no contiene un numero valido.") from exc
            if not np.isfinite(number):
                raise ValueError(f"El campo {name} debe ser un numero finito.")
            return number

        count = stats.get("count")
        try:
            normalized_count = int(count)
        except (TypeError, ValueError) as exc:
            raise ValueError("El campo count debe ser un entero valido.") from exc
        if normalized_count < 0:
            raise ValueError("El campo count no puede ser negativo.")

        return {
            "count": normalized_count,
            "min": numeric("min"),
            "max": numeric("max"),
            "mean": numeric("mean"),
            "median": numeric("median"),
            "standard_deviation": numeric("standard_deviation"),
            "p10": numeric("p10"),
            "p25": numeric("p25"),
            "p75": numeric("p75"),
            "p90": numeric("p90"),
            "range_min": numeric("range_min"),
            "range_max": numeric("range_max"),
        }

    @classmethod
    def stats_match(
        cls,
        persisted: dict[str, Any] | None,
        expected: dict[str, Any] | None,
    ) -> bool:
        if persisted is None or expected is None:
            return persisted is expected

        normalized_persisted = cls.normalize_roi_analysis_stats(persisted)
        normalized_expected = cls.normalize_roi_analysis_stats(expected)
        return normalized_persisted == normalized_expected

    def _stats(self, name: str, geometry: Any) -> dict[str, Any]:
        data = self.raster.roi_vegetation_index(geometry, name)
        matrix = np.asarray(data.get("matrix") or data.get("ndvi_matrix"), dtype=float)
        if name == "NDVI":
            matrix = matrix / 255 * 2 - 1
        mask_data = data.get("mask") or data.get("ndvi_mask")
        if mask_data is None:
            raise ValueError(f"{name} no devolviÃ³ una mÃ¡scara vÃ¡lida.")
        mask = np.asarray(mask_data, dtype=bool)
        values = matrix[mask & np.isfinite(matrix)]
        return {
            "count": int(values.size),
            "min": float(values.min()) if values.size else None,
            "max": float(values.max()) if values.size else None,
            "mean": float(values.mean()) if values.size else None,
            "standard_deviation": float(values.std()) if values.size else None,
        }
