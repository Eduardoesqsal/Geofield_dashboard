"""Casos de uso para publicar resultados hacia el dashboard externo."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from geofield.application.ports import PublicationRepository


class PublishResultsUseCase:
    """Valida y publica el paquete de resultados version 1."""

    def __init__(self, repository: PublicationRepository) -> None:
        self.repository = repository

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._validate(payload)
        normalized["analysis"]["payload_hash"] = self._payload_hash(normalized)
        return self.repository.publish(normalized)

    def _validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("La publicacion debe enviarse como objeto JSON.")

        normalized = copy.deepcopy(payload)
        project = self._object(normalized, "project")
        analysis = self._object(normalized, "analysis")
        roi = self._object(normalized, "roi")
        indices = normalized.get("indices")

        if not self._text(project.get("name")):
            raise ValueError("project.name es obligatorio.")
        if not self._text(analysis.get("source_publication_key")):
            raise ValueError("analysis.source_publication_key es obligatorio.")
        if not self._text(analysis.get("analysis_type")):
            analysis["analysis_type"] = "roi_prescription"
        if "payload_version" not in analysis:
            analysis["payload_version"] = 1
        if not isinstance(roi.get("geometry_geojson"), dict):
            raise ValueError("roi.geometry_geojson debe ser un objeto GeoJSON.")
        if not isinstance(indices, list) or not indices:
            raise ValueError("indices debe contener al menos un resultado.")

        for item in indices:
            if not isinstance(item, dict):
                raise ValueError("Cada indice publicado debe ser un objeto.")
            index_name = item.get("index_name")
            if index_name not in {"NDVI", "NDWI", "NDRE"}:
                raise ValueError("indices[].index_name debe ser NDVI, NDWI o NDRE.")
            if not isinstance(item.get("stats"), dict):
                item["stats"] = {}

        prescription = normalized.get("prescription")
        if prescription is not None:
            if not isinstance(prescription, dict):
                raise ValueError("prescription debe ser un objeto.")
            if not self._text(prescription.get("source_prescription_id")):
                raise ValueError("prescription.source_prescription_id es obligatorio.")
            if prescription.get("index_name") not in {"NDVI", "NDWI", "NDRE"}:
                raise ValueError("prescription.index_name debe ser NDVI, NDWI o NDRE.")
            if not isinstance(prescription.get("legend"), list):
                raise ValueError("prescription.legend debe ser una lista.")

        zoning = normalized.get("zoning")
        if zoning is not None:
            if not isinstance(zoning, dict):
                raise ValueError("zoning debe ser un objeto.")
            if zoning.get("index_name") not in {"NDVI", "NDWI", "NDRE"}:
                raise ValueError("zoning.index_name debe ser NDVI, NDWI o NDRE.")

        artifacts = normalized.get("artifacts")
        if artifacts is None:
            normalized["artifacts"] = []
        elif not isinstance(artifacts, list):
            raise ValueError("artifacts debe ser una lista.")

        return normalized

    @staticmethod
    def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
        value = payload.get(key)
        if not isinstance(value, dict):
            raise ValueError(f"{key} debe ser un objeto.")
        return value

    @staticmethod
    def _text(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _payload_hash(payload: dict[str, Any]) -> str:
        body = copy.deepcopy(payload)
        body.get("analysis", {}).pop("payload_hash", None)
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class DeletePublicationUseCase:
    """Elimina una publicacion de Neon sin tocar la base operativa."""

    def __init__(self, repository: PublicationRepository) -> None:
        self.repository = repository

    def execute(self, source_publication_key: str) -> dict[str, Any]:
        if not isinstance(source_publication_key, str) or not source_publication_key.strip():
            raise ValueError("source_publication_key es obligatorio.")
        return self.repository.delete(source_publication_key.strip())
