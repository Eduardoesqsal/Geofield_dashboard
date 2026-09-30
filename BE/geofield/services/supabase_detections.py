"""Persistencia de detecciones puntuales asociadas a un ortomosaico."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any

from postgrest import ReturnMethod


class SupabaseDetectionsMixin:
    def list_detections(self, cycle_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            self.require_client()
            .table("tree_detection_sets")
            .select(
                "orthomosaic_id,feature_count,updated_at,"
                "orthomosaics!inner(id,name,original_filename,capture_date,"
                "sensor_type,agricultural_cycle_id)",
            )
        )
        if cycle_id:
            query = query.eq("orthomosaics.agricultural_cycle_id", cycle_id)
        response = query.order("updated_at", desc=True).execute()
        return list(self._payload_data(response) or [])

    def get_detections(self, orthomosaic_id: str) -> dict[str, Any] | None:
        response = (
            self.require_client()
            .table("tree_detection_sets")
            .select("orthomosaic_id,geojson,feature_count,updated_at")
            .eq("orthomosaic_id", orthomosaic_id)
            .limit(1)
            .execute()
        )
        rows = self._payload_data(response) or []
        return rows[0] if rows else None

    def delete_detections(self, orthomosaic_id: str) -> None:
        (
            self.require_client()
            .table("tree_detection_sets")
            .delete(returning=ReturnMethod.minimal)
            .eq("orthomosaic_id", orthomosaic_id)
            .execute()
        )

    def save_detections(self, orthomosaic_id: str, geojson: dict[str, Any]) -> dict[str, Any]:
        features = geojson.get("features")
        if geojson.get("type") != "FeatureCollection" or not isinstance(features, list):
            raise ValueError("Las detecciones deben ser un FeatureCollection GeoJSON.")
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise ValueError("Cada deteccion debe ser un Feature GeoJSON.")
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict) or geometry.get("type") != "Point":
                raise ValueError("Las detecciones deben contener puntos.")
            coordinates = geometry.get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                raise ValueError("Cada punto debe incluir longitud y latitud.")
            longitude, latitude = coordinates[:2]
            if (
                isinstance(longitude, bool) or isinstance(latitude, bool)
                or not isinstance(longitude, (int, float))
                or not isinstance(latitude, (int, float))
                or not isfinite(longitude) or not isfinite(latitude)
                or abs(longitude) > 180 or abs(latitude) > 90
            ):
                raise ValueError("Las coordenadas de las detecciones deben estar en grados validos.")
        self.get_orthomosaic(orthomosaic_id)
        updated_at = datetime.now(timezone.utc).isoformat()
        (
            self.require_client()
            .table("tree_detection_sets")
            .upsert(
                {
                    "orthomosaic_id": orthomosaic_id,
                    "geojson": geojson,
                    "feature_count": len(features),
                    "updated_at": updated_at,
                },
                on_conflict="orthomosaic_id",
                returning=ReturnMethod.minimal,
            )
            .execute()
        )
        return {
            "orthomosaic_id": orthomosaic_id,
            "feature_count": len(features),
            "updated_at": updated_at,
        }
