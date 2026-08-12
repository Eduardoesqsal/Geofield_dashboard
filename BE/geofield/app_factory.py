"""Factory de FastAPI para GeoField.

Construye la aplicación, registra middleware y conecta servicios de raster,
persistencia y rutas HTTP en un único punto de ensamblaje.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from geofield.api.routes import create_router
from geofield.config import Settings
from geofield.services.raster_service import RasterService
from geofield.services.supabase_service import SupabaseService


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    app = FastAPI(title="Geofield Dashboard API", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=list(config.frontend_origins), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.mount("/static", StaticFiles(directory=config.output_dir), name="static")
    app.include_router(create_router(RasterService(config), config.output_dir, config.base_dir, SupabaseService(config)))
    return app
