"""Pruebas unitarias del servicio raster y sus cálculos espectrales."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from shapely.geometry import box

from geofield.config import Settings
from geofield.services.raster_service import RasterService


class RasterServiceIndexTileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
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
        np.testing.assert_array_equal(full[256, 256], np.array([85, 187, 0, 255], dtype=np.uint8))

    def test_roi_range_only_changes_visibility_not_color_scale(self) -> None:
        crop = self._rgba(self.service.crop_index_tile("NDVI", self.crop_id, 0, 0, 0, low=0.7, high=1.0))

        np.testing.assert_array_equal(crop[256, 256], np.array([85, 187, 0, 0], dtype=np.uint8))


if __name__ == "__main__":
    unittest.main()
