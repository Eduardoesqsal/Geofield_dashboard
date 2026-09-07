"""Utilidades de caché y rutas para `RasterService`."""

from __future__ import annotations

import tempfile
from pathlib import Path

from geofield.services.raster_helpers import compact_cache_component


def rgb_profile_key(path: Path) -> tuple[str, int, int]:
    raster_path = path.resolve()
    stat = raster_path.stat()
    return str(raster_path), stat.st_size, stat.st_mtime_ns


def tile_cache_version(path: Path, renderer_version: str) -> str:
    _, _, mtime_ns = rgb_profile_key(path)
    return f"{mtime_ns}-{renderer_version}"


def index_tile_cache_version(path: Path, renderer_version: str) -> str:
    _, _, mtime_ns = rgb_profile_key(path)
    return f"{mtime_ns}-{renderer_version}"


def tile_cache_path(
    cache_dir: Path,
    raster_path: Path,
    version: str,
    kind: str,
    z: int,
    x: int,
    y: int,
    variant: str = "default",
) -> Path:
    raster_scope = compact_cache_component(f"{raster_path.stem}-{version}")
    safe_variant = compact_cache_component(variant)
    return (
        cache_dir
        / "tiles"
        / kind
        / raster_scope
        / str(z)
        / str(x)
        / f"{y}-{safe_variant}.png"
    )


def read_tile_cache(cache_path: Path) -> bytes | None:
    try:
        return cache_path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        return None


def write_tile_cache(cache_path: Path, content: bytes) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=cache_path.parent,
        suffix=".tmp",
        delete=False,
    ) as temporary_file:
        temporary_file.write(content)
        temporary_path = Path(temporary_file.name)
    temporary_path.replace(cache_path)
