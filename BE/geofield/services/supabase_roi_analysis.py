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



class SupabaseRoiAnalysisMixin:
    """CRUD de ROI, zonas y analisis historicos."""

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
    