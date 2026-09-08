"""Compare bounded processing with the original full-array calculations."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.warp import reproject
from rasterio.windows import Window, transform as window_transform
from shapely.geometry import Polygon, mapping

from geofield.services import raster_processing as processing
from geofield.services.raster_service import RasterService


class RasterProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "source.tif"
        rng = np.random.default_rng(42)
        data = rng.uniform(1, 10, (2, 31, 37)).astype(np.float32)
        data[:, 3:8, 5:10] = 0
        self.transform = from_origin(500000, 2500000, 0.2, 0.2)
        with rasterio.open(self.path, "w", driver="GTiff", count=2, width=37,
                           height=31, dtype="float32", crs="EPSG:32613",
                           transform=self.transform, nodata=0) as dst:
            dst.write(data)
        self.geometry = Polygon([self.transform * p for p in
                                 [(1.4, 1.7), (35, 2), (28, 29), (3, 24)]])

    def test_disk_and_memory_grids_match_original_native_aggregation(self):
        with rasterio.open(self.path) as src:
            index, valid = RasterService._calculate_index(*src.read())
            valid &= np.all(src.read_masks() > 0, axis=0)
            valid &= src.dataset_mask() > 0
            valid &= geometry_mask([mapping(self.geometry)], out_shape=index.shape,
                                   transform=src.transform, invert=True, all_touched=True)
            valid &= (index >= -0.3) & (index <= 0.6)
            selected = index[valid]
            index[~valid] = np.nan
            for angle in (0, 17):
                dst_transform = self.transform * Affine.rotation(angle) * Affine.scale(5, 5)
                for mode, resampling in (("mean", Resampling.average),
                                         ("min", Resampling.min), ("max", Resampling.max)):
                    expected = np.full((8, 9), np.nan, dtype=np.float32)
                    fraction = np.zeros((8, 9), dtype=np.float32)
                    options = dict(src_transform=src.transform, src_crs=src.crs,
                                   dst_transform=dst_transform, dst_crs=src.crs)
                    reproject(index, expected, src_nodata=np.nan, dst_nodata=np.nan,
                              resampling=resampling, **options)
                    reproject(valid.astype(np.float32), fraction, dst_nodata=0,
                              resampling=Resampling.average, **options)
                    for limit in (0, 100000):
                        with self.subTest(angle=angle, mode=mode, limit=limit):
                            with patch.object(processing, "MEMORY_PIXELS", limit), \
                                 patch.object(processing, "BLOCK_SIZE", 8):
                                actual, coverage, stats = processing.classification_grid(
                                    src, Window(0, 0, 37, 31), self.geometry, (1, 2),
                                    RasterService._calculate_index, dst_transform, src.crs,
                                    8, 9, mode, -0.3, 0.6,
                                    self.root / f"cache-{angle}-{mode}-{limit}",
                                )
                            np.testing.assert_allclose(actual, expected, atol=1e-7)
                            np.testing.assert_allclose(coverage, fraction, atol=1e-7)
                            np.testing.assert_allclose(stats, [selected.min(), selected.max(),
                                                              selected.mean(dtype=np.float64)])
        self.assertFalse(list(self.root.rglob("grid-*")))

    def test_range_matches_original_fractional_window_and_reuses_cache(self):
        with rasterio.open(self.path) as src:
            window = Window(1.3, 2.7, 32.4, 26.2)
            values, valid = RasterService._calculate_index(*src.read(window=window))
            valid &= geometry_mask([mapping(self.geometry)], out_shape=values.shape,
                                   transform=window_transform(window, src.transform),
                                   invert=True, all_touched=True)
            expected = (float(values[valid].min()), float(values[valid].max()))
            with patch.object(processing, "BLOCK_SIZE", 7):
                actual = processing.index_range(src, window, self.geometry, (1, 2),
                                                RasterService._calculate_index, self.root)
            self.assertEqual(actual, expected)
            def unexpected(*args):
                self.fail("Cached range recalculated")
            self.assertEqual(processing.index_range(src, window, self.geometry, (1, 2),
                                                     unexpected, self.root), expected)

    def test_grid_cache_reused_and_invalidated_by_source_change(self):
        calls = []
        def calculate(*args):
            calls.append(1)
            return RasterService._calculate_index(*args)
        def run():
            with rasterio.open(self.path) as src:
                return processing.classification_grid(
                    src, Window(0, 0, 37, 31), self.geometry, (1, 2), calculate,
                    self.transform * Affine.scale(5, 5), src.crs, 7, 8, "mean",
                    None, None, self.root / "cache",
                )
        first = run()
        calls.clear()
        second = run()
        self.assertEqual(calls, [])
        np.testing.assert_array_equal(first[0], second[0])
        with rasterio.open(self.path, "r+") as dst:
            dst.write(np.ones((31, 37), dtype=np.float32), 1)
        run()
        self.assertTrue(calls)


if __name__ == "__main__":
    unittest.main()
