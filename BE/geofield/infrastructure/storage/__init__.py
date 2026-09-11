"""Adaptadores de almacenamiento de artefactos."""

from geofield.infrastructure.storage.factory import create_artifact_storage
from geofield.infrastructure.storage.local_artifact_storage import LocalArtifactStorage
from geofield.infrastructure.storage.supabase_artifact_storage import SupabaseArtifactStorage

__all__ = [
    "LocalArtifactStorage",
    "SupabaseArtifactStorage",
    "create_artifact_storage",
]

