"""Casos de uso para ortomosaicos.

El objetivo inicial es extraer coordinacion de alto nivel fuera de los
servicios concretos sin reescribir la infraestructura actual.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from geofield.application.ports import OrthomosaicRepository, RasterState


class ActivateOrthomosaicUseCase:
    """Activa un ortomosaico usando el gateway de persistencia actual."""

    def __init__(self, raster: RasterState, orthomosaics: OrthomosaicRepository) -> None:
        self.raster = raster
        self.orthomosaics = orthomosaics

    def execute(self, orthomosaic_id: str) -> dict[str, Any]:
        return self.orthomosaics.activate_orthomosaic(orthomosaic_id, self.raster)


class ResetActiveOrthomosaicUseCase:
    """Limpia el estado raster cuando se elimina el ortomosaico activo."""

    def __init__(self, raster: RasterState, orthomosaics: OrthomosaicRepository) -> None:
        self.raster = raster
        self.orthomosaics = orthomosaics

    def execute(self, record: dict[str, Any]) -> None:
        active_path = self.raster.active_path.resolve() if self.raster.active_path else None
        if not active_path:
            return

        file_path = record.get("file_path")
        if not file_path:
            return

        candidate_paths = {Path(str(file_path)).resolve()}
        original_filename = record.get("original_filename") or file_path
        suffix = Path(str(original_filename)).suffix or ".tif"
        candidate_paths.add(
            (self.orthomosaics.settings.cache_dir / f'{record["id"]}{suffix}').resolve(),
        )
        if active_path not in candidate_paths:
            return

        self.raster.active_path = None
        self.raster.sensor = None
        self.raster.rgb_stretch = None
        self.raster.overlay = None
        self.raster.crop_geometries.clear()


class DeleteOrthomosaicUseCase:
    """Elimina un ortomosaico y limpia el estado activo si corresponde."""

    def __init__(self, raster: RasterState, orthomosaics: OrthomosaicRepository) -> None:
        self.orthomosaics = orthomosaics
        self.reset_active = ResetActiveOrthomosaicUseCase(raster, orthomosaics)

    def execute(self, orthomosaic_id: str) -> dict[str, Any]:
        record = self.orthomosaics.get_orthomosaic(orthomosaic_id)
        self.reset_active.execute(record)
        self.orthomosaics.delete_orthomosaic(orthomosaic_id)
        return record


class DeleteAgriculturalCycleUseCase:
    """Elimina un ciclo y limpia cualquier ortomosaico activo que pertenezca a el."""

    def __init__(self, raster: RasterState, orthomosaics: OrthomosaicRepository) -> None:
        self.orthomosaics = orthomosaics
        self.reset_active = ResetActiveOrthomosaicUseCase(raster, orthomosaics)

    def execute(self, cycle_id: str) -> dict[str, Any]:
        for record in self.orthomosaics.list_orthomosaics(500, cycle_id):
            self.reset_active.execute(record)
        return self.orthomosaics.delete_agricultural_cycle(cycle_id)
