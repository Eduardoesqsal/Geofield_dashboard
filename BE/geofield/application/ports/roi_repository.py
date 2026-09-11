"""Contratos de persistencia para analisis ROI."""

from __future__ import annotations

from typing import Any, Protocol


class RoiAnalysisRepository(Protocol):
    def save_roi_analysis(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        ...

