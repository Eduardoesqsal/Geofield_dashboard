"""Pruebas de contrato para rutas FastAPI críticas del backend."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from geofield.api.routes import create_router


class FakeRasterService:
    def __init__(self, active_path: Path) -> None:
        self.active_path: Path | None = active_path
        self.sensor: str | None = "mavic3m"
        self.rgb_stretch: tuple[float, float] | None = (1.0, 2.0)
        self.overlay: tuple[int, int, object] | None = (10, 10, object())
        self.crop_geometries: dict[str, Any] = {"crop-1": object()}


class FakeSupabaseService:
    def __init__(self, record: dict[str, Any], cache_dir: Path) -> None:
        self.record = record
        self.settings = type("Settings", (), {"cache_dir": cache_dir})()

    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        return self.record

    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        return {
            "cycle": {"id": cycle_id, "name": "Ciclo prueba"},
            "orthomosaics": [self.record],
            "deleted_orthomosaics": 1,
            "deleted_rois": 2,
        }


class RoutesDeleteOrthomosaicTests(unittest.TestCase):
    def test_deleting_cycle_resets_its_active_orthomosaic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster_path = root / "active.tif"
            raster_path.write_bytes(b"fake-raster")
            raster = FakeRasterService(raster_path)
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(raster_path)},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).delete("/agricultural_cycles/cycle-1")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["deleted_orthomosaics"], 1)
            self.assertEqual(response.json()["deleted_rois"], 2)
            self.assertIsNone(raster.active_path)

    def test_deleting_active_orthomosaic_resets_raster_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster_path = root / "active.tif"
            raster_path.write_bytes(b"fake-raster")

            raster = FakeRasterService(raster_path)
            supabase = FakeSupabaseService(
                {"id": "ortho-1", "file_path": str(raster_path)},
                root / "cache",
            )
            app = FastAPI()
            app.include_router(create_router(raster, root, root, supabase))  # type: ignore[arg-type]

            response = TestClient(app).delete("/orthomosaics/ortho-1")

            self.assertEqual(response.status_code, 200)
            self.assertIsNone(raster.active_path)
            self.assertIsNone(raster.sensor)
            self.assertIsNone(raster.rgb_stretch)
            self.assertIsNone(raster.overlay)
            self.assertEqual(raster.crop_geometries, {})


if __name__ == "__main__":
    unittest.main()
