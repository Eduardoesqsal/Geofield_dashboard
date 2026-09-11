"""Casos de uso para ROI y estadisticas espectrales."""

from __future__ import annotations

from typing import Any

import numpy as np

from geofield.application.ports import (
    RoiAnalysisRasterProcessor,
    RoiAnalysisRepository,
)


def normalize_roi_analysis_stats(stats: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(stats, dict):
        raise ValueError("Las estadisticas del ROI deben enviarse como objeto.")

    def numeric(name: str) -> float | None:
        value = stats.get(name)
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"El campo {name} no contiene un numero valido.") from exc
        if not np.isfinite(number):
            raise ValueError(f"El campo {name} debe ser un numero finito.")
        return number

    count = stats.get("count")
    try:
        normalized_count = int(count)
    except (TypeError, ValueError) as exc:
        raise ValueError("El campo count debe ser un entero valido.") from exc
    if normalized_count < 0:
        raise ValueError("El campo count no puede ser negativo.")

    return {
        "count": normalized_count,
        "min": numeric("min"),
        "max": numeric("max"),
        "mean": numeric("mean"),
        "median": numeric("median"),
        "standard_deviation": numeric("standard_deviation"),
        "p10": numeric("p10"),
        "p25": numeric("p25"),
        "p75": numeric("p75"),
        "p90": numeric("p90"),
        "range_min": numeric("range_min"),
        "range_max": numeric("range_max"),
    }


def roi_stats_match(
    persisted: dict[str, Any] | None,
    expected: dict[str, Any] | None,
) -> bool:
    if persisted is None or expected is None:
        return persisted is expected
    return normalize_roi_analysis_stats(persisted) == normalize_roi_analysis_stats(
        expected,
    )


class AnalyzeRoiUseCase:
    """Calcula estadisticas para un indice dentro de una geometria ROI."""

    def __init__(self, raster: RoiAnalysisRasterProcessor) -> None:
        self.raster = raster

    def execute(self, name: str, geometry: Any) -> dict[str, Any]:
        data = self.raster.roi_vegetation_index(geometry, name)
        matrix = np.asarray(data.get("matrix") or data.get("ndvi_matrix"), dtype=float)
        if name == "NDVI":
            matrix = matrix / 255 * 2 - 1
        mask_data = data.get("mask") or data.get("ndvi_mask")
        if mask_data is None:
            raise ValueError(f"{name} no devolvio una mascara valida.")
        mask = np.asarray(mask_data, dtype=bool)
        values = matrix[mask & np.isfinite(matrix)]
        return {
            "count": int(values.size),
            "min": float(values.min()) if values.size else None,
            "max": float(values.max()) if values.size else None,
            "mean": float(values.mean()) if values.size else None,
            "standard_deviation": float(values.std()) if values.size else None,
        }


class SaveRoiAnalysisUseCase:
    """Normaliza, calcula si hace falta y persiste estadisticas ROI."""

    def __init__(
        self,
        raster: RoiAnalysisRasterProcessor,
        analyses: RoiAnalysisRepository,
    ) -> None:
        self.analyze_roi = AnalyzeRoiUseCase(raster)
        self.analyses = analyses

    def execute(
        self,
        *,
        roi_id: str,
        orthomosaic_id: str,
        geometry: Any,
        selected_index: str | None = None,
        selected_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if selected_index and selected_stats:
            stats = normalize_roi_analysis_stats(selected_stats)
        else:
            if not selected_index:
                raise ValueError("Selecciona un indice antes de guardar estadisticas.")
            stats = self.analyze_roi.execute(selected_index, geometry)

        return self.analyses.save_roi_analysis(
            roi_id,
            orthomosaic_id,
            selected_index,
            stats,
        )
