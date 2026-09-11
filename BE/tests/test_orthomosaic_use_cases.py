"""Pruebas de los casos de uso de ortomosaicos."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from geofield.application.use_cases import (
    ActivateOrthomosaicUseCase,
    DeleteAgriculturalCycleUseCase,
    DeleteOrthomosaicUseCase,
    ResetActiveOrthomosaicUseCase,
)


class FakeRasterState:
    def __init__(self, active_path: Path | None) -> None:
        self.active_path = active_path
        self.sensor: str | None = "mavic3m"
        self.rgb_stretch: tuple[float, float] | None = (1.0, 2.0)
        self.overlay: object | None = object()
        self.crop_geometries: dict[str, Any] = {"crop-1": object()}


class FakeOrthomosaicGateway:
    def __init__(self, record: dict[str, Any], cache_dir: Path) -> None:
        self.record = record
        self.settings = type("Settings", (), {"cache_dir": cache_dir})()
        self.activated: tuple[str, FakeRasterState] | None = None
        self.deleted_orthomosaic_id: str | None = None
        self.deleted_cycle_id: str | None = None

    def activate_orthomosaic(
        self,
        orthomosaic_id: str,
        raster: FakeRasterState,
    ) -> dict[str, Any]:
        self.activated = (orthomosaic_id, raster)
        return self.record

    def get_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        if orthomosaic_id != self.record["id"]:
            raise KeyError(orthomosaic_id)
        return self.record

    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        self.deleted_orthomosaic_id = orthomosaic_id
        return self.record

    def list_orthomosaics(
        self,
        _limit: int = 100,
        _agricultural_cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [self.record]

    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        self.deleted_cycle_id = cycle_id
        return {"cycle": {"id": cycle_id}, "deleted_orthomosaics": 1}


class OrthomosaicUseCaseTests(unittest.TestCase):
    def test_activate_delegates_to_gateway_with_current_raster(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            raster = FakeRasterState(root / "active.tif")
            gateway = FakeOrthomosaicGateway({"id": "ortho-1"}, root / "cache")

            result = ActivateOrthomosaicUseCase(raster, gateway).execute("ortho-1")

            self.assertEqual(result, {"id": "ortho-1"})
            self.assertEqual(gateway.activated, ("ortho-1", raster))

    def test_reset_active_orthomosaic_clears_matching_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active_path = root / "active.tif"
            active_path.write_bytes(b"fake-raster")
            raster = FakeRasterState(active_path)
            gateway = FakeOrthomosaicGateway(
                {"id": "ortho-1", "file_path": str(active_path)},
                root / "cache",
            )

            ResetActiveOrthomosaicUseCase(raster, gateway).execute(gateway.record)

            self.assertIsNone(raster.active_path)
            self.assertIsNone(raster.sensor)
            self.assertIsNone(raster.rgb_stretch)
            self.assertIsNone(raster.overlay)
            self.assertEqual(raster.crop_geometries, {})

    def test_reset_active_orthomosaic_ignores_unrelated_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active_path = root / "active.tif"
            other_path = root / "other.tif"
            active_path.write_bytes(b"fake-raster")
            other_path.write_bytes(b"fake-raster")
            raster = FakeRasterState(active_path)
            gateway = FakeOrthomosaicGateway(
                {"id": "ortho-1", "file_path": str(other_path)},
                root / "cache",
            )

            ResetActiveOrthomosaicUseCase(raster, gateway).execute(gateway.record)

            self.assertEqual(raster.active_path, active_path)
            self.assertEqual(raster.sensor, "mavic3m")
            self.assertEqual(set(raster.crop_geometries), {"crop-1"})

    def test_delete_orthomosaic_returns_record_and_resets_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active_path = root / "active.tif"
            active_path.write_bytes(b"fake-raster")
            raster = FakeRasterState(active_path)
            gateway = FakeOrthomosaicGateway(
                {"id": "ortho-1", "file_path": str(active_path)},
                root / "cache",
            )

            result = DeleteOrthomosaicUseCase(raster, gateway).execute("ortho-1")

            self.assertEqual(result["id"], "ortho-1")
            self.assertEqual(gateway.deleted_orthomosaic_id, "ortho-1")
            self.assertIsNone(raster.active_path)

    def test_delete_cycle_resets_active_orthomosaic_before_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active_path = root / "active.tif"
            active_path.write_bytes(b"fake-raster")
            raster = FakeRasterState(active_path)
            gateway = FakeOrthomosaicGateway(
                {"id": "ortho-1", "file_path": str(active_path)},
                root / "cache",
            )

            result = DeleteAgriculturalCycleUseCase(raster, gateway).execute("cycle-1")

            self.assertEqual(result["deleted_orthomosaics"], 1)
            self.assertEqual(gateway.deleted_cycle_id, "cycle-1")
            self.assertIsNone(raster.active_path)


if __name__ == "__main__":
    unittest.main()

