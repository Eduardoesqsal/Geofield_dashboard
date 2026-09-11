"""Factory de storage de artefactos.

El modo por defecto es local. Supabase queda preparado para activarse por
configuracion futura, sin cambiar los casos de uso.
"""

from __future__ import annotations

from supabase import Client

from geofield.application.ports import ArtifactStorage
from geofield.config import Settings
from geofield.infrastructure.storage.local_artifact_storage import LocalArtifactStorage
from geofield.infrastructure.storage.supabase_artifact_storage import SupabaseArtifactStorage


def create_artifact_storage(
    settings: Settings,
    supabase_client: Client | None = None,
) -> ArtifactStorage:
    mode = settings.artifact_storage_mode.strip().lower()
    if mode == "local":
        return LocalArtifactStorage(settings.output_dir)
    if mode == "supabase":
        if supabase_client is None:
            raise ValueError("Supabase Storage requiere un cliente configurado.")
        return SupabaseArtifactStorage(
            supabase_client,
            settings.artifact_storage_bucket,
        )
    raise ValueError("ARTIFACT_STORAGE_MODE debe ser local o supabase.")

