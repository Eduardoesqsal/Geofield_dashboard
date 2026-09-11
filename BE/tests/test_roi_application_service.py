"""Pruebas de validaciones de aplicacion para analisis ROI."""

from __future__ import annotations

import unittest

from geofield.services.application_service import RoiApplicationService


class RoiApplicationServiceTests(unittest.TestCase):
    def test_normalize_roi_analysis_stats_casts_numeric_payload(self) -> None:
        stats = RoiApplicationService.normalize_roi_analysis_stats(
            {
                "count": "15",
                "min": "-0.12",
                "max": "0.91",
                "mean": "0.47",
                "median": "0.5",
                "standard_deviation": "0.08",
                "p10": "0.1",
                "p25": "0.2",
                "p75": "0.7",
                "p90": "0.8",
                "range_min": "-0.2",
                "range_max": "1.0",
            },
        )

        self.assertEqual(stats["count"], 15)
        self.assertEqual(stats["min"], -0.12)
        self.assertEqual(stats["max"], 0.91)
        self.assertEqual(stats["range_max"], 1.0)

    def test_normalize_roi_analysis_stats_rejects_negative_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "count no puede ser negativo"):
            RoiApplicationService.normalize_roi_analysis_stats(
                {
                    "count": -1,
                    "min": 0,
                    "max": 1,
                    "mean": 0.5,
                    "median": 0.5,
                    "standard_deviation": 0.1,
                },
            )

    def test_normalize_roi_analysis_stats_rejects_non_finite_number(self) -> None:
        with self.assertRaisesRegex(ValueError, "mean debe ser un numero finito"):
            RoiApplicationService.normalize_roi_analysis_stats(
                {
                    "count": 1,
                    "min": 0,
                    "max": 1,
                    "mean": float("nan"),
                    "median": 0.5,
                    "standard_deviation": 0.1,
                },
            )

    def test_stats_match_compares_normalized_numeric_values(self) -> None:
        expected = {
            "count": "3",
            "min": "0.1",
            "max": "0.9",
            "mean": "0.5",
            "median": "0.5",
            "standard_deviation": "0.2",
            "p10": "0.2",
            "p25": "0.3",
            "p75": "0.7",
            "p90": "0.8",
            "range_min": "0.0",
            "range_max": "1.0",
        }
        persisted = {
            "count": 3,
            "min": 0.1,
            "max": 0.9,
            "mean": 0.5,
            "median": 0.5,
            "standard_deviation": 0.2,
            "p10": 0.2,
            "p25": 0.3,
            "p75": 0.7,
            "p90": 0.8,
            "range_min": 0.0,
            "range_max": 1.0,
        }

        self.assertTrue(RoiApplicationService.stats_match(persisted, expected))


if __name__ == "__main__":
    unittest.main()

