"""Pruebas unitarias del servicio raster y sus cÃ¡lculos espectrales."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np
import pyproj
import rasterio
from PIL import Image
from rasterio.enums import ColorInterp
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box, shape
from shapely.ops import transform as project_geometry

from geofield.config import Settings
from geofield.services.raster_service import RasterService


class CountingRasterService(RasterService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.profile_calculations = 0

    def _calculate_rgb_profile(
        self,
        src: object,
        bands: tuple[int, int, int],
    ) -> dict[str, object]:
        self.profile_calculations += 1
        return super()._calculate_rgb_profile(src, bands)  # type: ignore[arg-type,return-value]


class TileCachingRasterService(RasterService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.rgb_tile_renders = 0
        self.ndvi_tile_renders = 0

    def _reproject_rgb_tile(
        self,
        src: object,
        z: int,
        x: int,
        y: int,
    ) -> tuple[np.ndarray, np.ndarray, rasterio.Affine]:
        self.rgb_tile_renders += 1
        return super()._reproject_rgb_tile(src, z, x, y)  # type: ignore[arg-type,return-value]

    def _reproject_index_matrix(
        self,
        src: object,
        name: str,
        z: int,
        x: int,
        y: int,
    ) -> tuple[np.ndarray, np.ndarray, rasterio.Affine]:
        self.ndvi_tile_renders += 1
        return super()._reproject_index_matrix(src, name, z, x, y)  # type: ignore[arg-type,return-value]


class RasterServiceRgbTileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _settings(self, raster_path: Path) -> Settings:
        return Settings(
            base_dir=self.root,
            raster_path=raster_path,
            output_dir=self.root / "static",
            cache_dir=self.root / "cache",
            uploads_dir=self.root / "uploads",
        )

    @staticmethod
    def _rgba(content: bytes) -> np.ndarray:
        return np.asarray(Image.open(io.BytesIO(content)).convert("RGBA"))

    @staticmethod
    def _describe_rgb(destination: object) -> None:
        for index, description in enumerate(("Red", "Green", "Blue"), 1):
            destination.set_band_description(index, description)  # type: ignore[attr-defined]

    def test_uint8_rgb_tile_preserves_original_values(self) -> None:
        raster_path = self.root / "rgb-uint8.tif"
        mercator_bounds = RasterService.tile_bounds_mercator(0, 0, 0)
        bands = np.empty((3, 256, 256), dtype=np.uint8)
        bands[0] = 17
        bands[1] = 93
        bands[2] = 241
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=256,
            height=256,
            count=3,
            dtype="uint8",
            crs="EPSG:3857",
            transform=rasterio.transform.from_bounds(*mercator_bounds, 256, 256),
        ) as destination:
            destination.write(bands)
            self._describe_rgb(destination)

        service = RasterService(self._settings(raster_path))
        service.sensor = "rgb"

        rgba = self._rgba(service.tile("rgb", 0, 0, 0))

        self.assertEqual(rgba.shape, (256, 256, 4))
        np.testing.assert_array_equal(rgba[128, 128], [17, 93, 241, 255])
        self.assertEqual(service.rgb_render_profile()["mode"], "original")

    def test_nodata_is_excluded_from_global_percentiles(self) -> None:
        raster_path = self.root / "rgb-uint16-nodata.tif"
        gradient = np.linspace(100, 1000, 400, dtype=np.uint16).reshape(20, 20)
        bands = np.stack((gradient, gradient + 50, gradient + 100))
        bands[:, 0, 0] = 65535
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=20,
            height=20,
            count=3,
            dtype="uint16",
            nodata=65535,
            crs="EPSG:4326",
            transform=from_origin(0, 1, 1 / 20, 1 / 20),
        ) as destination:
            destination.write(bands)
            self._describe_rgb(destination)

        profile = RasterService(self._settings(raster_path)).rgb_render_profile()

        self.assertEqual(profile["mode"], "global-stretch")
        self.assertTrue(all(high < 2000 for _low, high in profile["ranges"]))

    def test_global_profile_is_calculated_once_and_shared_by_tiles(self) -> None:
        raster_path = self.root / "rgb-two-tiles.tif"
        left_bounds = RasterService.tile_bounds_mercator(1, 0, 0)
        right_bounds = RasterService.tile_bounds_mercator(1, 1, 0)
        raster_bounds = (
            left_bounds[0],
            left_bounds[1],
            right_bounds[2],
            left_bounds[3],
        )
        left = np.linspace(100, 200, 256 * 256, dtype=np.uint16).reshape(256, 256)
        right = np.linspace(800, 900, 256 * 256, dtype=np.uint16).reshape(256, 256)
        red = np.hstack((left, right))
        bands = np.stack((red, red + 25, red + 50))
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=512,
            height=256,
            count=3,
            dtype="uint16",
            crs="EPSG:3857",
            transform=rasterio.transform.from_bounds(*raster_bounds, 512, 256),
        ) as destination:
            destination.write(bands)
            self._describe_rgb(destination)

        service = CountingRasterService(self._settings(raster_path))

        left_tile = self._rgba(service.tile("rgb", 1, 0, 0))
        right_tile = self._rgba(service.tile("rgb", 1, 1, 0))

        self.assertEqual(service.profile_calculations, 1)
        self.assertLess(left_tile[..., 0].mean(), right_tile[..., 0].mean())

    def test_adjacent_webmercator_tiles_keep_a_continuous_line_aligned(self) -> None:
        raster_path = self.root / "rgb-adjacent-line.tif"
        left_bounds = RasterService.tile_bounds_mercator(1, 0, 0)
        right_bounds = RasterService.tile_bounds_mercator(1, 1, 0)
        raster_bounds = (
            left_bounds[0],
            left_bounds[1],
            right_bounds[2],
            left_bounds[3],
        )
        bands = np.full((3, 256, 512), 20, dtype=np.uint8)
        bands[:, 119:124, :] = 240
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=512,
            height=256,
            count=3,
            dtype="uint8",
            crs="EPSG:3857",
            transform=rasterio.transform.from_bounds(*raster_bounds, 512, 256),
        ) as destination:
            destination.write(bands)
            self._describe_rgb(destination)

        service = RasterService(self._settings(raster_path))
        left_tile = self._rgba(service.tile("rgb", 1, 0, 0))
        right_tile = self._rgba(service.tile("rgb", 1, 1, 0))

        left_line_rows = np.flatnonzero(left_tile[:, -1, 0] > 200)
        right_line_rows = np.flatnonzero(right_tile[:, 0, 0] > 200)
        np.testing.assert_array_equal(left_line_rows, right_line_rows)
        np.testing.assert_array_equal(left_tile[:, -1], right_tile[:, 0])

    def test_rededge_metadata_does_not_override_scrambled_rgb_bands(self) -> None:
        raster_path = self.root / "rededge-scrambled.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=5,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(0, 2, 1, 1),
        ) as destination:
            destination.write(np.ones((5, 2, 2), dtype=np.float32))
            for index, description in enumerate(
                ("NIR 840nm", "Blue 475nm", "Red Edge 717nm", "Red 668nm", "Green 560nm"),
                1,
            ):
                destination.set_band_description(index, description)

        service = RasterService(self._settings(raster_path))
        service.sensor = "micasense"
        with rasterio.open(raster_path) as source:
            self.assertEqual(service._rgb_bands(source), (4, 5, 2))

    def test_tile_cache_buster_contains_mtime_and_render_version(self) -> None:
        raster_path = self.root / "cache-version.tif"
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=3,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(0, 2, 1, 1),
        ) as destination:
            destination.write(np.ones((3, 2, 2), dtype=np.uint8))

        service = RasterService(self._settings(raster_path))
        version = service.tile_cache_version()

        self.assertIn(str(raster_path.stat().st_mtime_ns), version)
        self.assertTrue(version.endswith(service.RGB_RENDER_VERSION))

    def test_tile_cache_path_compacts_long_windows_unsafe_components(self) -> None:
        raster_path = self.root / ("d5f09b5ed5f0471a8951b66ee96d513e_Ortomosaico.data" * 2 + ".tif")
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=2,
            height=2,
            count=3,
            dtype="uint8",
            crs="EPSG:4326",
            transform=from_origin(0, 2, 1, 1),
        ) as destination:
            destination.write(np.ones((3, 2, 2), dtype=np.uint8))

        service = RasterService(self._settings(raster_path))
        cache_path = service._tile_cache_path(
            "crop-index",
            service.index_tile_cache_version(),
            18,
            57184,
            115699,
            variant=(
                "ndvi-759302376c324c8ab2bd5f9633d21b2a-linear-transparent-"
                "0.0393-0.9516"
            ),
        )

        self.assertLess(len(str(cache_path)), 240)
        self.assertLess(len(cache_path.name), 100)
        RasterService._write_tile_cache(cache_path, b"png")
        self.assertEqual(cache_path.read_bytes(), b"png")

    def test_rgb_tile_is_cached_after_first_render(self) -> None:
        raster_path = self.root / "rgb-cache.tif"
        mercator_bounds = RasterService.tile_bounds_mercator(0, 0, 0)
        bands = np.full((3, 256, 256), 90, dtype=np.uint8)
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=256,
            height=256,
            count=3,
            dtype="uint8",
            crs="EPSG:3857",
            transform=rasterio.transform.from_bounds(*mercator_bounds, 256, 256),
        ) as destination:
            destination.write(bands)
            self._describe_rgb(destination)

        service = TileCachingRasterService(self._settings(raster_path))
        first = service.tile("rgb", 0, 0, 0)
        second = service.tile("rgb", 0, 0, 0)

        self.assertEqual(service.rgb_tile_renders, 1)
        self.assertEqual(first, second)

    def test_ndvi_tile_is_cached_after_first_render(self) -> None:
        raster_path = self.root / "ndvi-cache.tif"
        mercator_bounds = RasterService.tile_bounds_mercator(0, 0, 0)
        bands = np.ones((6, 256, 256), dtype=np.float32)
        bands[3] = 2.0
        bands[5] = 8.0
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=256,
            height=256,
            count=6,
            dtype="float32",
            crs="EPSG:3857",
            transform=rasterio.transform.from_bounds(*mercator_bounds, 256, 256),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(
                ("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"),
                1,
            ):
                destination.set_band_description(index, description)

        service = TileCachingRasterService(self._settings(raster_path))
        service.sensor = "micasense"
        first = service.tile("ndvi", 0, 0, 0)
        second = service.tile("ndvi", 0, 0, 0)

        self.assertEqual(service.ndvi_tile_renders, 1)
        self.assertEqual(first, second)

    def test_equalized_crop_index_tile_is_cached_after_first_render(self) -> None:
        raster_path = self.root / "ndvi-crop-cache.tif"
        mercator_bounds = RasterService.tile_bounds_mercator(0, 0, 0)
        bands = np.ones((6, 256, 256), dtype=np.float32)
        bands[3] = 2.0
        bands[5] = 8.0
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=256,
            height=256,
            count=6,
            dtype="float32",
            crs="EPSG:3857",
            transform=rasterio.transform.from_bounds(*mercator_bounds, 256, 256),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(
                ("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"),
                1,
            ):
                destination.set_band_description(index, description)

        service = TileCachingRasterService(self._settings(raster_path))
        service.sensor = "micasense"
        crop = service.begin_crop_tiles(box(*rasterio.warp.transform_bounds("EPSG:3857", "EPSG:4326", *mercator_bounds)))

        first = service.crop_index_tile(
            "NDVI",
            crop["crop_id"],
            0,
            0,
            0,
            low=-0.05,
            high=1.0,
            equalized=True,
        )
        second = service.crop_index_tile(
            "NDVI",
            crop["crop_id"],
            0,
            0,
            0,
            low=-0.05,
            high=1.0,
            equalized=True,
        )

        self.assertEqual(service.ndvi_tile_renders, 1)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()

