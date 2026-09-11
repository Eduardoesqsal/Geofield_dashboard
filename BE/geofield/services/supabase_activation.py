"""Adaptador de persistencia hacia Supabase.

Aquí se centraliza la conexión, lectura y escritura de ortomosaicos, zonas,
ROI y estadísticas históricas consumidas por el dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from postgrest import ReturnMethod
from rasterio.io import MemoryFile
from rasterio.warp import transform_bounds
from shapely.geometry import box, shape
from supabase import Client, create_client

from geofield.config import Settings
from geofield.errors import (
    OrthomosaicNotFoundError,
    RoiAnalysisNotFoundError,
    SupabaseNotConfiguredError,
)
from geofield.services.raster_service import RasterContext, RasterService



class SupabaseActivationMixin:
    """Activacion de ortomosaicos sobre el motor raster."""

    def activate_orthomosaic_record(
        self,
        record: dict[str, Any],
        raster_service: RasterService,
    ) -> dict[str, Any]:
        orthomosaic_id = str(record["id"])
        if self.uses_local_storage:
            local_path = Path(record["file_path"]).resolve()
            if not local_path.is_file():
                raise FileNotFoundError(
                    f"No existe el archivo local del ortomosaico: {local_path}",
                )
        else:
            suffix = (
                Path(record.get("original_filename") or record["file_path"]).suffix
                or ".tif"
            )
            local_path = self.settings.cache_dir / f"{orthomosaic_id}{suffix}"
            if not local_path.is_file():
                client = self.require_client()
                content = client.storage.from_(
                    self.settings.supabase_bucket,
                ).download(record["file_path"])
                local_path.write_bytes(content)
        raster_service.validate_path(local_path)
        raster_service.set_active_context(
            RasterContext(
                path=local_path,
                sensor=record.get("sensor_type"),
                orthomosaic_id=orthomosaic_id,
            ),
        )
        raster_service.rgb_stretch = None
        raster_service.overlay = None
        return record
    
    def activate_orthomosaic(
        self,
        orthomosaic_id: str,
        raster_service: RasterService,
    ) -> dict[str, Any]:
        return self.activate_orthomosaic_record(
            self.get_orthomosaic(orthomosaic_id),
            raster_service,
        )
    
