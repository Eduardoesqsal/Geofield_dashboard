"""Servicio principal de procesamiento raster.

Mantiene la clase publica `RasterService` y reparte la implementacion en
mixins especializados para que el motor geoespacial sea mas mantenible sin
cambiar el contrato usado por rutas y tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import numpy as np
from affine import Affine

from geofield.config import Settings
from geofield.services.raster_classification import RasterClassificationMixin
from geofield.services.raster_indices import RasterIndexMixin
from geofield.services.raster_tiles_export import RasterTileExportMixin


class RasterService(RasterClassificationMixin, RasterIndexMixin, RasterTileExportMixin):
    """Procesamiento geoespacial; no conoce detalles de FastAPI."""

    VEGETATION_COLOR_RAMP = [
        "ff1f1f", "ff4a1f", "ff741f", "ff9b1f", "ffc21f",
        "ffdd1f", "f3eb23", "d6e428", "a9d83a", "6ccf45",
    ]
    VEGETATION_COLOR_STOPS = np.asarray(
        [0.0, 0.12, 0.24, 0.38, 0.50, 0.60, 0.68, 0.76, 0.88, 1.0],
        dtype=np.float32,
    )
    INDEX_RAMPS = {
        "NDVI": VEGETATION_COLOR_RAMP,
        # Colores de turbo.png, compartidos con FE/src/utils/ndvi.ts.
        "NDWI": [
            "5956a5", "476db0", "3387bc", "459eb4", "5bb5aa",
            "76c8a5", "92d3a4", "aedea3", "c9e99e", "e0f299",
            "eef8a5", "f9fdb8", "fffab9", "feeca0", "fedf8a",
            "fecb79", "fdb466", "fa9b59", "f7814c", "f06645",
            "e3534a",
        ],
        "NDRE": VEGETATION_COLOR_RAMP,
    }
    PIX4D_ZONE_DISPLAY_PALETTES = {
        ("NDVI", 4): ["ff1f1f", "ff9b1f", "d6f01f", "30df1f"],
        ("NDVI", 5): ["ff1f1f", "ffb31f", "fff01f", "b7ef1f", "18e61f"],
        ("NDRE", 4): ["ff1f1f", "ff9b1f", "d6f01f", "30df1f"],
        ("NDRE", 5): ["ff1f1f", "ffb31f", "fff01f", "b7ef1f", "18e61f"],
    }
    INDEX_DOMAINS = {"NDVI": (-0.2, 0.8), "NDWI": (-0.5, 0.5), "NDRE": (-0.2, 0.8)}
    RGB_RENDER_VERSION = "webmercator-v3"
    INDEX_RENDER_VERSION = "index-matrix-webmercator-v7"
    RGB_TILE_SIZE = 256
    EAVISION_DOSAGE_EXPORT_SCALE = 0.1
    _rgb_profile_cache: ClassVar[
        dict[tuple[str, int, int], dict[str, Any]]
    ] = {}
    _index_lut_cache: ClassVar[dict[str, np.ndarray]] = {}
    _equalization_cache_limit = 32

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Conservado como estado compatible; ahora contiene rangos globales por
        # canal y nunca percentiles calculados dentro de un tile.
        self.rgb_stretch: Any = None
        self.overlay: tuple[int, int, Affine] | None = None
        self.active_path: Path | None = None
        self.sensor: str | None = None
        self.crop_geometries: dict[str, Any] = {}
        self.equalization_cache: dict[tuple[Any, ...], np.ndarray | None] = {}
