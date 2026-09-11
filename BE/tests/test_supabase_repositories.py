"""Pruebas de adapters Supabase por repositorio."""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from geofield.infrastructure.repositories import (
    SupabaseOrthomosaicRepository,
    SupabaseRoiAnalysisRepository,
)


class FakeSupabaseService:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def list_orthomosaics(
        self,
        limit: int,
        agricultural_cycle_id: str | None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("list_orthomosaics", limit, agricultural_cycle_id))
        return [{"id": "ortho-1"}]

    def get_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        self.calls.append(("get_orthomosaic", orthomosaic_id))
        return {"id": orthomosaic_id}

    def activate_orthomosaic(
        self,
        orthomosaic_id: str,
        raster: object,
    ) -> dict[str, Any]:
        self.calls.append(("activate_orthomosaic", orthomosaic_id, raster))
        return {"id": orthomosaic_id}

    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        self.calls.append(("delete_orthomosaic", orthomosaic_id))
        return {"id": orthomosaic_id}

    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        self.calls.append(("delete_agricultural_cycle", cycle_id))
        return {"cycle": {"id": cycle_id}}

    def update_orthomosaic_capture_date(
        self,
        orthomosaic_id: str,
        capture_date: date,
    ) -> dict[str, Any]:
        self.calls.append(
            ("update_orthomosaic_capture_date", orthomosaic_id, capture_date),
        )
        return {"id": orthomosaic_id, "capture_date": capture_date.isoformat()}

    def reorder_orthomosaics(
        self,
        agricultural_cycle_id: str,
        orthomosaic_ids: list[str],
    ) -> list[dict[str, Any]]:
        self.calls.append(
            ("reorder_orthomosaics", agricultural_cycle_id, orthomosaic_ids),
        )
        return [{"id": value} for value in orthomosaic_ids]

    def create_roi(
        self,
        name: str,
        geojson: dict[str, Any],
        orthomosaic_id: str | None,
        agricultural_cycle_id: str | None,
    ) -> dict[str, Any]:
        self.calls.append(
            ("create_roi", name, geojson, orthomosaic_id, agricultural_cycle_id),
        )
        return {"id": "roi-1", "name": name}

    def get_roi(self, roi_id: str) -> dict[str, Any]:
        self.calls.append(("get_roi", roi_id))
        return {"id": roi_id}

    def save_roi_analysis(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            ("save_roi_analysis", roi_id, orthomosaic_id, index_type, stats),
        )
        return {"id": "analysis-1"}


class SupabaseRepositoryTests(unittest.TestCase):
    def test_orthomosaic_repository_delegates_to_service(self) -> None:
        service = FakeSupabaseService()
        repository = SupabaseOrthomosaicRepository(service)  # type: ignore[arg-type]
        raster = object()

        self.assertEqual(repository.list_orthomosaics(10, "cycle-1"), [{"id": "ortho-1"}])
        self.assertEqual(repository.activate_orthomosaic("ortho-1", raster), {"id": "ortho-1"})

        self.assertEqual(
            service.calls,
            [
                ("list_orthomosaics", 10, "cycle-1"),
                ("activate_orthomosaic", "ortho-1", raster),
            ],
        )

    def test_roi_repository_delegates_to_service(self) -> None:
        service = FakeSupabaseService()
        repository = SupabaseRoiAnalysisRepository(service)  # type: ignore[arg-type]

        self.assertEqual(
            repository.create_roi("Lote", {"type": "Feature"}, "ortho-1", "cycle-1"),
            {"id": "roi-1", "name": "Lote"},
        )
        self.assertEqual(
            repository.save_roi_analysis("roi-1", "ortho-1", "NDVI", {"count": 1}),
            {"id": "analysis-1"},
        )

        self.assertEqual(
            service.calls,
            [
                ("create_roi", "Lote", {"type": "Feature"}, "ortho-1", "cycle-1"),
                ("save_roi_analysis", "roi-1", "ortho-1", "NDVI", {"count": 1}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
