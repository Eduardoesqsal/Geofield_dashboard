"""Modelos de payload para rutas HTTP del backend."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ClassificationPayload(BaseModel):
    """Payload compartido por zonificacion y prescripcion."""

    orthomosaic_id: str
    geojson: Any | None = None
    index_name: str = "NDVI"
    zone_count: int = 4
    cell_size_m: float = 3.0
    grid_angle_deg: float = 0.0
    classification_method: str = "quantiles"
    cell_value_mode: str = "mean"
    manual_breaks: list[float] | None = None
    detail_level: float = 1.0
    analysis_min: float | None = None
    analysis_max: float | None = None


class PrescriptionPayload(ClassificationPayload):
    """Payload de prescripcion con dosis opcionales por zona."""

    doses: list[float] | None = None
