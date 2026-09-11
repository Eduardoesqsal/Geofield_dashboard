"""Pruebas de casos de uso ROI."""

from __future__ import annotations

import unittest
from typing import Any

from geofield.application.use_cases import AnalyzeRoiUseCase, SaveRoiAnalysisUseCase


class FakeRoiRaster:
    def roi_vegetation_index(self, _geometry: Any, name: str) -> dict[str, Any]:
        if name == "NDVI":
            return {
                "matrix": [[0, 127.5, 255]],
                "mask": [[True, False, True]],
            }
        return {
            "matrix": [[-0.2, 0.4, 0.8]],
            "mask": [[True, True, False]],
        }


class FakeRoiAnalysisRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, dict[str, Any]]] = []

    def save_roi_analysis(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        self.saved.append((roi_id, orthomosaic_id, index_type, stats))
        return {
            "id": "analysis-1",
            "roi_id": roi_id,
            "orthomosaic_id": orthomosaic_id,
            index_type.lower(): stats,
        }


class RoiUseCaseTests(unittest.TestCase):
    def test_analyze_roi_converts_ndvi_byte_matrix_to_signed_domain(self) -> None:
        stats = AnalyzeRoiUseCase(FakeRoiRaster()).execute("NDVI", object())

        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["min"], -1.0)
        self.assertEqual(stats["max"], 1.0)
        self.assertEqual(stats["mean"], 0.0)

    def test_save_roi_analysis_uses_supplied_normalized_stats(self) -> None:
        repository = FakeRoiAnalysisRepository()
        result = SaveRoiAnalysisUseCase(FakeRoiRaster(), repository).execute(
            roi_id="roi-1",
            orthomosaic_id="flight-1",
            geometry=object(),
            selected_index="NDWI",
            selected_stats={
                "count": "2",
                "min": "-0.2",
                "max": "0.4",
                "mean": "0.1",
                "median": "0.1",
                "standard_deviation": "0.3",
            },
        )

        self.assertEqual(repository.saved[0][2], "NDWI")
        self.assertEqual(repository.saved[0][3]["count"], 2)
        self.assertEqual(result["ndwi"]["mean"], 0.1)

    def test_save_roi_analysis_calculates_stats_when_payload_stats_are_absent(self) -> None:
        repository = FakeRoiAnalysisRepository()

        SaveRoiAnalysisUseCase(FakeRoiRaster(), repository).execute(
            roi_id="roi-1",
            orthomosaic_id="flight-1",
            geometry=object(),
            selected_index="NDWI",
        )

        self.assertEqual(repository.saved[0][3]["count"], 2)
        self.assertEqual(repository.saved[0][3]["mean"], 0.1)


if __name__ == "__main__":
    unittest.main()

