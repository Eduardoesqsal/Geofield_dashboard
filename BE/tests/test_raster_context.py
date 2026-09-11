"""Pruebas del contexto explicito de RasterService."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from geofield.config import Settings
from geofield.services.raster_service import RasterContext, RasterService
from geofield.services.supabase_service import SupabaseService


class RasterContextTests(unittest.TestCase):
    def _raster_path(self, root: Path) -> Path:
        path = root / "active.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=3,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(0, 4, 1, 1),
        ) as destination:
            destination.write(np.ones((3, 4, 4), dtype=np.uint8))
        return path

    def _multispectral_path(self, root: Path, name: str) -> Path:
        path = root / name
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=6,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(0, 4, 1, 1),
        ) as destination:
            destination.write(np.ones((6, 4, 4), dtype=np.float32))
            for index, description in enumerate(
                ("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"),
                1,
            ):
                destination.set_band_description(index, description)
        return path

    def test_active_context_drives_active_path_and_sensor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = self._raster_path(root)
            service = RasterService(
                Settings(
                    base_dir=root,
                    raster_path=None,
                    output_dir=root / "static",
                    cache_dir=root / "cache",
                    uploads_dir=root / "uploads",
                ),
            )

            service.set_active_context(
                RasterContext(
                    path=path,
                    sensor="mavic3m",
                    orthomosaic_id="ortho-1",
                ),
            )

            self.assertEqual(service.active_path, path)
            self.assertEqual(service.sensor, "mavic3m")
            self.assertEqual(service.active_context.orthomosaic_id, "ortho-1")

    def test_legacy_active_path_assignment_clears_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = self._raster_path(root)
            second = root / "second.tif"
            second.write_bytes(first.read_bytes())
            service = RasterService(
                Settings(
                    base_dir=root,
                    raster_path=None,
                    output_dir=root / "static",
                    cache_dir=root / "cache",
                    uploads_dir=root / "uploads",
                ),
            )
            service.set_active_context(RasterContext(path=first, sensor="mavic3m", orthomosaic_id="ortho-1"))

            service.active_path = second

            self.assertIsNone(service.active_context)
            self.assertEqual(service.active_path, second)

    def test_supabase_activation_sets_raster_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = self._raster_path(root)
            service = RasterService(
                Settings(
                    base_dir=root,
                    raster_path=None,
                    output_dir=root / "static",
                    cache_dir=root / "cache",
                    uploads_dir=root / "uploads",
                ),
            )
            supabase = object.__new__(SupabaseService)
            supabase.settings = Settings(
                base_dir=root,
                raster_path=None,
                output_dir=root / "static",
                cache_dir=root / "cache",
                uploads_dir=root / "uploads",
                orthomosaic_storage_mode="local",
            )

            supabase.activate_orthomosaic_record(
                {
                    "id": "ortho-1",
                    "file_path": str(path),
                    "sensor_type": "micasense",
                },
                service,
            )

            self.assertIsNotNone(service.active_context)
            self.assertEqual(service.active_context.orthomosaic_id, "ortho-1")
            self.assertEqual(service.active_path, path.resolve())
            self.assertEqual(service.sensor, "micasense")

    def test_path_and_sensor_helpers_can_use_explicit_context_without_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active = self._multispectral_path(root, "active.tif")
            explicit = self._multispectral_path(root, "explicit.tif")
            service = RasterService(
                Settings(
                    base_dir=root,
                    raster_path=None,
                    output_dir=root / "static",
                    cache_dir=root / "cache",
                    uploads_dir=root / "uploads",
                ),
            )
            service.set_active_context(
                RasterContext(path=active, sensor="mavic3m", orthomosaic_id="active"),
            )
            explicit_context = RasterContext(
                path=explicit,
                sensor="micasense",
                orthomosaic_id="explicit",
            )

            self.assertEqual(service._path(explicit_context), explicit)
            self.assertEqual(service._sensor_value(explicit_context), "micasense")
            self.assertEqual(service._ndvi_bands(context=explicit_context), (4, 6))
            self.assertEqual(service._index_bands("NDRE", context=explicit_context), (6, 5))
            self.assertEqual(service.active_path, active)
            self.assertEqual(service.sensor, "mavic3m")

    def test_classification_band_selection_can_use_explicit_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active = self._raster_path(root)
            explicit = self._multispectral_path(root, "explicit.tif")
            service = RasterService(
                Settings(
                    base_dir=root,
                    raster_path=None,
                    output_dir=root / "static",
                    cache_dir=root / "cache",
                    uploads_dir=root / "uploads",
                ),
            )
            service.set_active_context(
                RasterContext(path=active, sensor="rgb", orthomosaic_id="active"),
            )
            explicit_context = RasterContext(
                path=explicit,
                sensor="micasense",
                orthomosaic_id="explicit",
            )

            self.assertEqual(
                service._index_band_pair("NDRE", explicit, explicit_context),
                (6, 5),
            )
            self.assertEqual(service.sensor, "rgb")


    def test_cache_versions_can_be_resolved_from_context_without_changing_active_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            active = self._raster_path(root)
            explicit = root / "explicit.tif"
            explicit.write_bytes(active.read_bytes())
            service = RasterService(
                Settings(
                    base_dir=root,
                    raster_path=None,
                    output_dir=root / "static",
                    cache_dir=root / "cache",
                    uploads_dir=root / "uploads",
                ),
            )
            service.set_active_context(
                RasterContext(path=active, sensor="rgb", orthomosaic_id="active"),
            )
            explicit_context = RasterContext(path=explicit, sensor="rgb", orthomosaic_id="explicit")

            active_version = service.tile_cache_version()
            explicit_version = service.tile_cache_version(context=explicit_context)

            self.assertNotEqual(active_version, explicit_version)
            self.assertEqual(service.active_context.orthomosaic_id, "active")


if __name__ == "__main__":
    unittest.main()
