"""Puertos de aplicacion.

Estos contratos describen lo que los casos de uso necesitan de la
infraestructura. Las implementaciones actuales siguen siendo los servicios
existentes; no cambia el almacenamiento ni la base de datos.
"""

from geofield.application.ports.artifact_storage import ArtifactStorage
from geofield.application.ports.job_queue import JobQueue
from geofield.application.ports.orthomosaic_repository import (
    OrthomosaicRepository,
    RasterState,
)
from geofield.application.ports.publication_repository import PublicationRepository
from geofield.application.ports.raster_processor import (
    ClassificationRasterProcessor,
    RoiAnalysisRasterProcessor,
)
from geofield.application.ports.roi_repository import RoiAnalysisRepository

__all__ = [
    "ArtifactStorage",
    "ClassificationRasterProcessor",
    "JobQueue",
    "OrthomosaicRepository",
    "PublicationRepository",
    "RasterState",
    "RoiAnalysisRasterProcessor",
    "RoiAnalysisRepository",
]
