"""Casos de uso de aplicacion."""

from geofield.application.use_cases.artifacts import PublishJsonArtifactUseCase
from geofield.application.use_cases.orthomosaic import (
    ActivateOrthomosaicUseCase,
    DeleteAgriculturalCycleUseCase,
    DeleteOrthomosaicUseCase,
    ResetActiveOrthomosaicUseCase,
)
from geofield.application.use_cases.prescription import (
    GeneratePrescriptionUseCase,
    GenerateZoningUseCase,
)
from geofield.application.use_cases.roi import (
    AnalyzeRoiUseCase,
    SaveRoiAnalysisUseCase,
    normalize_roi_analysis_stats,
    roi_stats_match,
)

__all__ = [
    "ActivateOrthomosaicUseCase",
    "AnalyzeRoiUseCase",
    "DeleteAgriculturalCycleUseCase",
    "DeleteOrthomosaicUseCase",
    "GeneratePrescriptionUseCase",
    "GenerateZoningUseCase",
    "PublishJsonArtifactUseCase",
    "ResetActiveOrthomosaicUseCase",
    "SaveRoiAnalysisUseCase",
    "normalize_roi_analysis_stats",
    "roi_stats_match",
]
