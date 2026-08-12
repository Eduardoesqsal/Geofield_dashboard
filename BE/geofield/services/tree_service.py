"""Servicio para normalizar colecciones de árboles.

Convierte entradas heterogéneas a una estructura uniforme con métricas y
clases de tamaño listas para consumirse desde el frontend.
"""

from __future__ import annotations

from typing import Any

import numpy as np


class TreeService:
    SMALL_MAX = 2.5
    MEDIUM_MAX = 3.5
    STYLES = {
        "small": {"color": "#ff1a1a", "opacity": 0.55},
        "medium": {"color": "#ffea00", "opacity": 0.50},
        "large": {"color": "#7CFC00", "opacity": 0.45},
    }
    DIRECT_KEYS = (
        "diam_avg_m",
        "diameter_m",
        "diametro_m",
        "diam_m",
        "tree_diameter_m",
        "canopy_diameter_m",
        "dbh_m",
    )

    @classmethod
    def _number(cls, props: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            try:
                value = float(props[key])
                if value > 0:
                    return value
            except (KeyError, TypeError, ValueError):
                continue
        return None

    @classmethod
    def diameter(cls, props: dict[str, Any]) -> float | None:
        """Devuelve únicamente el promedio para consumidores existentes."""
        dimensions = cls.diameter_dimensions(props)
        return dimensions[0] if dimensions is not None else None

    @classmethod
    def diameter_dimensions(
        cls, props: dict[str, Any]
    ) -> tuple[float, float, float] | None:
        """Obtiene promedio, ancho y alto respetando la prioridad del contrato."""
        direct = cls._number(props, cls.DIRECT_KEYS)
        if direct is not None:
            return direct, direct, direct
        radius = cls._number(props, ("radius_m", "radio_m", "canopy_radius_m"))
        if radius is not None:
            diameter = radius * 2
            return diameter, diameter, diameter
        width = cls._number(props, ("bbox_w_px", "bbox_width_px", "bbox_width"))
        height = cls._number(props, ("bbox_h_px", "bbox_height_px", "bbox_height"))
        pixel = cls._number(props, ("pixel_size_m", "pixel_size", "pixel_resolution_m"))
        if width is None or height is None or pixel is None:
            return None
        width_m = width * pixel
        height_m = height * pixel
        return (width_m + height_m) / 2, width_m, height_m

    @classmethod
    def normalize_feature(cls, feature: Any) -> dict[str, Any] | None:
        if not isinstance(feature, dict):
            return None
        geometry = feature.get("geometry") or {}
        props = feature.get("properties") or {}
        coords = geometry.get("coordinates")
        if (
            geometry.get("type") != "Point"
            or not isinstance(coords, (list, tuple))
            or len(coords) < 2
        ):
            return None
        try:
            lon, lat = float(coords[0]), float(coords[1])
        except (TypeError, ValueError):
            return None
        normalized = dict(props)
        dimensions = cls.diameter_dimensions(props)
        diameter = dimensions[0] if dimensions is not None else None
        if dimensions is not None:
            diameter, width_m, height_m = (round(value, 2) for value in dimensions)
            size = (
                "small"
                if diameter <= cls.SMALL_MAX
                else "medium"
                if diameter <= cls.MEDIUM_MAX
                else "large"
            )
            normalized.update(
                diam_avg_m=diameter,
                diameter_m=diameter,
                diam_x_m=width_m,
                diam_y_m=height_m,
                size_class=size,
            )
        else:
            size = str(props.get("size_class", "unknown")).lower()
            size = size if size in (*cls.STYLES, "unknown") else "unknown"
            normalized["size_class"] = size
        normalized.setdefault("diam_x_m", None)
        normalized.setdefault("diam_y_m", None)
        if size in cls.STYLES:
            style = cls.STYLES[size]
            # Mantiene compatibilidad con visores que consumen estilo GeoJSON.
            normalized.update(
                {
                    "marker-color": style["color"],
                    "marker-opacity": style["opacity"],
                    "marker-size": "medium",
                    "marker-symbol": "circle",
                    "stroke": style["color"],
                    "stroke-opacity": style["opacity"],
                    "stroke-width": 1,
                    "fill": style["color"],
                    "fill-opacity": style["opacity"],
                }
            )
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": normalized,
        }

    @classmethod
    def process(cls, geojson: Any) -> dict[str, Any]:
        if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
            raise ValueError("Se esperaba un FeatureCollection GeoJSON.")
        features = [
            item
            for item in (
                cls.normalize_feature(feature)
                for feature in geojson.get("features", [])
            )
            if item
        ]
        if not features:
            raise ValueError("El GeoJSON no contiene puntos válidos.")
        diameters = [
            float(feature["properties"]["diam_avg_m"])
            for feature in features
            if feature["properties"].get("diam_avg_m") is not None
        ]
        counts = {
            key: sum(
                feature["properties"].get("size_class") == key
                for feature in features
            )
            for key in ("small", "medium", "large", "unknown")
        }
        return {
            "status": "ok",
            "geojson": {"type": "FeatureCollection", "features": features},
            "stats": {
                "count": len(features),
                "diameter_min": round(min(diameters), 2) if diameters else None,
                "diameter_max": round(max(diameters), 2) if diameters else None,
                "diameter_mean": (
                    round(float(np.mean(diameters)), 2) if diameters else None
                ),
                "class_counts": counts,
                "has_diameter": bool(diameters),
            },
        }
