"""Casos de uso para zonificacion y prescripcion."""

from __future__ import annotations

from typing import Any

from geofield.application.ports import ClassificationRasterProcessor, JobQueue


class _InlineJobQueue:
    def run(self, name: str, handler: Any) -> Any:
        del name
        return handler()


class GenerateZoningUseCase:
    """Genera un mapa de zonificacion para un indice espectral."""

    def __init__(
        self,
        raster: ClassificationRasterProcessor,
        job_queue: JobQueue | None = None,
    ) -> None:
        self.raster = raster
        self.job_queue = job_queue or _InlineJobQueue()

    def execute(
        self,
        *,
        geometry: Any,
        index_name: str,
        zone_count: int,
        cell_size_m: float,
        grid_angle_deg: float,
        classification_method: str,
        cell_value_mode: str,
        manual_breaks: list[float] | tuple[float, ...] | None,
        detail_level: float,
        analysis_min: float | None,
        analysis_max: float | None,
    ) -> dict[str, Any]:
        return self.job_queue.run(
            "generate_zoning",
            lambda: self.raster.ndvi_zoning_map(
                geometry,
                index_name,
                zone_count,
                cell_size_m,
                grid_angle_deg,
                classification_method,
                cell_value_mode,
                manual_breaks,
                detail_level,
                analysis_min,
                analysis_max,
            ),
        )


class GeneratePrescriptionUseCase:
    """Genera un mapa de prescripcion con dosis opcionales por zona."""

    def __init__(
        self,
        raster: ClassificationRasterProcessor,
        job_queue: JobQueue | None = None,
    ) -> None:
        self.raster = raster
        self.job_queue = job_queue or _InlineJobQueue()

    def execute(
        self,
        *,
        geometry: Any,
        index_name: str,
        zone_count: int,
        cell_size_m: float,
        grid_angle_deg: float,
        classification_method: str,
        cell_value_mode: str,
        manual_breaks: list[float] | tuple[float, ...] | None,
        detail_level: float,
        analysis_min: float | None,
        analysis_max: float | None,
        doses: list[float] | tuple[float, ...] | None,
    ) -> dict[str, Any]:
        return self.job_queue.run(
            "generate_prescription",
            lambda: self.raster.prescription_map_with_doses(
                geometry,
                index_name,
                zone_count,
                cell_size_m,
                grid_angle_deg,
                classification_method,
                cell_value_mode,
                manual_breaks,
                detail_level,
                analysis_min,
                analysis_max,
                doses,
            ),
        )
