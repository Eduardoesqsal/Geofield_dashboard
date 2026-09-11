"""Adaptador de persistencia hacia Supabase.

Mantiene la clase publica `SupabaseService` y reparte los grupos de operaciones
en mixins para que ciclos, ortomosaicos, ROI y analisis evolucionen separados.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from postgrest import ReturnMethod
from rasterio.io import MemoryFile
from rasterio.warp import transform_bounds
from shapely.geometry import box
from supabase import Client, create_client

from geofield.config import Settings
from geofield.errors import SupabaseNotConfiguredError
from geofield.services.supabase_activation import SupabaseActivationMixin
from geofield.services.supabase_orthomosaics import SupabaseOrthomosaicMixin
from geofield.services.supabase_roi_analysis import SupabaseRoiAnalysisMixin


@dataclass(frozen=True)
class RasterMetadata:
    bounds_wkt: str
    raster_crs: str | None
    width_px: int
    height_px: int
    bands_count: int
    file_size_bytes: int


class SupabaseService(SupabaseOrthomosaicMixin, SupabaseRoiAnalysisMixin, SupabaseActivationMixin):
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
