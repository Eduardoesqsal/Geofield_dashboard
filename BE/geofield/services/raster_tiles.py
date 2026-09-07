"""Reproyección y construcción de tiles para `RasterService`."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import Window, from_bounds, transform as window_transform


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    n = 2**z
    left, right = x / n * 360 - 180, (x + 1) / n * 360 - 180
    top = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * y / n))))
    bottom = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + 1) / n))))
    return left, bottom, right, top


def tile_bounds_mercator(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    origin = 20_037_508.342789244
    span = (origin * 2) / (2**z)
    left = -origin + x * span
    right = left + span
    top = origin - y * span
    bottom = top - span
    return left, bottom, right, top


def reproject_rgb_tile(
    src: Any,
    z: int,
    x: int,
    y: int,
    *,
    tile_size: int,
    mercator_bounds: tuple[float, float, float, float],
    rgb_render_profile: Callable[[Any], dict[str, Any]],
    rgb_valid_mask: Callable[..., np.ndarray],
    render_rgb_values: Callable[[np.ndarray, dict[str, Any]], np.ndarray],
) -> tuple[np.ndarray, np.ndarray, Affine]:
    if not src.crs:
        raise ValueError("El ortomosaico no tiene CRS y no puede reproyectarse a Web Mercator.")
    dst_transform = rasterio.transform.from_bounds(*mercator_bounds, tile_size, tile_size)
    profile = rgb_render_profile(src)
    bands = profile["bands"]
    destination_dtype = np.result_type(*(np.dtype(src.dtypes[index - 1]) for index in bands))
    rgb = np.zeros((3, tile_size, tile_size), dtype=destination_dtype)
    for destination, band_index in zip(rgb, bands, strict=True):
        options: dict[str, Any] = {
            "source": rasterio.band(src, band_index),
            "destination": destination,
            "src_transform": src.transform,
            "src_crs": src.crs,
            "dst_transform": dst_transform,
            "dst_crs": "EPSG:3857",
            "resampling": Resampling.nearest,
        }
        nodata = src.nodatavals[band_index - 1]
        if nodata is not None:
            options["src_nodata"] = nodata
        reproject(**options)

    destination_mask = np.zeros((tile_size, tile_size), dtype=np.uint8)
    source_bounds = transform_bounds("EPSG:3857", src.crs, *mercator_bounds, densify_pts=21)
    try:
        source_window = from_bounds(*source_bounds, transform=src.transform).intersection(
            Window(0, 0, src.width, src.height),
        )
    except Exception:
        source_window = None
    if source_window is not None and source_window.width > 0 and source_window.height > 0:
        sample_scale = max(1.0, max(source_window.width, source_window.height) / 2048)
        source_width = max(1, int(np.ceil(source_window.width / sample_scale)))
        source_height = max(1, int(np.ceil(source_window.height / sample_scale)))
        source_rgb = src.read(
            list(bands),
            window=source_window,
            out_shape=(3, source_height, source_width),
            resampling=Resampling.nearest,
        )
        source_valid = rgb_valid_mask(src, bands, source_rgb, window=source_window)
        source_transform = window_transform(source_window, src.transform) * Affine.scale(
            source_window.width / source_width,
            source_window.height / source_height,
        )
        reproject(
            source=source_valid.astype(np.uint8),
            destination=destination_mask,
            src_transform=source_transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            resampling=Resampling.nearest,
        )

    valid = (
        (destination_mask > 0)
        & np.all(np.isfinite(rgb), axis=0)
        & np.any(rgb != 0, axis=0)
    )
    return render_rgb_values(rgb, profile), valid, dst_transform


def reproject_index_matrix(
    src: Any,
    name: str,
    z: int,
    x: int,
    y: int,
    *,
    tile_size: int,
    mercator_bounds: tuple[float, float, float, float],
    index_bands: Callable[[str], tuple[int, int]],
    calculate_index: Callable[[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, Affine]:
    if not src.crs:
        raise ValueError("El ortomosaico no tiene CRS y no puede reproyectar el indice.")
    dst_transform = rasterio.transform.from_bounds(*mercator_bounds, tile_size, tile_size)
    tile_values = np.full((tile_size, tile_size), np.nan, dtype=np.float32)
    tile_valid = np.zeros((tile_size, tile_size), dtype=np.uint8)
    source_bounds = transform_bounds("EPSG:3857", src.crs, *mercator_bounds, densify_pts=21)
    try:
        source_window = from_bounds(*source_bounds, transform=src.transform).intersection(
            Window(0, 0, src.width, src.height),
        )
    except Exception:
        source_window = None
    if source_window is None or source_window.width <= 0 or source_window.height <= 0:
        return tile_values, tile_valid.astype(bool), dst_transform

    sample_scale = max(1.0, max(source_window.width, source_window.height) / 2048)
    source_width = max(1, int(np.ceil(source_window.width / sample_scale)))
    source_height = max(1, int(np.ceil(source_window.height / sample_scale)))
    bands = index_bands(name)
    positive, negative = src.read(
        list(bands),
        window=source_window,
        out_shape=(2, source_height, source_width),
        resampling=Resampling.nearest,
    ).astype(np.float32)
    values, valid = calculate_index(positive, negative)
    band_masks = src.read_masks(
        list(bands),
        window=source_window,
        out_shape=(2, source_height, source_width),
        resampling=Resampling.nearest,
    )
    dataset_mask = src.dataset_mask(
        window=source_window,
        out_shape=(source_height, source_width),
        resampling=Resampling.nearest,
    )
    valid &= np.all(band_masks > 0, axis=0) & (dataset_mask > 0)
    source_values = np.where(valid, values, np.nan).astype(np.float32)
    source_transform = window_transform(source_window, src.transform) * Affine.scale(
        source_window.width / source_width,
        source_window.height / source_height,
    )
    reproject(
        source=source_values,
        destination=tile_values,
        src_transform=source_transform,
        src_crs=src.crs,
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
    )
    reproject(
        source=valid.astype(np.uint8),
        destination=tile_valid,
        src_transform=source_transform,
        src_crs=src.crs,
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        resampling=Resampling.nearest,
    )
    return tile_values, (tile_valid > 0) & np.isfinite(tile_values), dst_transform
