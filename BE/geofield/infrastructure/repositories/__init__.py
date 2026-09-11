"""Adapters de repositorios de infraestructura."""

from geofield.infrastructure.repositories.supabase_repositories import (
    SupabaseOrthomosaicRepository,
    SupabaseRoiAnalysisRepository,
)

__all__ = [
    "SupabaseOrthomosaicRepository",
    "SupabaseRoiAnalysisRepository",
]
