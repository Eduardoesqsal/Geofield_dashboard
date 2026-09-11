"""Pruebas de casos de uso de zonificacion y prescripcion."""

from __future__ import annotations

import unittest
from typing import Any

from geofield.application.use_cases import GeneratePrescriptionUseCase, GenerateZoningUseCase


class FakeClassificationRaster:
    def __init__(self) -> None:
        self.zoning_call: tuple[Any, ...] | None = None
        self.prescription_call: tuple[Any, ...] | None = None

    def ndvi_zoning_map(self, *args: Any) -> dict[str, Any]:
        self.zoning_call = args
        return {"status": "ok", "stage": "zoning"}

    def prescription_map_with_doses(self, *args: Any) -> dict[str, Any]:
        self.prescription_call = args
        return {"status": "ok", "stage": "prescription"}


class RecordingJobQueue:
    def __init__(self) -> None:
        self.names: list[str] = []

    def run(self, name: str, handler: Any) -> Any:
        self.names.append(name)
        return handler()


class ClassificationUseCaseTests(unittest.TestCase):
    def test_generate_zoning_delegates_full_contract_to_raster(self) -> None:
        raster = FakeClassificationRaster()
        geometry = object()

        result = GenerateZoningUseCase(raster).execute(
            geometry=geometry,
            index_name="NDRE",
            zone_count=5,
            cell_size_m=4.0,
            grid_angle_deg=12.0,
            classification_method="quantiles",
            cell_value_mode="mean",
            manual_breaks=[0.1, 0.2],
            detail_level=0.5,
            analysis_min=0.0,
            analysis_max=0.9,
        )

        self.assertEqual(result["stage"], "zoning")
        self.assertEqual(
            raster.zoning_call,
            (geometry, "NDRE", 5, 4.0, 12.0, "quantiles", "mean", [0.1, 0.2], 0.5, 0.0, 0.9),
        )

    def test_generate_prescription_delegates_doses_to_raster(self) -> None:
        raster = FakeClassificationRaster()
        geometry = object()

        result = GeneratePrescriptionUseCase(raster).execute(
            geometry=geometry,
            index_name="NDVI",
            zone_count=4,
            cell_size_m=3.0,
            grid_angle_deg=0.0,
            classification_method="manual",
            cell_value_mode="max",
            manual_breaks=[0.1, 0.2, 0.3],
            detail_level=1.0,
            analysis_min=0.1,
            analysis_max=0.8,
            doses=[10, 20, 30, 40],
        )

        self.assertEqual(result["stage"], "prescription")
        self.assertEqual(
            raster.prescription_call,
            (
                geometry,
                "NDVI",
                4,
                3.0,
                0.0,
                "manual",
                "max",
                [0.1, 0.2, 0.3],
                1.0,
                0.1,
                0.8,
                [10, 20, 30, 40],
            ),
        )

    def test_generation_runs_through_job_queue_port(self) -> None:
        raster = FakeClassificationRaster()
        jobs = RecordingJobQueue()

        result = GenerateZoningUseCase(raster, jobs).execute(
            geometry=object(),
            index_name="NDVI",
            zone_count=4,
            cell_size_m=3.0,
            grid_angle_deg=0.0,
            classification_method="quantiles",
            cell_value_mode="mean",
            manual_breaks=None,
            detail_level=1.0,
            analysis_min=None,
            analysis_max=None,
        )

        self.assertEqual(result["stage"], "zoning")
        self.assertEqual(jobs.names, ["generate_zoning"])


if __name__ == "__main__":
    unittest.main()
