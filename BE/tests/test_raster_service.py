"""Pruebas unitarias del servicio raster y sus cálculos espectrales."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pyproj
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.ops import transform as project_geometry

from geofield.config import Settings
from geofield.services.raster_service import RasterService


class RasterServiceIndexTileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.root = root
        raster_path = root / "micasense.tif"
        bands = np.ones((6, 4, 4), dtype=np.float32)
        bands[3] = 2.0  # Red, band 4.
        bands[5] = 8.0  # NIR, band 6. NDVI = 0.6.
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=6,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(0, 4, 1, 1),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"), 1):
                destination.set_band_description(index, description)

        settings = Settings(
            base_dir=root,
            raster_path=raster_path,
            output_dir=root / "static",
            cache_dir=root / "cache",
            uploads_dir=root / "uploads",
        )
        self.service = RasterService(settings)
        self.service.sensor = "micasense"
        self.service.tile_bounds = lambda _z, _x, _y: (0, 0, 4, 4)  # type: ignore[method-assign]
        crop = self.service.begin_crop_tiles(box(0, 0, 4, 4))
        self.crop_id = crop["crop_id"]

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _rgba(content: bytes) -> np.ndarray:
        return np.asarray(Image.open(io.BytesIO(content)).convert("RGBA"))

    def test_full_and_roi_ndvi_use_nir_minus_red_and_identical_colors(self) -> None:
        full = self._rgba(self.service.index_tile("NDVI", 0, 0, 0))
        crop = self._rgba(self.service.crop_index_tile("NDVI", self.crop_id, 0, 0, 0))

        np.testing.assert_array_equal(crop, full)
        np.testing.assert_array_equal(full[256, 256], np.array([39, 232, 51, 255], dtype=np.uint8))

    def test_roi_range_only_changes_visibility_not_color_scale(self) -> None:
        crop = self._rgba(self.service.crop_index_tile("NDVI", self.crop_id, 0, 0, 0, low=0.7, high=1.0))

        np.testing.assert_array_equal(crop[256, 256], np.array([39, 232, 51, 0], dtype=np.uint8))

    def test_truncated_geotiff_is_rejected_before_persistence(self) -> None:
        content = self.service.settings.raster_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "incompleto o dañado"):
            self.service.validate_uploaded(content[: len(content) // 2])

    def test_zoning_and_prescription_use_metric_cells_and_requested_zones(self) -> None:
        raster_path = self.root / "prescription.tif"
        bands = np.ones((6, 9, 9), dtype=np.float32)
        bands[3] = np.linspace(1, 5, 81, dtype=np.float32).reshape(9, 9)
        bands[5] = 8.0
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=9,
            height=9,
            count=6,
            dtype="float32",
            crs="EPSG:32613",
            transform=from_origin(500_000, 2_500_000, 1, 1),
        ) as destination:
            destination.write(bands)

        self.service.active_path = raster_path
        self.service.sensor = "micasense"

        roi = project_geometry(
            pyproj.Transformer.from_crs(
                "EPSG:32613",
                "EPSG:4326",
                always_xy=True,
            ).transform,
            box(500_000, 2_499_991, 500_009, 2_500_000),
        )
        zoning = self.service.ndvi_zoning_map(
            roi,
            zone_count=4,
            cell_size_m=3,
        )
        prescription = self.service.prescription_map_with_doses(
            roi,
            zone_count=4,
            cell_size_m=3,
            doses=[
                {"class_id": 1, "dose": 12},
                {"class_id": 2, "dose": 8},
                {"class_id": 3, "dose": 5},
                {"class_id": 4, "dose": 0},
            ],
        )

        self.assertEqual(zoning["stage"], "zoning")
        self.assertEqual(zoning["zone_count"], 4)
        self.assertEqual(zoning["cell_size_m"], 3)
        self.assertEqual(zoning["valid_cell_count"], 9)
        self.assertEqual(len(zoning["legend"]), 4)
        self.assertEqual(
            [zone["label"] for zone in zoning["legend"]],
            ["NDVI muy bajo", "NDVI bajo", "NDVI medio-alto", "NDVI alto"],
        )
        self.assertEqual(
            [zone["color"] for zone in zoning["legend"]],
            ["#ff7a00", "#ffc400", "#acf404", "#00b824"],
        )
        self.assertEqual(zoning["legend"][0]["percentile_min"], 0.0)
        self.assertEqual(zoning["legend"][-1]["percentile_max"], 100.0)

        self.assertEqual(prescription["stage"], "prescription")
        self.assertEqual(prescription["zone_count"], 4)
        self.assertEqual(prescription["cell_size_m"], 3)
        self.assertEqual(prescription["valid_cell_count"], 9)
        self.assertEqual(len(prescription["legend"]), 4)
        self.assertEqual(
            [zone["dose"] for zone in prescription["legend"]],
            [12.0, 8.0, 5.0, 0.0],
        )
        self.assertEqual(
            [zone["label"] for zone in prescription["legend"]],
            ["NDVI muy bajo", "NDVI bajo", "NDVI medio-alto", "NDVI alto"],
        )

        image_name = Path(prescription["image_url"]).name
        image_path = self.service.settings.output_dir / "prescriptions" / image_name
        self.assertTrue(image_path.is_file())
        rendered = np.asarray(Image.open(image_path).convert("RGBA"))
        visible_alpha = rendered[..., 3][rendered[..., 3] > 0]
        self.assertTrue(np.all(visible_alpha == 255))
        expected_colors = {
            tuple(int(color[index : index + 2], 16) for index in (0, 2, 4))
            for color in self.service.INDEX_RAMPS["NDVI"]
        }
        rendered_colors = {
            tuple(color)
            for color in rendered[..., :3][rendered[..., 3] > 0]
        }
        self.assertIn((75, 81, 77), rendered_colors)
        fill_colors = rendered_colors - {(75, 81, 77)}
        self.assertTrue(fill_colors)
        self.assertTrue(fill_colors.issubset(expected_colors))


if __name__ == "__main__":
    unittest.main()
