"""Utilidades de parsing para la capa HTTP.

Estas funciones encapsulan validaciones repetidas de payloads JSON y GeoJSON
sin acoplar la lógica de negocio a `routes.py`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException
from shapely.geometry import shape
from shapely.ops import unary_union


def payload_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(400, "El cuerpo de la petición debe ser un objeto JSON.")
    return payload


def require_string(payload: Any, key: str, message: str) -> str:
    value = payload_object(payload).get(key)
    text = str(value or "").strip()
    if not text:
        raise HTTPException(400, message)
    return text


def optional_string(payload: Any, key: str) -> str | None:
    text = str(payload_object(payload).get(key) or "").strip()
    return text or None


def parse_iso_date(raw: Any, message: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise HTTPException(422, message) from exc


def require_list_of_strings(payload: Any, key: str, message: str) -> list[str]:
    raw_items = payload_object(payload).get(key)
    if not isinstance(raw_items, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw_items
    ):
        raise HTTPException(400, message)
    return [item.strip() for item in raw_items]


def geojson_geometry(payload: Any) -> Any:
    data = payload_object(payload)
    if "geojson" not in data:
        raise HTTPException(400, "No GeoJSON recibido")
    geojson = data["geojson"]
    if not isinstance(geojson, dict):
        raise HTTPException(400, "El campo geojson debe ser un objeto GeoJSON")
    if geojson.get("type") == "Feature":
        geojson = geojson.get("geometry")
    elif geojson.get("type") == "FeatureCollection":
        geometries = [
            item.get("geometry")
            for item in geojson.get("features", [])
            if isinstance(item, dict) and isinstance(item.get("geometry"), dict)
        ]
        if not geometries:
            raise HTTPException(400, "El FeatureCollection no contiene geometrías")
        try:
            return unary_union([shape(item) for item in geometries])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Geometrías GeoJSON inválidas") from exc
    elif "geometry" in geojson and geojson.get("type") != "FeatureCollection":
        geojson = geojson["geometry"]
    if not isinstance(geojson, dict) or not geojson.get("type") or "coordinates" not in geojson:
        raise HTTPException(400, "Se requiere una geometría GeoJSON válida")
    try:
        return shape(geojson)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Geometría GeoJSON inválida") from exc
