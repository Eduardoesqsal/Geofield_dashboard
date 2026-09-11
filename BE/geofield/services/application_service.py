"""Servicios de aplicacion para ortomosaicos y ROI.

Coordinan validaciones, flujos de persistencia y operaciones de alto nivel
entre las rutas HTTP y la infraestructura concreta. La logica de negocio nueva
debe vivir en `geofield.application.use_cases`; estas clases quedan como
fachadas compatibles para las rutas existentes.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from geofield.application.use_cases import (
    ActivateOrthomosaicUseCase,
    DeleteAgriculturalCycleUseCase,
    DeleteOrthomosaicUseCase,
    ResetActiveOrthomosaicUseCase,
    SaveRoiAnalysisUseCase,
    normalize_roi_analysis_stats,
    roi_stats_match,
)
from geofield.services.raster_service import RasterService
from geofield.services.supabase_service import SupabaseService


class OrthomosaicApplicationService:
    """Coordina flujos de ortomosaicos sin conocer HTTP."""

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
        # registro. Un TIFF puede tener encabezado valido y datos truncados.
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
            # El registro recien insertado ya contiene todo lo necesario para
            # activar el archivo. Evita una segunda lectura susceptible a una
            # conexion HTTP persistente rota despues de reiniciar el backend.
            self.supabase.activate_orthomosaic_record(record, self.raster)
        analysis = self.raster.analyze_uploaded(
            content,
            self._kind_from_sensor(sensor_type),
            filename,
            sensor_type,
        )
        return {"orthomosaic": record, "analysis": analysis}

    def activate_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        return ActivateOrthomosaicUseCase(self.raster, self.supabase).execute(
            orthomosaic_id,
        )

    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        return DeleteOrthomosaicUseCase(self.raster, self.supabase).execute(
            orthomosaic_id,
        )

    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        return DeleteAgriculturalCycleUseCase(self.raster, self.supabase).execute(
            cycle_id,
        )

    def update_orthomosaic_capture_date(
        self,
        orthomosaic_id: str,
        capture_date: date,
    ) -> dict[str, Any]:
        return self.supabase.update_orthomosaic_capture_date(
            orthomosaic_id,
            capture_date,
        )

    def create_agricultural_cycle(
        self,
        *,
        name: str,
        crop_name: str | None,
        start_date: date,
        end_date: date | None,
        notes: str | None,
    ) -> dict[str, Any]:
        return self.supabase.create_agricultural_cycle(
            name=name,
            crop_name=crop_name,
            start_date=start_date,
            end_date=end_date,
            notes=notes,
        )

    def update_agricultural_cycle(self, cycle_id: str, *, name: str) -> dict[str, Any]:
        return self.supabase.update_agricultural_cycle(cycle_id, name=name)

    def reorder_orthomosaics(
        self,
        cycle_id: str,
        orthomosaic_ids: list[str],
    ) -> list[dict[str, Any]]:
        return self.supabase.reorder_orthomosaics(cycle_id, orthomosaic_ids)

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

    def set_roi_active(self, roi_id: str, active: bool) -> dict[str, Any]:
        return self.supabase.set_roi_active(roi_id, active)

    def reset_active_orthomosaic(self, record: dict[str, Any]) -> None:
        ResetActiveOrthomosaicUseCase(self.raster, self.supabase).execute(record)


class RoiApplicationService:
    """Fachada de aplicacion para ROI y estadisticas."""

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
        return SaveRoiAnalysisUseCase(self.raster, self.supabase).execute(
            roi_id=roi_id,
            orthomosaic_id=orthomosaic_id,
            geometry=geometry,
            selected_index=selected_index,
            selected_stats=selected_stats,
        )

    def save_roi_analysis_for_roi(
        self,
        *,
        roi_id: str,
        orthomosaic_id: str,
        geometry: Any,
        selected_index: str | None = None,
        selected_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = self.save_roi_analysis(
            roi_id=roi_id,
            orthomosaic_id=orthomosaic_id,
            geometry=geometry,
            selected_index=selected_index,
            selected_stats=selected_stats,
        )
        if selected_index and selected_stats:
            persisted_stats = record.get(selected_index.lower())
            normalized_stats = self.normalize_roi_analysis_stats(selected_stats)
            if not self.stats_match(persisted_stats, normalized_stats):
                raise ValueError(
                    f"Se guardo un registro distinto al resumen numerico actual de {selected_index}. "
                    "La base de datos devolvio estadisticas diferentes a las enviadas desde el histograma.",
                )
        return record

    def save_global_analysis(self, *, orthomosaic_id: str) -> dict[str, Any]:
        return self.supabase.save_global_analysis(orthomosaic_id=orthomosaic_id)

    @staticmethod
    def normalize_roi_analysis_stats(stats: dict[str, Any]) -> dict[str, Any]:
        return normalize_roi_analysis_stats(stats)

    @classmethod
    def stats_match(
        cls,
        persisted: dict[str, Any] | None,
        expected: dict[str, Any] | None,
    ) -> bool:
        return roi_stats_match(persisted, expected)

    def _stats(self, name: str, geometry: Any) -> dict[str, Any]:
        return SaveRoiAnalysisUseCase(self.raster, self.supabase).analyze_roi.execute(
            name,
            geometry,
        )
