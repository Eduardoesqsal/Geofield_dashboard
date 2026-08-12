from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        capture_date: date,
        sensor_type: str,
        name: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        client = self.require_client()
        metadata = self._metadata_from_bytes(content)
        if self.uses_local_storage:
            local_path = self._local_path(capture_date, filename)
            local_path.write_bytes(content)
            file_path = str(local_path.resolve())
        else:
            storage_path = self._storage_path(capture_date, filename)
            client.storage.from_(self.settings.supabase_bucket).upload(
                storage_path,
                content,
                {"content-type": content_type or "image/tiff", "upsert": "false"},
            )
            file_path = storage_path
        response = client.table("orthomosaics").insert(
            {
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
            },
        ).execute()
        data = self._payload_data(response)
        return data[0] if isinstance(data, list) else data

    def list_orthomosaics(self, limit: int = 100) -> list[dict[str, Any]]:
        client = self.require_client()
        response = (
            client.table("orthomosaics")
            .select(
                "id,name,original_filename,capture_date,sensor_type,file_path,upload_status,created_at",
            )
            .order("capture_date", desc=True)
            .limit(limit)
            .execute()
        )
        data = self._payload_data(response)
        return list(data or [])

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

    def create_roi(
        self,
        name: str,
        geojson: dict[str, Any],
        orthomosaic_id: str | None,
    ) -> dict[str, Any]:
        response = self.require_client().table("rois").insert(
            {
                "name": name,
                "geojson": geojson,
                "orthomosaic_id": orthomosaic_id,
            },
        ).execute()
        data = self._payload_data(response)
        return data[0] if isinstance(data, list) else data

    def ensure_zone_for_roi(self, roi_id: str) -> dict[str, Any]:
        roi = self.get_roi(roi_id)
        client = self.require_client()
        try:
            response = (
                client.table("zones")
                .select("id,name,properties")
                .contains("properties", {"roi_id": roi_id})
                .limit(1)
                .execute()
            )
            data = list(self._payload_data(response) or [])
            if data:
                return data[0]
        except Exception:
            pass

        geometry = shape(roi["geojson"]["geometry"] if roi["geojson"].get("type") == "Feature" else roi["geojson"])
        zone_payload = {
            "name": roi.get("name") or "ROI",
            "geom": f"SRID=4326;{geometry.wkt}",
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
            try:
                response = client.table("zones").insert(payload).execute()
                data = self._payload_data(response)
                if isinstance(data, list) and data:
                    return data[0]
                if isinstance(data, dict):
                    return data
            except Exception as exc:
                label = source_format if source_format is not None else "<omitido>"
                errors.append(f"{label}: {exc}")
        raise RoiAnalysisNotFoundError(
            "No se pudo crear la zona asociada al ROI. "
            + " | ".join(errors),
        )

    def list_rois(self) -> list[dict[str, Any]]:
        response = (
            self.require_client()
            .table("rois")
            .select("id,name,geojson,orthomosaic_id,is_active,created_at")
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
        return self._index_result_to_roi_analysis(record) if record else None

    def save_roi_analysis(
        self,
        roi_id: str,
        orthomosaic_id: str,
        index_type: str,
        stats: dict[str, Any],
    ) -> dict[str, Any]:
        client = self.require_client()
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
                mutation = (
                    client.table("index_results")
                    .insert(legacy_payload)
                    .select(self.INDEX_RESULT_LEGACY_COLUMNS)
                    .execute()
                )
                mutation_data = self._payload_data(mutation) or []
                record = mutation_data[0] if isinstance(mutation_data, list) and mutation_data else mutation_data
            except Exception as legacy_exc:
                raise ValueError(
                    "Fallo el guardado en index_results. "
                    f"Intento esquema real: {modern_error}. "
                    f"Intento esquema legado: {legacy_exc}."
                ) from legacy_exc
        if not record:
            record = self.get_index_result(roi_id, orthomosaic_id, index_type)
        if not record:
            raise RoiAnalysisNotFoundError(
                "No se pudo recuperar la estadistica recien guardada.",
            )
        return self._index_result_to_roi_analysis(record)

    def list_roi_analyses(
        self,
        roi_id: str,
        index: str | None = None,
    ) -> list[dict[str, Any]]:
        client = self.require_client()
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
            if data:
                return [self._index_result_to_roi_analysis(item) for item in data]
        except Exception:
            pass

        query = (
            client.table("index_results")
            .select(self.INDEX_RESULT_LEGACY_COLUMNS)
            .eq("roi_id", roi_id)
        )
        if index in {"NDVI", "NDWI", "NDRE"}:
            query = query.eq("index_type", index)
        response = query.order("created_at", desc=True).execute()
        return [
            self._index_result_to_roi_analysis(item)
            for item in list(self._payload_data(response) or [])
        ]

    def delete_roi_analysis(self, roi_id: str, analysis_id: str) -> None:
        client = self.require_client()
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

    def activate_orthomosaic(
        self,
        orthomosaic_id: str,
        raster_service: RasterService,
    ) -> dict[str, Any]:
        record = self.get_orthomosaic(orthomosaic_id)
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
        raster_service.active_path = local_path
        raster_service.sensor = record.get("sensor_type")
        raster_service.rgb_stretch = None
        raster_service.overlay = None
        return record
