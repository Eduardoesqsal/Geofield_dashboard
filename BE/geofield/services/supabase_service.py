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


@dataclass(frozen=True)
class RasterMetadata:
    bounds_wkt: str
    raster_crs: str | None
    width_px: int
    height_px: int
    bands_count: int
    file_size_bytes: int


class SupabaseService:
    INDEX_RESULT_LEGACY_COLUMNS = (
        "id,roi_id,orthomosaic_id,index_type,avg_value,min_value,max_value,"
        "stddev,p10,p25,p50,p75,p90,pixel_count,range_min,range_max,"
        "created_at,orthomosaics(name,capture_date)"
    )
    INDEX_RESULT_MODERN_COLUMNS = (
        "id,zone_id,orthomosaic_id,index_type,avg_value,min_value,max_value,"
        "stddev,p10,p25,p50,p75,p90,pixel_count,result_meta,calculated_at,"
        "orthomosaics(name,capture_date)"
    )
    ROI_ANALYSES_COLUMNS = (
        "id,roi_id,orthomosaic_id,ndvi,ndwi,ndre,created_at,"
        "orthomosaics(name,capture_date)"
    )
    ZONE_COLUMNS = "id,name,geom,source_format,properties,created_at,roi_id"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client: Client | None = None
        if settings.supabase_url and settings.supabase_service_role_key:
            self.client = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key,
            )

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @property
    def uses_local_storage(self) -> bool:
        return self.settings.orthomosaic_storage_mode != "supabase"

    def require_client(self) -> Client:
        if not self.client:
            raise SupabaseNotConfiguredError(
                "Supabase no esta configurado. Define SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY.",
            )
        return self.client

    def _reconnect_client(self) -> Client:
        """Recrea el cliente para descartar conexiones HTTP persistentes rotas."""
        if not self.settings.supabase_url or not self.settings.supabase_service_role_key:
            raise SupabaseNotConfiguredError(
                "Supabase no esta configurado. Define SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY.",
            )
        self.client = create_client(
            self.settings.supabase_url,
            self.settings.supabase_service_role_key,
        )
        return self.client

    def _upsert_orthomosaic_record(
        self,
        payload: dict[str, Any],
    ) -> Any:
        """Inserta de forma idempotente y renueva conexiones HTTP rotas."""
        client = self.require_client()
        for attempt in range(3):
            try:
                (
                    client.table("orthomosaics")
                    .upsert(
                        payload,
                        on_conflict="id",
                        returning=ReturnMethod.minimal,
                    )
                    .execute()
                )
                # El payload ya contiene todos los campos usados para activar
                # el raster. No dependemos de volver a leer la representación.
                return payload
            except httpx.TransportError as transport_error:
                if attempt == 2:
                    raise transport_error
                client = self._reconnect_client()
                try:
                    verification = (
                        client.table("orthomosaics")
                        .select("id")
                        .eq("id", payload["id"])
                        .limit(1)
                        .execute()
                    )
                    if self._payload_data(verification):
                        return payload
                except httpx.TransportError:
                    client = self._reconnect_client()
        raise RuntimeError("No se pudo guardar el registro del ortomosaico.")

    def _upload_orthomosaic_object(
        self,
        storage_path: str,
        content: bytes,
        content_type: str | None,
    ) -> None:
        """Sube al bucket con una ruta única y reintentos seguros."""
        client = self.require_client()
        options = {
            "content-type": content_type or "image/tiff",
            # La ruta contiene UUID. Upsert permite repetir la operación si
            # Supabase guardó el archivo pero se perdió la respuesta HTTP.
            "upsert": "true",
        }
        for attempt in range(3):
            try:
                client.storage.from_(self.settings.supabase_bucket).upload(
                    storage_path,
                    content,
                    options,
                )
                return
            except httpx.TransportError:
                if attempt == 2:
                    raise
                client = self._reconnect_client()

    @staticmethod
    def _safe_filename(filename: str) -> str:
        sanitized = "".join(
            character
            if character.isalnum() or character in {".", "-", "_"}
            else "_"
            for character in filename
        )
        return sanitized or "upload.tif"

    @staticmethod
    def _payload_data(result: Any) -> Any:
        return getattr(result, "data", result)

    @staticmethod
    def _metadata_from_bytes(content: bytes) -> RasterMetadata:
        with MemoryFile(content) as memory_file:
            with memory_file.open() as src:
                if src.crs:
                    projected_bounds = transform_bounds(
                        src.crs,
                        "EPSG:4326",
                        *src.bounds,
                        densify_pts=21,
                    )
                else:
                    projected_bounds = src.bounds
                polygon = box(*projected_bounds)
                return RasterMetadata(
                    bounds_wkt=f"SRID=4326;{polygon.wkt}",
                    raster_crs=src.crs.to_string() if src.crs else None,
                    width_px=src.width,
                    height_px=src.height,
                    bands_count=src.count,
                    file_size_bytes=len(content),
                )

    @staticmethod
    def _stats_from_index_result(row: dict[str, Any]) -> dict[str, Any]:
        result_meta = row.get("result_meta") if isinstance(row.get("result_meta"), dict) else {}
        saved_stats = (
            result_meta.get("saved_stats")
            if isinstance(result_meta.get("saved_stats"), dict)
            else None
        )
        if saved_stats:
            return {
                "count": int(saved_stats.get("count") or 0),
                "min": saved_stats.get("min"),
                "max": saved_stats.get("max"),
                "mean": saved_stats.get("mean"),
                "median": saved_stats.get("median"),
                "standard_deviation": saved_stats.get("standard_deviation"),
                "p10": saved_stats.get("p10"),
                "p25": saved_stats.get("p25"),
                "p75": saved_stats.get("p75"),
                "p90": saved_stats.get("p90"),
                "range_min": saved_stats.get("range_min"),
                "range_max": saved_stats.get("range_max"),
            }
        return {
            "count": int(row.get("pixel_count") or 0),
            "min": row.get("min_value"),
            "max": row.get("max_value"),
            "mean": row.get("avg_value"),
            "median": row.get("p50"),
            "standard_deviation": row.get("stddev"),
            "p10": row.get("p10"),
            "p25": row.get("p25"),
            "p75": row.get("p75"),
            "p90": row.get("p90"),
            "range_min": row.get("range_min", result_meta.get("range_min")),
            "range_max": row.get("range_max", result_meta.get("range_max")),
        }

    @classmethod
    def _index_result_to_roi_analysis(cls, row: dict[str, Any]) -> dict[str, Any]:
        index_type = str(row.get("index_type") or "").upper()
        stats = cls._stats_from_index_result(row)
        result_meta = row.get("result_meta") if isinstance(row.get("result_meta"), dict) else {}
        return {
            "id": row["id"],
            "roi_id": row.get("roi_id") or result_meta.get("roi_id") or row.get("zone_id"),
            "orthomosaic_id": row["orthomosaic_id"],
            "ndvi": stats if index_type == "NDVI" else None,
            "ndwi": stats if index_type == "NDWI" else None,
            "ndre": stats if index_type == "NDRE" else None,
            "created_at": row.get("created_at") or row.get("calculated_at"),
            "orthomosaics": row.get("orthomosaics"),
        }

    @staticmethod
    def _is_saved_roi_stats(value: Any) -> bool:
        return isinstance(value, dict) and any(
            key in value
            for key in (
                "count",
                "min",
                "max",
                "mean",
                "median",
                "standard_deviation",
                "p10",
                "p25",
                "p75",
                "p90",
                "range_min",
                "range_max",
            )
        )

    @staticmethod
    def _roi_analyses_record_id(row_id: str, index_type: str) -> str:
        return f"roi_analyses:{row_id}:{index_type.upper()}"

    @staticmethod
    def _parse_roi_analyses_record_id(analysis_id: str) -> tuple[str, str] | None:
        parts = analysis_id.split(":")
        if len(parts) != 3 or parts[0] != "roi_analyses":
            return None
        row_id, index_type = parts[1], parts[2].upper()
        if index_type not in {"NDVI", "NDWI", "NDRE"}:
            return None
        return row_id, index_type

    @classmethod
    def _roi_analyses_row_to_analyses(
        cls,
        row: dict[str, Any],
        index: str | None = None,
    ) -> list[dict[str, Any]]:
        selected = index.upper() if index else None
        analyses: list[dict[str, Any]] = []
        for index_type in ("NDVI", "NDWI", "NDRE"):
            if selected and index_type != selected:
                continue
            stats = row.get(index_type.lower())
            if not cls._is_saved_roi_stats(stats):
                continue
            analyses.append(
                {
                    "id": cls._roi_analyses_record_id(str(row["id"]), index_type),
                    "roi_id": row["roi_id"],
                    "orthomosaic_id": row["orthomosaic_id"],
                    "ndvi": stats if index_type == "NDVI" else None,
                    "ndwi": stats if index_type == "NDWI" else None,
                    "ndre": stats if index_type == "NDRE" else None,
                    "created_at": row.get("created_at"),
                    "orthomosaics": row.get("orthomosaics"),
                },
            )
        return analyses

    def _get_roi_analyses_row(
        self,
        roi_id: str,
        orthomosaic_id: str,
    ) -> dict[str, Any] | None:
        response = (
            self.require_client()
            .table("roi_analyses")
            .select(self.ROI_ANALYSES_COLUMNS)
            .eq("roi_id", roi_id)
            .eq("orthomosaic_id", orthomosaic_id)
            .limit(1)
            .execute()
        )
        data = self._payload_data(response) or []
        return data[0] if data else None

    def _save_roi_analysis_row(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        client = self.require_client()
        field = index_type.lower()
        existing = self._get_roi_analyses_row(roi_id, orthomosaic_id)
        payload: dict[str, Any] = {field: stats}
        if existing:
            mutation = (
                client.table("roi_analyses")
                .update(payload)
                .eq("id", existing["id"])
                .select(self.ROI_ANALYSES_COLUMNS)
                .execute()
            )
        else:
            payload.update(
                {
                    "roi_id": roi_id,
                    "orthomosaic_id": orthomosaic_id,
                    # El esquema legado exige ndvi not null incluso si el
                    # analisis inicial corresponde a otro indice.
                    "ndvi": stats if index_type == "NDVI" else {},
                },
            )
            mutation = (
                client.table("roi_analyses")
                .insert(payload)
                .select(self.ROI_ANALYSES_COLUMNS)
                .execute()
            )
        mutation_data = self._payload_data(mutation) or []
        row = mutation_data[0] if isinstance(mutation_data, list) and mutation_data else mutation_data
        analyses = self._roi_analyses_row_to_analyses(row, index_type)
        if analyses:
            return analyses[0]
        raise RoiAnalysisNotFoundError(
            "No se pudo recuperar la estadistica recien guardada.",
        )

    @staticmethod
    def _latest_index_results_per_flight(
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Conserva una medición por ROI, vuelo e índice, priorizando la más nueva."""
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (
                str(row.get("orthomosaic_id") or ""),
                str(row.get("index_type") or "").upper(),
            )
            timestamp = str(row.get("calculated_at") or row.get("created_at") or "")
            current = latest.get(key)
            current_timestamp = (
                str(
                    current.get("calculated_at")
                    or current.get("created_at")
                    or ""
                )
                if current
                else ""
            )
            if current is None or timestamp > current_timestamp:
                latest[key] = row
        return list(latest.values())

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

    def create_roi(
        self,
        name: str,
        geojson: dict[str, Any],
        orthomosaic_id: str | None,
        agricultural_cycle_id: str | None,
    ) -> dict[str, Any]:
        cycle_id = agricultural_cycle_id
        if not cycle_id and orthomosaic_id:
            cycle_id = self.get_orthomosaic(orthomosaic_id).get(
                "agricultural_cycle_id",
            )
        response = self.require_client().table("rois").insert(
            {
                "name": name,
                "geojson": geojson,
                "orthomosaic_id": orthomosaic_id,
                "agricultural_cycle_id": cycle_id,
            },
        ).execute()
        data = self._payload_data(response)
        return data[0] if isinstance(data, list) else data

    def ensure_zone_for_roi(self, roi_id: str) -> dict[str, Any]:
        roi = self.get_roi(roi_id)
        client = self.require_client()
        for query_builder in (
            lambda: (
                client.table("zones")
                .select(self.ZONE_COLUMNS)
                .eq("roi_id", roi_id)
                .limit(1)
            ),
            lambda: (
                client.table("zones")
                .select("id,name,geom,source_format,properties,created_at")
                .contains("properties", {"roi_id": roi_id})
                .limit(1)
            ),
        ):
            try:
                response = query_builder().execute()
                data = list(self._payload_data(response) or [])
                if data:
                    return data[0]
            except Exception:
                continue

        geometry = shape(roi["geojson"]["geometry"] if roi["geojson"].get("type") == "Feature" else roi["geojson"])
        zone_payload = {
            "name": roi.get("name") or "ROI",
            "geom": f"SRID=4326;{geometry.wkt}",
            "roi_id": roi_id,
            "properties": {
                "roi_id": roi_id,
                "orthomosaic_id": roi.get("orthomosaic_id"),
            },
        }
        source_format_candidates = [None, "manual", "drawn", "polygon", "roi"]
        errors: list[str] = []
        for source_format in source_format_candidates:
            payload = dict(zone_payload)
            if source_format is not None:
                payload["source_format"] = source_format

            attempts = [payload]
            legacy_payload = dict(payload)
            legacy_payload.pop("roi_id", None)
            if legacy_payload != payload:
                attempts.append(legacy_payload)

            label = source_format if source_format is not None else "<omitido>"
            for attempt_index, candidate_payload in enumerate(attempts):
                try:
                    response = client.table("zones").insert(candidate_payload).execute()
                    data = self._payload_data(response)
                    if isinstance(data, list) and data:
                        return data[0]
                    if isinstance(data, dict):
                        return data
                except Exception as exc:
                    message = str(exc)
                    missing_roi_id_column = (
                        attempt_index == 0
                        and "roi_id" in candidate_payload
                        and "roi_id" in message
                        and "zones" in message
                    )
                    if missing_roi_id_column and len(attempts) > 1:
                        continue
                    errors.append(f"{label}: {exc}")
                    break
        raise RoiAnalysisNotFoundError(
            "No se pudo crear la zona asociada al ROI. "
            + " | ".join(errors),
        )

    def list_rois(self, agricultural_cycle_id: str | None = None) -> list[dict[str, Any]]:
        client = self.require_client()
        if agricultural_cycle_id:
            columns = (
                "id,name,geojson,orthomosaic_id,agricultural_cycle_id,is_active,created_at"
            )
            response = (
                client.table("rois")
                .select(columns)
                .eq("agricultural_cycle_id", agricultural_cycle_id)
                .order("created_at", desc=True)
                .execute()
            )
            records = {
                item["id"]: item for item in list(self._payload_data(response) or [])
            }

            # Compatibilidad con ROI creados antes de incorporar ciclos: los
            # vinculados a un vuelo se resuelven mediante el ciclo del vuelo.
            orthomosaics = self.list_orthomosaics(500, agricultural_cycle_id)
            orthomosaic_ids = [item["id"] for item in orthomosaics]
            if orthomosaic_ids:
                response = (
                    client.table("rois")
                    .select(columns)
                    .in_("orthomosaic_id", orthomosaic_ids)
                    .order("created_at", desc=True)
                    .execute()
                )
                for item in list(self._payload_data(response) or []):
                    records[item["id"]] = item

            # Una versión anterior del listener de dibujo podía guardar ambos
            # vínculos como null. Esas geometrías son globales y deben seguir
            # disponibles para reutilizarse en cualquier vuelo.
            response = (
                client.table("rois")
                .select(columns)
                .is_("agricultural_cycle_id", "null")
                .is_("orthomosaic_id", "null")
                .order("created_at", desc=True)
                .execute()
            )
            for item in list(self._payload_data(response) or []):
                records[item["id"]] = item

            return sorted(
                records.values(),
                key=lambda item: str(item.get("created_at") or ""),
                reverse=True,
            )
        response = (
            client.table("rois")
            .select(
                "id,name,geojson,orthomosaic_id,agricultural_cycle_id,is_active,created_at",
            )
            .order("created_at", desc=True)
            .execute()
        )
        return list(self._payload_data(response) or [])

    def get_roi(self, roi_id: str) -> dict[str, Any]:
        response = (
            self.require_client()
            .table("rois")
            .select("*")
            .eq("id", roi_id)
            .limit(1)
            .execute()
        )
        data = self._payload_data(response) or []
        if not data:
            raise OrthomosaicNotFoundError("No existe el ROI.")
        return data[0]

    def get_index_result(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
    ) -> dict[str, Any] | None:
        client = self.require_client()
        try:
            response = (
                client.table("index_results")
                .select(self.INDEX_RESULT_MODERN_COLUMNS)
                .contains("result_meta", {"roi_id": roi_id})
                .eq("orthomosaic_id", orthomosaic_id)
                .eq("index_type", index_type)
                .order("calculated_at", desc=True)
                .limit(1)
                .execute()
            )
            data = self._payload_data(response) or []
            if data:
                return data[0]
        except Exception:
            pass

        response = (
            client.table("index_results")
            .select(self.INDEX_RESULT_LEGACY_COLUMNS)
            .eq("roi_id", roi_id)
            .eq("orthomosaic_id", orthomosaic_id)
            .eq("index_type", index_type)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        data = self._payload_data(response) or []
        return data[0] if data else None

    def get_index_result_by_zone(
        self,
        zone_id: str,
        orthomosaic_id: str,
        index_type: str,
    ) -> dict[str, Any] | None:
        response = (
            self.require_client()
            .table("index_results")
            .select(self.INDEX_RESULT_MODERN_COLUMNS)
            .eq("zone_id", zone_id)
            .eq("orthomosaic_id", orthomosaic_id)
            .eq("index_type", index_type)
            .order("calculated_at", desc=True)
            .limit(1)
            .execute()
        )
        data = self._payload_data(response) or []
        return data[0] if data else None

    def get_index_result_by_id(self, result_id: str) -> dict[str, Any] | None:
        client = self.require_client()
        for columns in (
            self.INDEX_RESULT_MODERN_COLUMNS,
            self.INDEX_RESULT_LEGACY_COLUMNS,
        ):
            try:
                response = (
                    client.table("index_results")
                    .select(columns)
                    .eq("id", result_id)
                    .limit(1)
                    .execute()
                )
                data = self._payload_data(response) or []
                if data:
                    return data[0]
            except Exception:
                continue
        return None

    def get_roi_analysis(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str = "NDVI",
    ) -> dict[str, Any] | None:
        record = self.get_index_result(roi_id, orthomosaic_id, index_type)
        if record:
            return self._index_result_to_roi_analysis(record)
        row = self._get_roi_analyses_row(roi_id, orthomosaic_id)
        if not row:
            return None
        analyses = self._roi_analyses_row_to_analyses(row, index_type)
        return analyses[0] if analyses else None

    def save_roi_analysis(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        client = self.require_client()
        roi = self.get_roi(roi_id)
        orthomosaic = self.get_orthomosaic(orthomosaic_id)
        if (
            roi.get("agricultural_cycle_id")
            and orthomosaic.get("agricultural_cycle_id")
            and roi["agricultural_cycle_id"] != orthomosaic["agricultural_cycle_id"]
        ):
            raise ValueError(
                "El ROI y el ortomosaico pertenecen a ciclos agricolas distintos.",
            )
        zone = self.ensure_zone_for_roi(roi_id)
        legacy_payload = {
            "roi_id": roi_id,
            "orthomosaic_id": orthomosaic_id,
            "index_type": index_type,
            "avg_value": stats.get("mean"),
            "min_value": stats.get("min"),
            "max_value": stats.get("max"),
            "stddev": stats.get("standard_deviation"),
            "p10": stats.get("p10"),
            "p25": stats.get("p25"),
            "p50": stats.get("median"),
            "p75": stats.get("p75"),
            "p90": stats.get("p90"),
            "pixel_count": stats.get("count"),
            "range_min": stats.get("range_min"),
            "range_max": stats.get("range_max"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        modern_payload = {
            "zone_id": zone["id"],
            "orthomosaic_id": orthomosaic_id,
            "index_type": index_type,
            "avg_value": stats.get("mean"),
            "min_value": stats.get("min"),
            "max_value": stats.get("max"),
            "stddev": stats.get("standard_deviation"),
            "p10": stats.get("p10"),
            "p25": stats.get("p25"),
            "p50": stats.get("median"),
            "p75": stats.get("p75"),
            "p90": stats.get("p90"),
            "pixel_count": stats.get("count"),
            "result_meta": {
                "roi_id": roi_id,
                "range_min": stats.get("range_min"),
                "range_max": stats.get("range_max"),
                "saved_stats": stats,
            },
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        }
        record = None
        modern_error: Exception | None = None
        try:
            existing_modern = self.get_index_result_by_zone(
                zone["id"],
                orthomosaic_id,
                index_type,
            )
            if existing_modern:
                mutation = (
                    client.table("index_results")
                    .update(modern_payload)
                    .eq("id", existing_modern["id"])
                    .select(self.INDEX_RESULT_MODERN_COLUMNS)
                    .execute()
                )
            else:
                mutation = (
                    client.table("index_results")
                    .insert(modern_payload)
                    .select(self.INDEX_RESULT_MODERN_COLUMNS)
                    .execute()
                )
            mutation_data = self._payload_data(mutation) or []
            record = mutation_data[0] if isinstance(mutation_data, list) and mutation_data else mutation_data
        except Exception as exc:
            modern_error = exc
            try:
                existing_response = (
                    client.table("index_results")
                    .select(self.INDEX_RESULT_LEGACY_COLUMNS)
                    .eq("roi_id", roi_id)
                    .eq("orthomosaic_id", orthomosaic_id)
                    .eq("index_type", index_type)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                existing_legacy = list(self._payload_data(existing_response) or [])
                mutation_query = client.table("index_results")
                mutation = (
                    mutation_query.update(legacy_payload)
                    .eq("id", existing_legacy[0]["id"])
                    if existing_legacy
                    else mutation_query.insert(legacy_payload)
                )
                mutation = (
                    mutation
                    .select(self.INDEX_RESULT_LEGACY_COLUMNS)
                    .execute()
                )
                mutation_data = self._payload_data(mutation) or []
                record = mutation_data[0] if isinstance(mutation_data, list) and mutation_data else mutation_data
            except Exception as legacy_exc:
                try:
                    return self._save_roi_analysis_row(
                        roi_id,
                        orthomosaic_id,
                        index_type,
                        stats,
                    )
                except Exception as roi_analyses_exc:
                    raise ValueError(
                        "Fallo el guardado en index_results. "
                        f"Intento esquema real: {modern_error}. "
                        f"Intento esquema legado: {legacy_exc}. "
                        f"Intento roi_analyses: {roi_analyses_exc}."
                    ) from roi_analyses_exc
        if not record:
            record = self.get_index_result(roi_id, orthomosaic_id, index_type)
        if not record:
            return self._save_roi_analysis_row(
                roi_id,
                orthomosaic_id,
                index_type,
                stats,
            )
        return self._index_result_to_roi_analysis(record)

    def list_roi_analyses(
        self,
        roi_id: str,
        index: str | None = None,
        agricultural_cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        roi = self.get_roi(roi_id)
        if (
            agricultural_cycle_id
            and roi.get("agricultural_cycle_id")
            and roi["agricultural_cycle_id"] != agricultural_cycle_id
        ):
            return []
        client = self.require_client()
        modern_query_succeeded = False
        try:
            query = (
                client.table("index_results")
                .select(self.INDEX_RESULT_MODERN_COLUMNS)
                .contains("result_meta", {"roi_id": roi_id})
            )
            if index in {"NDVI", "NDWI", "NDRE"}:
                query = query.eq("index_type", index)
            response = query.order("calculated_at", desc=True).execute()
            data = list(self._payload_data(response) or [])
            modern_query_succeeded = True
            modern_items = [
                self._index_result_to_roi_analysis(item)
                for item in self._latest_index_results_per_flight(data)
            ]
            if modern_items:
                return modern_items
        except Exception:
            pass

        try:
            response = (
                client.table("roi_analyses")
                .select(self.ROI_ANALYSES_COLUMNS)
                .eq("roi_id", roi_id)
                .order("created_at", desc=True)
                .execute()
            )
            rows = list(self._payload_data(response) or [])
            analyses: list[dict[str, Any]] = []
            for row in rows:
                analyses.extend(self._roi_analyses_row_to_analyses(row, index))
            if analyses:
                return analyses
        except Exception:
            pass

        if modern_query_succeeded:
            return []

        query = (
            client.table("index_results")
            .select(self.INDEX_RESULT_LEGACY_COLUMNS)
            .eq("roi_id", roi_id)
        )
        if index in {"NDVI", "NDWI", "NDRE"}:
            query = query.eq("index_type", index)
        response = query.order("created_at", desc=True).execute()
        legacy_items = [
            self._index_result_to_roi_analysis(item)
            for item in self._latest_index_results_per_flight(
                list(self._payload_data(response) or []),
            )
        ]
        return legacy_items

    def delete_roi_analysis(self, roi_id: str, analysis_id: str) -> None:
        client = self.require_client()
        roi_analyses_key = self._parse_roi_analyses_record_id(analysis_id)
        if roi_analyses_key:
            row_id, index_type = roi_analyses_key
            response = (
                client.table("roi_analyses")
                .select(self.ROI_ANALYSES_COLUMNS)
                .eq("id", row_id)
                .eq("roi_id", roi_id)
                .limit(1)
                .execute()
            )
            rows = list(self._payload_data(response) or [])
            if not rows:
                raise RoiAnalysisNotFoundError(
                    "No existe la estadistica seleccionada para este ROI.",
                )
            row = rows[0]
            remaining = {
                name: row.get(name)
                for name in ("ndvi", "ndwi", "ndre")
            }
            remaining[index_type.lower()] = None
            still_has_stats = any(
                self._is_saved_roi_stats(value)
                for value in remaining.values()
            )
            if not still_has_stats:
                client.table("roi_analyses").delete().eq("id", row_id).execute()
                return
            update_payload = {index_type.lower(): None}
            if index_type == "NDVI":
                update_payload["ndvi"] = {}
            client.table("roi_analyses").update(update_payload).eq("id", row_id).execute()
            return
        found = False
        try:
            response = (
                client.table("index_results")
                .select("id,result_meta")
                .eq("id", analysis_id)
                .limit(1)
                .execute()
            )
            data = list(self._payload_data(response) or [])
            if data and isinstance(data[0].get("result_meta"), dict):
                found = data[0]["result_meta"].get("roi_id") == roi_id
        except Exception:
            found = False
        if not found:
            response = (
                client.table("index_results")
                .select("id")
                .eq("id", analysis_id)
                .eq("roi_id", roi_id)
                .limit(1)
                .execute()
            )
            found = bool(self._payload_data(response))
        if not found:
            raise RoiAnalysisNotFoundError(
                "No existe la estadistica seleccionada para este ROI.",
            )
        client.table("index_results").delete().eq("id", analysis_id).execute()

    def delete_global_analysis(self, analysis_id: str) -> None:
        client = self.require_client()
        response = (
            client.table("global_analyses")
            .select("id")
            .eq("id", analysis_id)
            .limit(1)
            .execute()
        )
        if not self._payload_data(response):
            raise RoiAnalysisNotFoundError(
                "No existe la estadistica global seleccionada.",
            )
        client.table("global_analyses").delete().eq("id", analysis_id).execute()

    def set_roi_active(self, roi_id: str, active: bool) -> dict[str, Any]:
        response = (
            self.require_client()
            .table("rois")
            .update({"is_active": active})
            .eq("id", roi_id)
            .execute()
        )
        data = self._payload_data(response)
        if not data:
            raise OrthomosaicNotFoundError("No existe el ROI.")
        return data[0]

    def delete_roi(self, roi_id: str) -> None:
        self.require_client().table("rois").delete().eq("id", roi_id).execute()

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
        raster_service.active_path = local_path
        raster_service.sensor = record.get("sensor_type")
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
