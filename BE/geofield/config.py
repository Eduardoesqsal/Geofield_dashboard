from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _normalize_supabase_url(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().rstrip("/")
    if normalized.endswith("/rest/v1"):
        normalized = normalized[: -len("/rest/v1")]
    return normalized or None


@dataclass(frozen=True)
class Settings:
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    raster_path: Path | None = None
    output_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "static")
    cache_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "cache")
    uploads_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "uploads")
    frontend_origins: tuple[str, ...] = ("http://localhost:3000", "http://localhost:5173")
    rgb_max_pixels: int = 850_000
    ndvi_max_pixels: int = 2_250_000
    port: int = 8005
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_bucket: str = "orthomosaics"
    orthomosaic_storage_mode: str = "local"

    def __post_init__(self) -> None:
        if self.raster_path is None:
            candidates = (self.base_dir / "LA_GARZA.tif", self.base_dir.parent / "LA_GARZA.tif", self.base_dir / "LA_GARZA.tif")
            object.__setattr__(self, "raster_path", next((p for p in candidates if p.is_file()), None))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",") if x.strip())
        raster = os.getenv("RASTER_PATH")
        return cls(
            raster_path=Path(raster).resolve() if raster else None,
            frontend_origins=origins,
            port=int(os.getenv("PORT", "8005")),
            supabase_url=_normalize_supabase_url(os.getenv("SUPABASE_URL")),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
            supabase_bucket=os.getenv("SUPABASE_BUCKET", "orthomosaics"),
            orthomosaic_storage_mode=os.getenv("ORTHOMOSAIC_STORAGE_MODE", "local").strip().lower() or "local",
        )
