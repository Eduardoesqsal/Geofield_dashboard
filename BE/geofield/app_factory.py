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
from geofield.infrastructure.jobs import ImmediateJobQueue
from geofield.infrastructure.storage import create_artifact_storage
from geofield.services.raster_service import RasterService
from geofield.services.supabase_service import SupabaseService


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    supabase = SupabaseService(config)
    artifact_storage = create_artifact_storage(config, supabase.client)
    job_queue = ImmediateJobQueue()
    raster = RasterService(config, artifact_storage)
    app = FastAPI(title="Geofield Dashboard API", version="1.0.0")
    # Permite desarrollo local tanto en localhost como en IPs privadas de la red.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.frontend_origins),
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}|192\.168(?:\.\d{1,3}){2})(?::\d+)?$", #INPUTACION DE ENTRADA 
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=config.output_dir), name="static")
    app.include_router(
        create_router(
            raster,
            config.output_dir,
            config.base_dir,
            supabase,
            artifact_storage,
            job_queue,
        ),
    )
    return app
