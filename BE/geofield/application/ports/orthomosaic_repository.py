"""Contratos de ortomosaicos para la capa de aplicacion."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class RasterState(Protocol):
    active_path: Path | None
    sensor: str | None
    rgb_stretch: Any
    overlay: Any
    crop_geometries: dict[str, Any]


class OrthomosaicRepository(Protocol):
    settings: Any

    def activate_orthomosaic(
        self,
        orthomosaic_id: str,
        raster: RasterState,
    ) -> dict[str, Any]:
        ...

    def get_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        ...

    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        ...

    def list_orthomosaics(
        self,
        limit: int = 100,
        agricultural_cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        ...

