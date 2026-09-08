"""Block-based native-resolution processing for the raster service."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.windows import Window, transform as window_transform
from rasterio.warp import reproject
from shapely.geometry import mapping

from geofield.services import raster_cache

BLOCK_SIZE = 1024
MEMORY_PIXELS = 4_000_000


def windows(width, height):
    for row in range(0, height, BLOCK_SIZE):
        for col in range(0, width, BLOCK_SIZE):
            yield Window(col, row, min(BLOCK_SIZE, width - col), min(BLOCK_SIZE, height - row))


def index_range(src, window, geometry, bands, calculate_index, cache_dir):
    key = hashlib.sha256(json.dumps([
        "index-range-v1", raster_cache.rgb_profile_key(Path(src.name)),
        tuple(window.flatten()), geometry.wkb_hex, bands,
    ]).encode()).hexdigest()
    cache_path = cache_dir / "index-ranges" / f"{key}.json"
    cached = raster_cache.read_tile_cache(cache_path)
    if cached is not None:
        try:
            return tuple(json.loads(cached))
        except (ValueError, TypeError):
            pass
    width, height = int(np.floor(window.width + 0.5)), int(np.floor(window.height + 0.5))
    minimum, maximum = np.inf, -np.inf
    transform = window_transform(window, src.transform)
    roi_mask = geometry_mask([mapping(geometry)], out_shape=(height, width),
                             transform=transform, invert=True, all_touched=True)
    for local in windows(width, height):
        # Preserve Rasterio's sampling of fractional windows and the original
        # ROI mask transform, including its existing edge-pixel semantics.
        source_window = Window(
            window.col_off + local.col_off * window.width / width,
            window.row_off + local.row_off * window.height / height,
            local.width * window.width / width, local.height * window.height / height,
        )
        positive, negative = src.read(list(bands), window=source_window,
                                     out_shape=(2, int(local.height), int(local.width))).astype(np.float32)
        values, valid = calculate_index(positive, negative)
        rows, cols = local.toslices()
        valid &= roi_mask[rows, cols]
        selected = values[valid]
        if selected.size:
            minimum = min(minimum, float(selected.min()))
            maximum = max(maximum, float(selected.max()))
    result = (minimum, maximum) if minimum != np.inf else (None, None)
    raster_cache.write_tile_cache(cache_path, json.dumps(result).encode())
    return result


def classification_grid(
    src, source_window, geometry, bands, calculate_index,
    destination_transform, destination_crs, height, width, mode,
    analysis_min, analysis_max, cache_dir,
):
    """Keep GDAL's native-pixel aggregation; cache only the small output grid."""
    key = hashlib.sha256(json.dumps([
        "classification-grid-v1", raster_cache.rgb_profile_key(Path(src.name)),
        tuple(source_window.flatten()), geometry.wkb_hex, bands,
        tuple(destination_transform), str(destination_crs), height, width,
        mode, analysis_min, analysis_max,
    ], sort_keys=True).encode()).hexdigest()
    cache_path = cache_dir / "classification" / f"{key}.npz"
    cached = raster_cache.read_tile_cache(cache_path)
    if cached is not None:
        try:
            with np.load(io.BytesIO(cached), allow_pickle=False) as saved:
                return saved["values"], saved["fraction"], saved["stats"]
        except (ValueError, OSError, EOFError):
            pass

    source_width, source_height = int(source_window.width), int(source_window.height)
    transform = window_transform(source_window, src.transform)
    # Rasterizing each block independently changes GDAL's all_touched edge
    # decisions. Keep one byte per native pixel to preserve the original mask.
    roi_mask = geometry_mask([mapping(geometry)], out_shape=(source_height, source_width),
                             transform=transform, invert=True, all_touched=True)
    values = np.full((height, width), np.nan, dtype=np.float32)
    fraction = np.zeros((height, width), dtype=np.float32)
    minimum, maximum, total, count = np.inf, -np.inf, 0.0, 0
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Large intermediate matrices live on disk. Both paths use the same
    # reprojection call, including validity zeros outside the polygon.
    with tempfile.TemporaryDirectory(dir=cache_dir, prefix="grid-") as temporary:
        large = source_width * source_height > MEMORY_PIXELS
        if large:
            intermediate = rasterio.open(
                Path(temporary) / "source.tif", "w+", driver="GTiff",
                width=source_width, height=source_height, count=2,
                dtype="float32", transform=transform, crs=src.crs,
                tiled=True, blockxsize=256, blockysize=256, BIGTIFF="IF_SAFER",
            )
        else:
            intermediate = None
            matrix = np.empty((2, source_height, source_width), dtype=np.float32)
        try:
            for local in windows(source_width, source_height):
                window = Window(source_window.col_off + local.col_off,
                                source_window.row_off + local.row_off,
                                local.width, local.height)
                positive, negative = src.read(list(bands), window=window).astype(np.float32)
                index, valid = calculate_index(positive, negative)
                valid &= np.all(src.read_masks(list(bands), window=window) > 0, axis=0)
                valid &= src.dataset_mask(window=window) > 0
                rows, cols = local.toslices()
                valid &= roi_mask[rows, cols]
                if analysis_min is not None:
                    valid &= index >= analysis_min
                if analysis_max is not None:
                    valid &= index <= analysis_max
                selected = index[valid]
                if selected.size:
                    minimum = min(minimum, float(selected.min()))
                    maximum = max(maximum, float(selected.max()))
                    total += float(np.sum(selected, dtype=np.float64))
                    count += selected.size
                index[~valid] = np.nan
                if intermediate is not None:
                    intermediate.write(index, 1, window=local)
                    intermediate.write(valid.astype(np.float32), 2, window=local)
                else:
                    rows, cols = local.toslices()
                    matrix[0, rows, cols] = index
                    matrix[1, rows, cols] = valid
            if not count:
                raise ValueError("El ROI no contiene muestras validas dentro del filtro de analisis.")
            del roi_mask
            options = dict(src_transform=transform, src_crs=src.crs,
                           dst_transform=destination_transform, dst_crs=destination_crs)
            reproject(source=rasterio.band(intermediate, 1) if large else matrix[0],
                      destination=values, src_nodata=np.nan, dst_nodata=np.nan,
                      resampling={"mean": Resampling.average, "min": Resampling.min,
                                  "max": Resampling.max}[mode], **options)
            reproject(source=rasterio.band(intermediate, 2) if large else matrix[1],
                      destination=fraction, dst_nodata=0,
                      resampling=Resampling.average, **options)
        finally:
            if intermediate is not None:
                intermediate.close()
    stats = np.asarray([minimum, maximum, total / count], dtype=np.float64)
    output = io.BytesIO()
    np.savez_compressed(output, values=values, fraction=fraction, stats=stats)
    raster_cache.write_tile_cache(cache_path, output.getvalue())
    return values, fraction, stats
