from __future__ import annotations

import unittest

from geofield.services.tree_service import TreeService


class TreeServiceTests(unittest.TestCase):
    """Protege el contrato de normalización compartido con el frontend."""

    @staticmethod
    def feature(properties: dict[str, object]) -> dict[str, object]:
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [-103.3496, 20.6597]},
            "properties": properties,
        }

    def normalize(self, properties: dict[str, object]) -> dict[str, object]:
        result = TreeService.normalize_feature(self.feature(properties))
        if result is None:
            self.fail("La detección válida fue descartada.")
        normalized = result["properties"]
        self.assertIsInstance(normalized, dict)
        return normalized

    def test_inclusive_class_thresholds(self) -> None:
        cases = (
            (2.5, "small"),
            (2.51, "medium"),
            (3.5, "medium"),
            (3.51, "large"),
        )
        for diameter, expected in cases:
            with self.subTest(diameter=diameter):
                properties = self.normalize({"diameter_m": diameter})
                self.assertEqual(properties["size_class"], expected)

    def test_radius_is_converted_to_diameter(self) -> None:
        properties = self.normalize({"radius_m": 1.6})
        self.assertEqual(properties["diameter_m"], 3.2)
        self.assertEqual(properties["size_class"], "medium")

    def test_bbox_preserves_both_dimensions_and_average(self) -> None:
        properties = self.normalize(
            {"bbox_w_px": 30, "bbox_h_px": 26, "pixel_size_m": 0.1}
        )
        self.assertEqual(properties["diam_x_m"], 3.0)
        self.assertEqual(properties["diam_y_m"], 2.6)
        self.assertEqual(properties["diam_avg_m"], 2.8)

    def test_direct_diameter_has_priority_over_radius(self) -> None:
        properties = self.normalize({"diameter_m": 2.1, "radius_m": 3})
        self.assertEqual(properties["diameter_m"], 2.1)

    def test_invalid_geometry_is_omitted_and_unknown_point_is_preserved(self) -> None:
        line = {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            "properties": {},
        }
        self.assertIsNone(TreeService.normalize_feature(line))
        properties = self.normalize({})
        self.assertEqual(properties["size_class"], "unknown")
        self.assertIsNone(properties["diam_x_m"])
        self.assertIsNone(properties["diam_y_m"])


if __name__ == "__main__":
    unittest.main()
