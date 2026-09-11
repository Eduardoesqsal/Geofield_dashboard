"""Repositorios Supabase separados por contrato de aplicacion.

Son wrappers del servicio actual para avanzar hacia adapters por dominio sin
reescribir de golpe la integracion existente.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from geofield.services.raster_service import RasterService
from geofield.services.supabase_service import SupabaseService


class SupabaseOrthomosaicRepository:
    def __init__(self, service: SupabaseService) -> None:
        self.service = service

    def list_orthomosaics(
        self,
        limit: int = 100,
        agricultural_cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.service.list_orthomosaics(limit, agricultural_cycle_id)

    def get_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        return self.service.get_orthomosaic(orthomosaic_id)

    def activate_orthomosaic(
        self,
        orthomosaic_id: str,
        raster: RasterService,
    ) -> dict[str, Any]:
        return self.service.activate_orthomosaic(orthomosaic_id, raster)

    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        return self.service.delete_orthomosaic(orthomosaic_id)

    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        return self.service.delete_agricultural_cycle(cycle_id)

    def update_orthomosaic_capture_date(
        self,
        orthomosaic_id: str,
        capture_date: date,
    ) -> dict[str, Any]:
        return self.service.update_orthomosaic_capture_date(
            orthomosaic_id,
            capture_date,
        )

    def reorder_orthomosaics(
        self,
        agricultural_cycle_id: str,
        orthomosaic_ids: list[str],
    ) -> list[dict[str, Any]]:
        return self.service.reorder_orthomosaics(
            agricultural_cycle_id,
            orthomosaic_ids,
        )


class SupabaseRoiAnalysisRepository:
    def __init__(self, service: SupabaseService) -> None:
        self.service = service

    def create_roi(
        self,
        name: str,
        geojson: dict[str, Any],
        orthomosaic_id: str | None,
        agricultural_cycle_id: str | None,
    ) -> dict[str, Any]:
        return self.service.create_roi(
            name,
            geojson,
            orthomosaic_id,
            agricultural_cycle_id,
        )

    def get_roi(self, roi_id: str) -> dict[str, Any]:
        return self.service.get_roi(roi_id)

    def save_roi_analysis(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        return self.service.save_roi_analysis(
            roi_id,
            orthomosaic_id,
            index_type,
            stats,
        )
