"""Pruebas unitarias del servicio raster y sus cálculos espectrales."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
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
        mercator_bounds = rasterio.warp.transform_bounds(
            "EPSG:4326",
            "EPSG:3857",
            0,
            0,
            4,
            4,
        )
        self.service.tile_bounds_mercator = lambda _z, _x, _y: mercator_bounds  # type: ignore[method-assign]
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
        expected_color = self.service._index_color_lut("NDVI")[204]

        self.assertEqual(full.shape, (256, 256, 4))
        np.testing.assert_array_equal(crop, full)
        np.testing.assert_array_equal(
            full[128, 128],
            np.array([*expected_color[:3], 255], dtype=np.uint8),
        )

    def test_ndvi_uses_one_fixed_256_entry_color_lut(self) -> None:
        first = self.service._index_color_lut("NDVI")
        second = self.service._index_color_lut("NDVI")

        self.assertIs(first, second)
        self.assertEqual(first.shape, (256, 4))
        self.assertTrue(np.all(first[:, 3] == 255))

    def test_ndre_uses_the_same_color_ramp_as_ndvi(self) -> None:
        self.assertEqual(
            self.service.INDEX_RAMPS["NDRE"],
            self.service.INDEX_RAMPS["NDVI"],
        )
        np.testing.assert_array_equal(
            self.service._index_color_lut("NDRE"),
            self.service._index_color_lut("NDVI"),
        )

    def test_ndwi_zone_palette_uses_its_own_ramp_for_four_zones(self) -> None:
        colors = self.service._zone_palette("NDWI", 4)
        expected = np.asarray(
            [
                [192, 0, 58],
                [255, 170, 0],
                [77, 212, 224],
                [0, 0, 255],
            ],
            dtype=np.uint8,
        )

        np.testing.assert_array_equal(colors, expected)

    def test_mavic3m_ndvi_ignores_alpha_band_in_five_band_exports(self) -> None:
        raster_path = self.root / "mavic3m_alpha.tif"
        bands = np.ones((5, 4, 4), dtype=np.float32)
        bands[1] = 2.0  # Red, band 2.
        bands[3] = 8.0  # NIR, band 4.
        bands[4] = 255.0  # Alpha, band 5.
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=5,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(0, 4, 1, 1),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(
                ("Green", "Red", "Red edge", "NIR", "Alpha"),
                1,
            ):
                destination.set_band_description(index, description)
            destination.colorinterp = (
                ColorInterp.undefined,
                ColorInterp.undefined,
                ColorInterp.undefined,
                ColorInterp.undefined,
                ColorInterp.alpha,
            )

        service = RasterService(self.service.settings)
        service.active_path = raster_path
        service.sensor = "mavic3m"

        self.assertEqual(service._ndvi_bands(), (2, 4))
        values = service.vegetation_index_data("NDWI")["matrix"]
        self.assertAlmostEqual(values[0][0], (1.0 - 8.0) / (1.0 + 8.0), places=6)

    def test_adjacent_ndvi_tiles_keep_matrix_and_color_aligned(self) -> None:
        raster_path = self.root / "ndvi-adjacent.tif"
        left_bounds = RasterService.tile_bounds_mercator(1, 0, 0)
        right_bounds = RasterService.tile_bounds_mercator(1, 1, 0)
        raster_bounds = (
            left_bounds[0],
            left_bounds[1],
            right_bounds[2],
            left_bounds[3],
        )
        bands = np.ones((6, 256, 512), dtype=np.float32)
        bands[3] = 2.0
        bands[5] = 4.0
        bands[5, 119:124, :] = 8.0
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=512,
            height=256,
            count=6,
            dtype="float32",
            crs="EPSG:3857",
            transform=rasterio.transform.from_bounds(*raster_bounds, 512, 256),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(
                ("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"),
                1,
            ):
                destination.set_band_description(index, description)

        service = RasterService(self.service.settings)
        service.active_path = raster_path
        service.sensor = "micasense"
        left_tile = self._rgba(service.index_tile("NDVI", 1, 0, 0))
        right_tile = self._rgba(service.index_tile("NDVI", 1, 1, 0))

        np.testing.assert_array_equal(left_tile[:, -1], right_tile[:, 0])
        left_line_rows = np.flatnonzero(
            np.any(left_tile[:, -1, :3] != left_tile[0, -1, :3], axis=1),
        )
        right_line_rows = np.flatnonzero(
            np.any(right_tile[:, 0, :3] != right_tile[0, 0, :3], axis=1),
        )
        np.testing.assert_array_equal(left_line_rows, right_line_rows)

    def test_roi_range_only_changes_visibility_not_color_scale(self) -> None:
        crop = self._rgba(self.service.crop_index_tile("NDVI", self.crop_id, 0, 0, 0, low=0.7, high=1.0))
        expected_color = self.service._index_color_lut("NDVI")[204]

        np.testing.assert_array_equal(
            crop[128, 128],
            np.array([*expected_color[:3], 0], dtype=np.uint8),
        )

    def test_equalized_tiles_reuse_cached_cdf_for_same_roi_and_range(self) -> None:
        calls = 0
        original = self.service._equalization_response

        def wrapped(name: str, crop_id: str | None):
            nonlocal calls
            calls += 1
            return original(name, crop_id)

        self.service._equalization_response = wrapped  # type: ignore[method-assign]

        first = self._rgba(
            self.service.crop_index_tile(
                "NDVI",
                self.crop_id,
                0,
                0,
                0,
                low=-0.05,
                high=1.0,
                equalized=True,
            ),
        )
        second = self._rgba(
            self.service.crop_index_tile(
                "NDVI",
                self.crop_id,
                0,
                0,
                0,
                low=-0.05,
                high=1.0,
                equalized=True,
            ),
        )

        self.assertEqual(calls, 1)
        np.testing.assert_array_equal(first, second)

    def test_crop_export_preserves_bands_crs_and_geometry_mask(self) -> None:
        crop = self.service.begin_crop_tiles(
            box(0, 0, 2, 2).difference(box(1, 1, 2, 2)),
        )

        content = self.service.export_crop(crop["crop_id"])

        with MemoryFile(content) as memory_file:
            with memory_file.open() as exported:
                self.assertEqual(exported.count, 6)
                self.assertEqual(exported.crs.to_string(), "EPSG:4326")
                self.assertEqual((exported.width, exported.height), (2, 2))
                mask = exported.dataset_mask()
                self.assertTrue(np.any(mask == 255))
                self.assertTrue(np.any(mask == 0))

    def test_cloud_visual_crop_is_uint8_rgba_and_keeps_georeferencing(self) -> None:
        crop = self.service.begin_crop_tiles(
            box(0, 0, 2, 2).difference(box(1, 1, 2, 2)),
        )

        visual = self.service.export_crop_visual(crop["crop_id"])
        analytical = self.service.export_crop(crop["crop_id"])

        with MemoryFile(analytical) as analytical_file, MemoryFile(visual) as visual_file:
            with analytical_file.open() as analytical_raster, visual_file.open() as visual_raster:
                self.assertEqual(visual_raster.count, 4)
                self.assertEqual(visual_raster.dtypes, ("uint8",) * 4)
                self.assertEqual(
                    visual_raster.colorinterp,
                    (
                        ColorInterp.red,
                        ColorInterp.green,
                        ColorInterp.blue,
                        ColorInterp.alpha,
                    ),
                )
                self.assertEqual(visual_raster.crs, analytical_raster.crs)
                self.assertEqual(visual_raster.transform, analytical_raster.transform)
                alpha = visual_raster.read(4)
                self.assertTrue(np.any(alpha == 255))
                self.assertTrue(np.any(alpha == 0))

    def test_truncated_geotiff_is_rejected_before_persistence(self) -> None:
        content = self.service.settings.raster_path.read_bytes()

        with self.assertRaisesRegex(ValueError, "incompleto o dañado"):
            self.service.validate_uploaded(content[: len(content) // 2])

    def test_prescription_fills_internal_gaps_and_clips_boundary_cells(self) -> None:
        zones = np.asarray(
            [
                [1, 0, 0],
                [0, 0, 0],
                [0, 0, 2],
            ],
            dtype=np.uint8,
        )
        target_mask = np.asarray(
            [
                [True, True, False],
                [True, True, True],
                [False, True, True],
            ],
        )
        filled = self.service._fill_unclassified_cells(zones, target_mask)
        self.assertTrue(np.all(filled[target_mask] > 0))
        self.assertTrue(np.all(filled[~target_mask] == 0))

        rgba = np.full((2, 2, 4), 255, dtype=np.uint8)
        artifact_id = "a" * 32
        self.service._render_classification_artifact(
            artifact_id,
            rgba,
            from_origin(0, 2, 1, 1),
            "EPSG:32613",
            Polygon([(0, 0), (0, 2), (2, 0)]),
        )
        rendered = np.asarray(
            Image.open(
                self.service.settings.output_dir / "prescriptions" / f"{artifact_id}.png",
            ).convert("RGBA"),
        )
        self.assertTrue(np.any(rendered[..., 3] == 255))
        self.assertTrue(np.any(rendered[..., 3] == 0))

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
        )

        self.assertEqual(zoning["stage"], "zoning")
        self.assertEqual(zoning["index_name"], "NDVI")
        self.assertIn("/{z}/{x}/{y}.png", zoning["tile_url"])
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
            ["#ff1f1f", "#ff9b1f", "#d6f01f", "#30df1f"],
        )
        self.assertEqual(zoning["legend"][0]["percentile_min"], 0.0)
        self.assertEqual(zoning["legend"][-1]["percentile_max"], 100.0)

        self.assertEqual(prescription["stage"], "prescription")
        self.assertEqual(prescription["index_name"], "NDVI")
        self.assertIn("/{z}/{x}/{y}.png", prescription["tile_url"])
        self.assertTrue(prescription["grid_url"].endswith("_grid.geojson"))
        self.assertTrue(prescription["geojson_url"].endswith("_fill.geojson"))
        self.assertTrue(prescription["json_url"].endswith("/download.json"))
        self.assertEqual(prescription["zone_count"], 4)
        self.assertEqual(prescription["cell_size_m"], 3)
        self.assertEqual(prescription["valid_cell_count"], 9)
        self.assertEqual(len(prescription["legend"]), 4)
        self.assertEqual(
            [zone["class_id"] for zone in prescription["legend"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [zone["label"] for zone in prescription["legend"]],
            ["NDVI muy bajo", "NDVI bajo", "NDVI medio-alto", "NDVI alto"],
        )
        self.assertTrue(all(isinstance(zone["mean"], float) for zone in prescription["legend"]))
        alignment = prescription["debug"]["alignment"]
        self.assertEqual(alignment["roi_input_crs"], "EPSG:4326")
        self.assertEqual(alignment["raster_crs"], "EPSG:32613")
        self.assertEqual(alignment["grid_crs"], "EPSG:32613")
        self.assertEqual(alignment["raster_width"], 9)
        self.assertEqual(alignment["raster_height"], 9)
        self.assertEqual(alignment["feature_count"], prescription["valid_cell_count"])
        self.assertEqual(len(alignment["raster_transform"]), 9)
        self.assertLess(alignment["roi_bounds_raster"][0], alignment["roi_bounds_raster"][2])
        self.assertLess(alignment["roi_bounds_raster"][1], alignment["roi_bounds_raster"][3])
        self.assertLessEqual(alignment["grid_bounds"][0], alignment["roi_bounds_raster"][0])
        self.assertLessEqual(alignment["grid_bounds"][1], alignment["roi_bounds_raster"][1])
        self.assertGreaterEqual(alignment["grid_bounds"][2], alignment["roi_bounds_raster"][2])
        self.assertGreaterEqual(alignment["grid_bounds"][3], alignment["roi_bounds_raster"][3])

        image_name = Path(prescription["image_url"]).name
        image_path = self.service.settings.output_dir / "prescriptions" / image_name
        self.assertTrue(image_path.is_file())
        rendered = np.asarray(Image.open(image_path).convert("RGBA"))
        self.assertEqual(rendered.shape[:2], (96, 96))
        visible_alpha = rendered[..., 3][rendered[..., 3] > 0]
        self.assertTrue(np.all(visible_alpha == 255))
        expected_colors = {
            tuple(color)
            for color in self.service._zone_display_palette("NDVI", 4)
        }
        rendered_colors = {
            tuple(color)
            for color in rendered[..., :3][rendered[..., 3] > 0]
        }
        self.assertTrue(rendered_colors)
        self.assertTrue(rendered_colors.issubset(expected_colors))

        artifact_path = image_path.with_suffix(".tif")
        self.assertTrue(artifact_path.is_file())
        with rasterio.open(artifact_path) as artifact:
            artifact_bounds = rasterio.warp.transform_bounds(
                artifact.crs,
                "EPSG:3857",
                *artifact.bounds,
                densify_pts=21,
            )
        self.service.tile_bounds_mercator = lambda _z, _x, _y: artifact_bounds  # type: ignore[method-assign]
        tile = self._rgba(
            self.service.prescription_tile(prescription["prescription_id"], 0, 0, 0),
        )
        self.assertEqual(tile.shape, (256, 256, 4))
        self.assertTrue(np.any(tile[..., 3] == 255))
        self.assertTrue(np.all(tile[..., 3] == 255))

        json_path = (
            self.service.settings.output_dir
            / "prescriptions"
            / f"{prescription['prescription_id']}.json"
        )
        exported_json = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(exported_json["cellSize"], 3)
        self.assertEqual(exported_json["columns"], 3)
        self.assertEqual(exported_json["rows"] * exported_json["columns"], len(exported_json["weightData"]))
        self.assertEqual(exported_json["rows"], 3)
        self.assertEqual(exported_json["dataType"], 4)
        self.assertEqual(exported_json["source"], "Pix4D")
        self.assertEqual(exported_json["version"], 1)
        self.assertEqual(exported_json["workType"], 1)
        self.assertEqual(exported_json["rotation"], 0.0)
        self.assertRegex(exported_json["guid"], r"^[0-9a-f-]{36}$")
        self.assertEqual(
            [item["level"] for item in exported_json["dataTypeLevel"]],
            [1, 2, 3, 4],
        )
        self.assertEqual(
            [item["dosage"] for item in exported_json["dataTypeLevel"]],
            [0.0, 0.0, 0.0, 0.0],
        )
        self.assertTrue(any(value > 0 for value in exported_json["weightData"]))
        self.assertTrue(all(isinstance(value, (int, float)) for value in exported_json["weightData"]))
        self.assertTrue(set(exported_json["weightData"]).issubset({0, 1, 2, 3, 4}))
        self.assertIn(4, exported_json["weightData"])
        self.assertEqual(
            [exported_json["weightData"].count(class_id) for class_id in range(1, 5)],
            [zone["cell_count"] for zone in prescription["legend"]],
        )
        self.assertLess(exported_json["originLat"], exported_json["originEndLat"])
        self.assertLess(exported_json["originLng"], exported_json["originEndLng"])

        fill_geojson_path = (
            self.service.settings.output_dir
            / "prescriptions"
            / Path(prescription["geojson_url"]).name
        )
        fill_geojson = json.loads(fill_geojson_path.read_text(encoding="utf-8"))
        self.assertEqual(fill_geojson["type"], "FeatureCollection")
        self.assertEqual(len(fill_geojson["features"]), prescription["valid_cell_count"])
        roi_geometry = roi
        for feature in fill_geojson["features"]:
            self.assertIn("geometry", feature)
            self.assertIn("properties", feature)
            self.assertIn("id", feature)
            self.assertIn(feature["properties"]["zone"], {1, 2, 3, 4})
            self.assertIsInstance(feature["properties"]["value"], float)
            self.assertIsInstance(feature["properties"]["color"], str)
            clipped_geometry = shape(feature["geometry"])
            self.assertFalse(clipped_geometry.is_empty)
            self.assertTrue(clipped_geometry.buffer(1e-12).within(roi_geometry.buffer(1e-9)))

    def test_ndre_prescription_uses_same_json_export_flow(self) -> None:
        raster_path = self.root / "prescription_ndre.tif"
        bands = np.ones((6, 9, 9), dtype=np.float32)
        bands[4] = np.linspace(2, 6, 81, dtype=np.float32).reshape(9, 9)
        bands[5] = 10.0
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
        prescription = self.service.prescription_map_with_doses(
            roi,
            index_name="NDRE",
            zone_count=4,
            cell_size_m=3,
        )

        self.assertEqual(prescription["index_name"], "NDRE")
        json_path = (
            self.service.settings.output_dir
            / "prescriptions"
            / f"{prescription['prescription_id']}.json"
        )
        exported_json = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(exported_json["dataType"], 4)
        self.assertIn("weightData", exported_json)

    def test_prescription_json_uses_manual_doses_when_provided(self) -> None:
        raster_path = self.root / "prescription_doses.tif"
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
        doses = [120.0, 180.5, 240.25, 300.0]

        prescription = self.service.prescription_map_with_doses(
            roi,
            index_name="NDVI",
            zone_count=4,
            cell_size_m=3,
            doses=doses,
        )

        json_path = (
            self.service.settings.output_dir
            / "prescriptions"
            / f"{prescription['prescription_id']}.json"
        )
        exported_json = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [item["dosage"] for item in exported_json["dataTypeLevel"]],
            [12.0, 18.05, 24.025, 30.0],
        )
        self.assertEqual(
            [zone["dosage"] for zone in prescription["legend"]],
            doses,
        )

    def test_quantiles_with_maximum_detail_keep_near_equal_cell_distribution(self) -> None:
        values = np.linspace(0.1, 0.8, 16, dtype=np.float32).reshape(4, 4)
        breaks = self.service._classification_breaks(
            values.ravel(),
            4,
            "quantiles",
            float(values.min()),
            float(values.max()),
            None,
        )
        initial = np.zeros_like(values, dtype=np.uint8)
        valid = np.ones_like(values, dtype=bool)
        initial[valid] = (
            np.digitize(values[valid], breaks[1:-1], right=False) + 1
        ).astype(np.uint8)

        final = self.service._regularize_zones(initial, valid, values, breaks, 1.0)
        counts = [int(np.count_nonzero(final == class_id)) for class_id in range(1, 5)]

        self.assertEqual(counts, [4, 4, 4, 4])

    def test_quantile_breaks_keep_active_histogram_edges(self) -> None:
        values = np.array([0.177, 0.385, 0.507, 0.539, 0.569, 0.593, 0.613, 0.727], dtype=np.float32)

        breaks = self.service._classification_breaks(
            values,
            4,
            "quantiles",
            0.007,
            0.921,
            None,
        )

        self.assertEqual(len(breaks), 5)
        self.assertAlmostEqual(float(breaks[0]), 0.007, places=6)
        self.assertAlmostEqual(float(breaks[-1]), 0.921, places=6)
        np.testing.assert_allclose(
            breaks[1:-1],
            np.quantile(values, [0.25, 0.5, 0.75]).astype(np.float32),
        )

    def test_equal_quantile_and_manual_classification_stay_separate_from_smoothing(self) -> None:
        values = np.linspace(0.1, 0.9, 100, dtype=np.float32).reshape(10, 10)
        valid = np.ones_like(values, dtype=bool)
        configurations = (
            ("quantiles", None),
            ("equal_intervals", None),
            ("manual", [0.30, 0.55, 0.72]),
        )

        for method, manual_breaks in configurations:
            with self.subTest(method=method):
                breaks = self.service._classification_breaks(
                    values.ravel(),
                    4,
                    method,
                    0.1,
                    0.9,
                    manual_breaks,
                )
                initial = (np.digitize(values, breaks[1:-1]) + 1).astype(np.uint8)
                detailed = self.service._regularize_zones(
                    initial,
                    valid,
                    values,
                    breaks,
                    1.0,
                )
                np.testing.assert_array_equal(detailed, initial)
                np.testing.assert_array_equal(
                    breaks,
                    self.service._classification_breaks(
                        values.ravel(),
                        4,
                        method,
                        0.1,
                        0.9,
                        manual_breaks,
                    ),
                )

    def test_cell_aggregation_supports_mean_minimum_and_maximum(self) -> None:
        values = np.arange(1, 17, dtype=np.float32).reshape(4, 4)
        valid = np.ones_like(values, dtype=bool)
        expected = {
            "mean": np.array([[3.5, 5.5], [11.5, 13.5]], dtype=np.float32),
            "min": np.array([[1, 3], [9, 11]], dtype=np.float32),
            "max": np.array([[6, 8], [14, 16]], dtype=np.float32),
        }

        for mode, expected_values in expected.items():
            with self.subTest(mode=mode):
                aggregated, areas = self.service._aggregate_cell_values(
                    values,
                    valid,
                    height=2,
                    width=2,
                    oversample=2,
                    cell_value_mode=mode,
                    cell_size_m=2,
                )
                np.testing.assert_array_equal(aggregated, expected_values)
                np.testing.assert_array_equal(areas, np.full((2, 2), 4, dtype=np.float32))

    def test_slider_preserves_thresholds_but_changes_coverage(self) -> None:
        values = np.array(
            [
                [0.11, 0.12, 0.13, 0.74],
                [0.10, 0.75, 0.14, 0.73],
                [0.15, 0.16, 0.72, 0.71],
                [0.17, 0.18, 0.19, 0.70],
            ],
            dtype=np.float32,
        )
        breaks = self.service._classification_breaks(
            values.ravel(),
            4,
            "quantiles",
            float(values.min()),
            float(values.max()),
            None,
        )
        initial = np.zeros_like(values, dtype=np.uint8)
        valid = np.ones_like(values, dtype=bool)
        initial[valid] = (
            np.digitize(values[valid], breaks[1:-1], right=False) + 1
        ).astype(np.uint8)

        detailed = self.service._regularize_zones(initial, valid, values, breaks, 1.0)
        simplified = self.service._regularize_zones(initial, valid, values, breaks, 0.0)

        np.testing.assert_allclose(
            breaks,
            self.service._classification_breaks(
                values.ravel(),
                4,
                "quantiles",
                float(values.min()),
                float(values.max()),
                None,
            ),
        )
        detailed_counts = [int(np.count_nonzero(detailed == class_id)) for class_id in range(1, 5)]
        simplified_counts = [int(np.count_nonzero(simplified == class_id)) for class_id in range(1, 5)]
        self.assertNotEqual(detailed_counts, simplified_counts)
        self.assertLess(
            len(np.unique(simplified[simplified > 0])),
            len(np.unique(detailed[detailed > 0])),
        )

    def test_low_detail_preserves_large_agronomic_bands(self) -> None:
        zones = np.tile(
            np.array([1, 2, 3, 4, 5, 4, 3, 2], dtype=np.uint8),
            (18, 1),
        )
        values = np.tile(
            np.array([0.18, 0.34, 0.5, 0.64, 0.8, 0.66, 0.52, 0.36], dtype=np.float32),
            (18, 1),
        )
        valid = np.ones_like(values, dtype=bool)
        breaks = np.array([0.10, 0.24, 0.40, 0.56, 0.70, 0.86], dtype=np.float32)

        detailed = self.service._regularize_zones(zones, valid, values, breaks, 1.0)
        simplified = self.service._regularize_zones(zones, valid, values, breaks, 0.0)

        np.testing.assert_array_equal(detailed, zones)
        np.testing.assert_array_equal(simplified[1:-1], zones[1:-1])
        self.assertLessEqual(int(np.count_nonzero(simplified != zones)), 2)

    def test_zone_deviation_is_percentage_against_field_mean(self) -> None:
        field_mean = 0.508
        zone_mean = 0.417

        deviation_percent = ((zone_mean - field_mean) / field_mean) * 100

        self.assertAlmostEqual(deviation_percent, -17.91338582677166)

    def test_zoning_histogram_uses_aggregated_cell_values_used_by_prescription(self) -> None:
        raster_path = self.root / "zoning-histogram-samples.tif"
        bands = np.ones((6, 4, 4), dtype=np.float32)
        ndvi_targets = np.array(
            [
                [0.10, 0.20, 0.30, 0.40],
                [0.50, 0.60, 0.70, 0.80],
                [0.15, 0.25, 0.35, 0.45],
                [0.55, 0.65, 0.75, 0.85],
            ],
            dtype=np.float32,
        )
        red = np.ones((4, 4), dtype=np.float32)
        nir = ((1 + ndvi_targets) / (1 - ndvi_targets)).astype(np.float32)
        bands[3] = red
        bands[5] = nir
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=6,
            dtype="float32",
            crs="EPSG:32613",
            transform=from_origin(500_000, 2_500_000, 1, 1),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(
                ("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"),
                1,
            ):
                destination.set_band_description(index, description)

        self.service.active_path = raster_path
        self.service.sensor = "micasense"
        roi = project_geometry(
            pyproj.Transformer.from_crs(
                "EPSG:32613",
                "EPSG:4326",
                always_xy=True,
            ).transform,
            box(500_000, 2_499_996, 500_004, 2_500_000),
        )

        zoning = self.service.ndvi_zoning_map(roi, zone_count=4, cell_size_m=2)

        histogram = zoning["histogram"]
        self.assertAlmostEqual(histogram["minimum"], 0.10, places=2)
        self.assertAlmostEqual(histogram["maximum"], 0.85, places=2)
        self.assertEqual(sum(histogram["bins"]), 4)
        self.assertAlmostEqual(zoning["field_mean"], float(np.mean(ndvi_targets)), places=2)

    def test_zoning_mean_integrates_all_native_pixels_in_each_cell(self) -> None:
        raster_path = self.root / "zoning-native-pixel-mean.tif"
        ndvi_targets = np.empty((40, 40), dtype=np.float32)
        ndvi_targets[:20, :20] = 0.10
        ndvi_targets[:20, 20:] = 0.30
        ndvi_targets[20:, :20] = 0.50
        ndvi_targets[20:, 20:] = 0.70
        # Narrow rows deliberately fall between most points of the previous
        # 4 x 4-per-cell sampler. A true cell mean must still include them.
        ndvi_targets[::10] += 0.20
        red = np.ones_like(ndvi_targets)
        nir = ((1 + ndvi_targets) / (1 - ndvi_targets)).astype(np.float32)
        bands = np.ones((6, 40, 40), dtype=np.float32)
        bands[3] = red
        bands[5] = nir
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=40,
            height=40,
            count=6,
            dtype="float32",
            crs="EPSG:32613",
            transform=from_origin(500_000, 2_500_000, 0.1, 0.1),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(
                ("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"),
                1,
            ):
                destination.set_band_description(index, description)

        self.service.active_path = raster_path
        self.service.sensor = "micasense"
        roi = project_geometry(
            pyproj.Transformer.from_crs(
                "EPSG:32613",
                "EPSG:4326",
                always_xy=True,
            ).transform,
            box(500_000, 2_499_996, 500_004, 2_500_000),
        )
        prepared = self.service._prepare_index_classification(
            "NDVI",
            roi,
            zone_count=2,
            cell_size_m=2,
            cell_value_mode="mean",
        )
        expected = ndvi_targets.reshape(2, 20, 2, 20).mean(axis=(1, 3))

        np.testing.assert_allclose(prepared["index_values"], expected, atol=1e-5)

    def test_quantile_thresholds_are_computed_from_visible_cell_values(self) -> None:
        raster_path = self.root / "zoning-quantile-cells.tif"
        bands = np.ones((6, 4, 4), dtype=np.float32)
        ndvi_targets = np.array(
            [
                [0.90, -1.00, 0.10, 0.10],
                [-1.00, -1.00, 0.10, 0.10],
                [0.20, 0.20, 0.30, 0.30],
                [0.20, 0.20, 0.30, 0.30],
            ],
            dtype=np.float32,
        )
        red = np.ones((4, 4), dtype=np.float32)
        nir = ((1 + ndvi_targets) / (1 - ndvi_targets)).astype(np.float32)
        invalid = ndvi_targets <= -1
        red[invalid] = 0
        nir[invalid] = 0
        bands[3] = red
        bands[5] = nir
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=6,
            dtype="float32",
            crs="EPSG:32613",
            transform=from_origin(500_000, 2_500_000, 1, 1),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(
                ("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"),
                1,
            ):
                destination.set_band_description(index, description)

        self.service.active_path = raster_path
        self.service.sensor = "micasense"
        roi = project_geometry(
            pyproj.Transformer.from_crs(
                "EPSG:32613",
                "EPSG:4326",
                always_xy=True,
            ).transform,
            box(500_000, 2_499_996, 500_004, 2_500_000),
        )

        zoning = self.service.ndvi_zoning_map(roi, zone_count=2, cell_size_m=2)

        self.assertAlmostEqual(zoning["thresholds"][1], 0.25, places=2)
        self.assertAlmostEqual(zoning["histogram"]["breaks"][1], 0.25, places=2)
        self.assertEqual(
            [zone["cell_count"] for zone in zoning["legend"]],
            [2, 2],
        )

    def test_ndvi_zoning_uses_nir_minus_red_not_the_inverse(self) -> None:
        raster_path = self.root / "ndvi-zoning-direction.tif"
        bands = np.ones((6, 4, 4), dtype=np.float32)
        bands[3] = np.array(
            [
                [1, 2, 3, 4],
                [1, 2, 3, 4],
                [1, 2, 3, 4],
                [1, 2, 3, 4],
            ],
            dtype=np.float32,
        )
        bands[5] = 8.0
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=6,
            dtype="float32",
            crs="EPSG:32613",
            transform=from_origin(500_000, 2_500_000, 1, 1),
        ) as destination:
            destination.write(bands)
            for index, description in enumerate(
                ("Blue", "Green", "Panchromatic", "Red", "Red edge", "NIR"),
                1,
            ):
                destination.set_band_description(index, description)

        self.service.active_path = raster_path
        self.service.sensor = "micasense"
        roi = project_geometry(
            pyproj.Transformer.from_crs(
                "EPSG:32613",
                "EPSG:4326",
                always_xy=True,
            ).transform,
            box(500_000, 2_499_996, 500_004, 2_500_000),
        )
        zoning = self.service.ndvi_zoning_map(roi, zone_count=4, cell_size_m=1)
        means = [zone["mean"] for zone in zoning["legend"]]

        self.assertEqual(means, sorted(means))

    def test_regularization_preserves_original_index_values(self) -> None:
        values = np.array(
            [
                [0.11, 0.12, 0.13],
                [0.12, 0.74, 0.13],
                [0.11, 0.12, 0.13],
            ],
            dtype=np.float32,
        )
        breaks = self.service._classification_breaks(
            values.ravel(),
            4,
            "quantiles",
            float(values.min()),
            float(values.max()),
            None,
        )
        valid = np.ones_like(values, dtype=bool)
        initial = np.zeros_like(values, dtype=np.uint8)
        initial[valid] = (
            np.digitize(values[valid], breaks[1:-1], right=False) + 1
        ).astype(np.uint8)
        snapshot = values.copy()

        _final = self.service._regularize_zones(initial, valid, values, breaks, 0.0)

        np.testing.assert_array_equal(values, snapshot)

    def test_fine_preserves_single_cell_and_coarse_removes_it(self) -> None:
        zones = np.array(
            [
                [1, 1, 1],
                [1, 4, 1],
                [1, 1, 1],
            ],
            dtype=np.uint8,
        )
        values = np.array(
            [
                [0.11, 0.12, 0.11],
                [0.12, 0.18, 0.12],
                [0.11, 0.12, 0.11],
            ],
            dtype=np.float32,
        )
        valid = np.ones_like(values, dtype=bool)
        breaks = np.array([0.10, 0.12, 0.14, 0.16, 0.20], dtype=np.float32)

        detailed = self.service._regularize_zones(zones, valid, values, breaks, 1.0)
        simplified = self.service._regularize_zones(zones, valid, values, breaks, 0.0)

        self.assertEqual(int(detailed[1, 1]), 4)
        self.assertNotEqual(int(simplified[1, 1]), 4)

    def test_simplification_preserves_long_narrow_component(self) -> None:
        zones = np.array(
            [
                [1, 1, 1, 1, 1, 1, 1],
                [1, 2, 2, 2, 2, 2, 1],
                [1, 1, 1, 1, 1, 1, 1],
            ],
            dtype=np.uint8,
        )
        values = np.array(
            [
                [0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12],
                [0.12, 0.18, 0.18, 0.18, 0.18, 0.18, 0.12],
                [0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12],
            ],
            dtype=np.float32,
        )
        valid = np.ones_like(values, dtype=bool)
        breaks = np.array([0.10, 0.14, 0.16, 0.18, 0.20], dtype=np.float32)

        simplified = self.service._regularize_zones(zones, valid, values, breaks, 0.0)

        np.testing.assert_array_equal(simplified[1, 2:5], np.full(3, 2, dtype=np.uint8))
        self.assertEqual(int(simplified[1, 1]), 1)
        self.assertEqual(int(simplified[1, 5]), 1)

    def test_coarse_regularization_fills_small_enclosed_hole(self) -> None:
        zones = np.array(
            [
                [1, 1, 1, 1, 1],
                [1, 2, 2, 2, 1],
                [1, 2, 3, 2, 1],
                [1, 2, 2, 2, 1],
                [1, 1, 1, 1, 1],
            ],
            dtype=np.uint8,
        )
        values = np.array(
            [
                [0.12, 0.12, 0.12, 0.12, 0.12],
                [0.12, 0.18, 0.18, 0.18, 0.12],
                [0.12, 0.18, 0.24, 0.18, 0.12],
                [0.12, 0.18, 0.18, 0.18, 0.12],
                [0.12, 0.12, 0.12, 0.12, 0.12],
            ],
            dtype=np.float32,
        )
        valid = np.ones_like(values, dtype=bool)

        breaks = np.array([0.10, 0.15, 0.21, 0.30], dtype=np.float32)
        filled = self.service._regularize_zones(zones, valid, values, breaks, 0.0)

        self.assertEqual(int(filled[2, 2]), 2)

    def test_connected_component_does_not_join_corner_touching_islands(self) -> None:
        zones = np.array(
            [
                [2, 1, 1],
                [1, 2, 1],
                [1, 1, 3],
            ],
            dtype=np.uint8,
        )
        valid = np.ones_like(zones, dtype=bool)
        visited = np.zeros_like(zones, dtype=bool)

        class_id, component, perimeter_counts = self.service._connected_component(
            zones,
            valid,
            visited,
            0,
            0,
            self.service._component_connectivity_offsets(),
            self.service._neighbor_offsets(),
        )

        self.assertEqual(class_id, 2)
        self.assertEqual(component, [(0, 0)])
        self.assertEqual(perimeter_counts, {1: 2})

    def test_simplification_absorbs_corner_touching_single_cells(self) -> None:
        zones = np.ones((5, 5), dtype=np.uint8)
        zones[1, 1] = 2
        zones[2, 2] = 2
        zones[3, 3] = 2
        valid = np.ones_like(zones, dtype=bool)
        values = np.full(zones.shape, 0.12, dtype=np.float32)
        values[zones == 2] = 0.18
        breaks = np.array([0.10, 0.14, 0.20], dtype=np.float32)

        detailed = self.service._regularize_zones(zones, valid, values, breaks, 1.0)
        simplified = self.service._regularize_zones(zones, valid, values, breaks, 0.0)

        np.testing.assert_array_equal(detailed, zones)
        np.testing.assert_array_equal(simplified, np.ones_like(zones))

    def test_simple_removes_a_weakly_attached_spur_from_a_large_component(self) -> None:
        zones = np.ones((13, 17), dtype=np.uint8)
        zones[2:11, 2:11] = 2
        zones[6, 11:14] = 2
        valid = np.ones_like(zones, dtype=bool)
        values = np.full(zones.shape, 0.12, dtype=np.float32)
        values[zones == 2] = 0.18
        breaks = np.array([0.10, 0.14, 0.20], dtype=np.float32)

        detailed = self.service._regularize_zones(zones, valid, values, breaks, 1.0)
        simplified = self.service._regularize_zones(zones, valid, values, breaks, 0.0)

        self.assertEqual(int(detailed[6, 13]), 2)
        self.assertEqual(int(detailed[6, 12]), 2)
        np.testing.assert_array_equal(simplified[2:11, 2:11], np.full((9, 9), 2, dtype=np.uint8))
        np.testing.assert_array_equal(simplified[6, 11:14], np.array([2, 2, 1], dtype=np.uint8))

    def test_component_merge_combines_boundary_spectral_and_continuity_evidence(self) -> None:
        zones = np.array(
            [
                [1, 1, 1, 2, 2],
                [1, 3, 1, 2, 2],
                [1, 1, 2, 2, 2],
            ],
            dtype=np.uint8,
        )
        values = np.where(zones == 1, 0.10, np.where(zones == 2, 0.48, 0.50)).astype(np.float32)
        areas = np.ones_like(values, dtype=np.float32)
        target = self.service._select_component_target(
            {1: 3, 2: 2},
            3,
            [(1, 1)],
            zones,
            values,
            areas,
            {1: 6.0, 2: 7.0, 3: 1.0},
            np.array([0.0, 0.2, 0.4, 0.55], dtype=np.float32),
        )

        self.assertEqual(target, 2)

    def test_regularization_never_crosses_nodata_barrier(self) -> None:
        zones = np.ones((7, 9), dtype=np.uint8)
        zones[:, 4] = 0
        zones[:, 5:] = 2
        valid = zones > 0
        values = np.where(zones == 2, 0.8, 0.2).astype(np.float32)
        values[~valid] = np.nan
        breaks = np.array([0.0, 0.5, 1.0], dtype=np.float32)

        simplified = self.service._regularize_zones(zones, valid, values, breaks, 0.0)

        np.testing.assert_array_equal(simplified[:, 4], np.zeros(7, dtype=np.uint8))
        np.testing.assert_array_equal(simplified[:, :4], np.ones((7, 4), dtype=np.uint8))
        np.testing.assert_array_equal(simplified[:, 5:], np.full((7, 4), 2, dtype=np.uint8))

    def test_detail_levels_progressively_reduce_fragmentation_and_perimeter(self) -> None:
        height, width = 80, 120
        rows, columns = np.mgrid[:height, :width]
        values = (
            0.12
            + 0.72 * columns / (width - 1)
            + 0.06 * np.sin(rows / 8)
        ).astype(np.float32)
        breaks = np.array([0.05, 0.25, 0.45, 0.65, 0.90], dtype=np.float32)
        zones = (np.digitize(values, breaks[1:-1]) + 1).astype(np.uint8)
        random = np.random.default_rng(42)
        noisy_rows = random.integers(0, height, 700)
        noisy_columns = random.integers(0, width, 700)
        zones[noisy_rows, noisy_columns] = random.integers(1, 5, 700)
        valid = np.ones_like(zones, dtype=bool)
        areas = np.full(zones.shape, 9.0, dtype=np.float32)
        metrics = []

        for detail_level in (1.0, 0.75, 0.50, 0.25, 0.0):
            result = self.service._regularize_zones(
                zones,
                valid,
                values,
                breaks,
                detail_level,
                areas,
            )
            parameters = self.service._spatial_detail_parameters(detail_level, valid, areas)
            metrics.append(
                self.service._zone_debug_snapshot(
                    result,
                    valid,
                    values,
                    areas,
                    4,
                    float(parameters["minimum_region_area_m2"]),
                ),
            )

        component_counts = [metric["connected_components"] for metric in metrics]
        perimeters = [metric["internal_perimeter_m"] for metric in metrics]
        self.assertEqual(component_counts, sorted(component_counts, reverse=True))
        self.assertLess(component_counts[-1], component_counts[0] * 0.05)
        self.assertLess(perimeters[-1], perimeters[0] * 0.25)
        self.assertTrue(all(len(metric["zones"]) == 4 for metric in metrics))


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
