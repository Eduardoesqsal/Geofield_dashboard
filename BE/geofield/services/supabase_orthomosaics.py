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
from geofield.services.raster_service import RasterService



class SupabaseOrthomosaicMixin:
    """CRUD de ciclos agricolas y ortomosaicos."""

    def _storage_path(self, capture_date: date, filename: str) -> str:
        return (
            f"{capture_date.isoformat()}/"
            f"{uuid4().hex}_{self._safe_filename(filename)}"
        )
    
    def _local_path(self, capture_date: date, filename: str) -> Path:
        local_dir = self.settings.uploads_dir / capture_date.isoformat()
        local_dir.mkdir(parents=True, exist_ok=True)
        return local_dir / f"{uuid4().hex}_{self._safe_filename(filename)}"
    
    def upload_orthomosaic(
        self,
        *,
        content: bytes,
        filename: str,
        agricultural_cycle_id: str,
        capture_date: date,
        sensor_type: str,
        name: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        self.require_client()
        metadata = self._metadata_from_bytes(content)
        orthomosaic_id = str(uuid4())
        if self.uses_local_storage:
            local_path = self._local_path(capture_date, filename)
            local_path.write_bytes(content)
            file_path = str(local_path.resolve())
        else:
            storage_path = self._storage_path(capture_date, filename)
            self._upload_orthomosaic_object(
                storage_path,
                content,
                content_type,
            )
            file_path = storage_path
        payload = {
            "id": orthomosaic_id,
            "agricultural_cycle_id": agricultural_cycle_id,
            "name": (name or Path(filename).stem).strip() or Path(filename).stem,
            "original_filename": filename,
            "capture_date": capture_date.isoformat(),
            "sensor_type": sensor_type,
            "file_path": file_path,
            "bounds": metadata.bounds_wkt,
            "raster_crs": metadata.raster_crs,
            "width_px": metadata.width_px,
            "height_px": metadata.height_px,
            "bands_count": metadata.bands_count,
            "file_size_bytes": metadata.file_size_bytes,
            "upload_status": "uploaded",
        }
        response = self._upsert_orthomosaic_record(payload)
        data = self._payload_data(response)
        return data[0] if isinstance(data, list) else data
    
    def list_agricultural_cycles(self, limit: int = 100) -> list[dict[str, Any]]:
        client = self.require_client()
        response = (
            client.table("agricultural_cycles")
            .select("id,name,crop_name,start_date,end_date,notes,created_at")
            .order("start_date", desc=True)
            .limit(limit)
            .execute()
        )
        data = self._payload_data(response)
        return list(data or [])
    
    def create_agricultural_cycle(
        self,
        *,
        name: str,
        crop_name: str | None,
        start_date: date,
        end_date: date | None,
        notes: str | None,
    ) -> dict[str, Any]:
        response = (
            self.require_client()
            .table("agricultural_cycles")
            .insert(
                {
                    "name": name,
                    "crop_name": crop_name,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat() if end_date else None,
                    "notes": notes,
                },
            )
            .execute()
        )
        data = self._payload_data(response)
        return data[0] if isinstance(data, list) else data
    
    def update_agricultural_cycle(
        self,
        cycle_id: str,
        *,
        name: str,
    ) -> dict[str, Any]:
        response = (
            self.require_client()
            .table("agricultural_cycles")
            .update({"name": name})
            .eq("id", cycle_id)
            .select("id,name,crop_name,start_date,end_date,notes,created_at")
            .execute()
        )
        data = self._payload_data(response) or []
        if not data:
            raise OrthomosaicNotFoundError(
                f"No existe el ciclo agricola {cycle_id}.",
            )
        return data[0]
    
    def delete_agricultural_cycle(self, cycle_id: str) -> dict[str, Any]:
        client = self.require_client()
        response = (
            client.table("agricultural_cycles")
            .select("id,name,crop_name,start_date,end_date,notes,created_at")
            .eq("id", cycle_id)
            .limit(1)
            .execute()
        )
        cycles = list(self._payload_data(response) or [])
        if not cycles:
            raise OrthomosaicNotFoundError(
                f"No existe el ciclo agricola {cycle_id}.",
            )
    
        rois = self.list_rois(cycle_id)
        # Los análisis asociados se eliminan mediante sus relaciones cascade.
        client.table("rois").delete().eq(
            "agricultural_cycle_id",
            cycle_id,
        ).execute()
    
        orthomosaics = self.list_orthomosaics(500, cycle_id)
        for orthomosaic in orthomosaics:
            self.delete_orthomosaic(str(orthomosaic["id"]))
    
        deleted = (
            client.table("agricultural_cycles")
            .delete()
            .eq("id", cycle_id)
            .execute()
        )
        if not self._payload_data(deleted):
            raise OrthomosaicNotFoundError(
                f"No se pudo confirmar la eliminación del ciclo {cycle_id}.",
            )
        return {
            "cycle": cycles[0],
            "orthomosaics": orthomosaics,
            "deleted_orthomosaics": len(orthomosaics),
            "deleted_rois": len(rois),
        }
    
    def list_orthomosaics(
        self,
        limit: int = 100,
        agricultural_cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        client = self.require_client()
        columns = (
            "id,name,original_filename,capture_date,sensor_type,file_path,"
            "upload_status,created_at,agricultural_cycle_id"
        )
    
        def build_query(*, include_display_order: bool) -> Any:
            selected_columns = (
                f"{columns},display_order" if include_display_order else columns
            )
            query = client.table("orthomosaics").select(selected_columns)
            if include_display_order:
                query = query.order(
                    "display_order",
                    desc=False,
                    nullsfirst=False,
                )
            query = query.order("capture_date", desc=True).limit(limit)
            if agricultural_cycle_id:
                query = query.eq(
                    "agricultural_cycle_id",
                    agricultural_cycle_id,
                )
            return query
    
        try:
            response = build_query(include_display_order=True).execute()
        except Exception as exc:
            if "display_order" not in str(exc).lower():
                raise
            response = build_query(include_display_order=False).execute()
        data = self._payload_data(response)
        return list(data or [])
    
    def reorder_orthomosaics(
        self,
        agricultural_cycle_id: str,
        orthomosaic_ids: list[str],
    ) -> list[dict[str, Any]]:
        current = self.list_orthomosaics(500, agricultural_cycle_id)
        current_ids = [str(item.get("id") or "") for item in current]
        if len(orthomosaic_ids) != len(set(orthomosaic_ids)):
            raise ValueError("El orden contiene vuelos duplicados.")
        if set(orthomosaic_ids) != set(current_ids):
            raise ValueError(
                "El orden debe incluir exactamente todos los ortomosaicos del ciclo.",
            )
    
        client = self.require_client()
        by_id = {str(item["id"]): item for item in current}
        ordered: list[dict[str, Any]] = []
        for position, orthomosaic_id in enumerate(orthomosaic_ids):
            try:
                response = (
                    client.table("orthomosaics")
                    .update({"display_order": position})
                    .eq("id", orthomosaic_id)
                    .eq("agricultural_cycle_id", agricultural_cycle_id)
                    .execute()
                )
            except Exception as exc:
                if "display_order" in str(exc).lower():
                    raise RuntimeError(
                        "Falta preparar el orden de vuelos en Supabase. "
                        "Ejecuta BE/sql/005_add_orthomosaic_display_order.sql.",
                    ) from exc
                raise
            if not self._payload_data(response):
                raise OrthomosaicNotFoundError(
                    f"No existe el ortomosaico {orthomosaic_id} en este ciclo.",
                )
            ordered.append({**by_id[orthomosaic_id], "display_order": position})
        return ordered
    
    def healthcheck(self) -> dict[str, Any]:
        client = self.require_client()
        response = (
            client.table("orthomosaics")
            .select("id", count="exact")
            .limit(1)
            .execute()
        )
        data = self._payload_data(response) or []
        count = getattr(response, "count", None)
        return {"reachable": True, "rows_sampled": len(data), "count": count}
    
    def get_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        client = self.require_client()
        response = (
            client.table("orthomosaics")
            .select("*")
            .eq("id", orthomosaic_id)
            .limit(1)
            .execute()
        )
        data = self._payload_data(response) or []
        if not data:
            raise OrthomosaicNotFoundError(
                f"No existe el ortomosaico {orthomosaic_id}.",
            )
        return data[0]
    
    def delete_orthomosaic(self, orthomosaic_id: str) -> dict[str, Any]:
        record = self.get_orthomosaic(orthomosaic_id)
        if self.uses_local_storage:
            local_path = Path(record["file_path"]).resolve()
            uploads_root = self.settings.uploads_dir.resolve()
            try:
                local_path.relative_to(uploads_root)
            except ValueError as exc:
                raise ValueError(
                    "La ruta del ortomosaico no pertenece al almacenamiento local.",
                ) from exc
            local_path.unlink(missing_ok=True)
        else:
            self.require_client().storage.from_(self.settings.supabase_bucket).remove(
                [record["file_path"]],
            )
        self.require_client().table("orthomosaics").delete().eq(
            "id",
            orthomosaic_id,
        ).execute()
        return record
    
    def update_orthomosaic_capture_date(
        self,
        orthomosaic_id: str,
        capture_date: date,
    ) -> dict[str, Any]:
        client = self.require_client()
        response = (
            client.table("orthomosaics")
            .update({"capture_date": capture_date.isoformat()})
            .eq("id", orthomosaic_id)
            .select(
                "id,name,original_filename,capture_date,sensor_type,file_path,upload_status,created_at,agricultural_cycle_id,display_order",
            )
            .limit(1)
            .execute()
        )
        data = self._payload_data(response) or []
        if not data:
            raise OrthomosaicNotFoundError(
                f"No existe el ortomosaico {orthomosaic_id}.",
            )
        return data[0]
    