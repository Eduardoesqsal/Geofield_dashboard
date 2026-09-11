"""Contratos raster para la capa de aplicacion."""

from __future__ import annotations

from typing import Any, Protocol


class RoiAnalysisRasterProcessor(Protocol):
    def roi_vegetation_index(self, geometry: Any, name: str) -> dict[str, Any]:
        ...


class ClassificationRasterProcessor(Protocol):
    def ndvi_zoning_map(
        self,
        geom: Any,
        index_name: str = "NDVI",
        zone_count: int = 4,
        cell_size_m: float = 3.0,
        grid_angle_deg: float = 0.0,
        classification_method: str = "quantiles",
        cell_value_mode: str = "mean",
        manual_breaks: list[float] | tuple[float, ...] | None = None,
        detail_level: float = 1.0,
        analysis_min: float | None = None,
        analysis_max: float | None = None,
        context: Any | None = None,
    ) -> dict[str, Any]:
        ...

    def prescription_map_with_doses(
        self,
        geom: Any,
        index_name: str = "NDVI",
        zone_count: int = 4,
        cell_size_m: float = 3.0,
        grid_angle_deg: float = 0.0,
        classification_method: str = "quantiles",
        cell_value_mode: str = "mean",
        manual_breaks: list[float] | tuple[float, ...] | None = None,
        detail_level: float = 1.0,
        analysis_min: float | None = None,
        analysis_max: float | None = None,
        doses: list[float] | tuple[float, ...] | None = None,
        context: Any | None = None,
    ) -> dict[str, Any]:
        ...
