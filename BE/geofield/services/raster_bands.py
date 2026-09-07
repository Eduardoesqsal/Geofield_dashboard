"""Detección de bandas espectrales a partir de metadatos raster."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def wavelength_nm(value: str) -> float | None:
    numbers = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", value)
    if not numbers:
        return None
    wavelength = float(numbers[0])
    return wavelength * 1000 if 0 < wavelength < 10 else wavelength


def band_role_from_text(value: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    if re.search(r"\b(red edge|rededge|re)\b", normalized):
        return "rededge"
    for role, pattern in (
        ("blue", r"\b(blue|azul|b02)\b"),
        ("green", r"\b(green|verde|b03)\b"),
        ("red", r"\b(red|rojo|b04)\b"),
    ):
        if re.search(pattern, normalized):
            return role
    return None


def band_role_from_wavelength(wavelength_nm: float | None) -> str | None:
    if wavelength_nm is None:
        return None
    if 430 <= wavelength_nm < 510:
        return "blue"
    if 510 <= wavelength_nm < 600:
        return "green"
    if 600 <= wavelength_nm < 700:
        return "red"
    if 700 <= wavelength_nm < 760:
        return "rededge"
    if wavelength_nm >= 760:
        return "nir"
    return None


def dataset_wavelengths(src: Any) -> list[float] | None:
    for key, value in src.tags().items():
        if "wavelength" not in key.lower():
            continue
        numbers = re.findall(r"\d+(?:\.\d+)?", str(value))
        if len(numbers) < src.count:
            continue
        wavelengths = [float(number) for number in numbers[: src.count]]
        return [number * 1000 if 0 < number < 10 else number for number in wavelengths]
    return None


def rgb_bands(
    src: Any,
    *,
    sensor: str | None = None,
    fallback_path: Path | None = None,
) -> tuple[int, int, int]:
    roles: dict[str, int] = {}
    for index, interpretation in enumerate(src.colorinterp, 1):
        role = str(getattr(interpretation, "name", interpretation)).lower()
        if role in {"red", "green", "blue"}:
            roles.setdefault(role, index)

    wavelengths = dataset_wavelengths(src)
    for index in range(1, src.count + 1):
        description = src.descriptions[index - 1] or ""
        tags = src.tags(index)
        metadata_text = " ".join([description, *[f"{key} {value}" for key, value in tags.items()]])
        role = band_role_from_text(metadata_text)
        if role not in {"red", "green", "blue"}:
            wavelength = next(
                (
                    wavelength_nm(str(value))
                    for key, value in tags.items()
                    if "wavelength" in key.lower()
                ),
                None,
            )
            if wavelength is None and wavelengths:
                wavelength = wavelengths[index - 1]
            role = band_role_from_wavelength(wavelength)
        if role in {"red", "green", "blue"}:
            roles.setdefault(role, index)

    selected_sensor = sensor
    is_multispectral = selected_sensor in {"mavic3m", "micasense"} or src.count > 4
    if not is_multispectral and src.count in {3, 4}:
        alpha_index = next(
            (
                index
                for index, interpretation in enumerate(src.colorinterp, 1)
                if str(getattr(interpretation, "name", interpretation)).lower() == "alpha"
            ),
            None,
        )
        if src.count == 3 or alpha_index == 4:
            roles.setdefault("red", 1)
            roles.setdefault("green", 2)
            roles.setdefault("blue", 3)
    elif selected_sensor == "mavic3m" and src.count >= 4:
        roles.setdefault("red", 2)
        roles.setdefault("green", 1)
        roles.setdefault("blue", 3)

    missing = [role for role in ("red", "green", "blue") if role not in roles]
    if missing:
        details = ", ".join(
            f"banda {index}: {src.descriptions[index - 1] or 'sin descripcion'}; tags={src.tags(index)}"
            for index in range(1, src.count + 1)
        )
        raster_name = Path(src.name).name if getattr(src, "name", None) else "raster"
        raise ValueError(
            f"No se pudieron identificar las bandas RGB del raster '{raster_name}'. "
            f"Faltan metadatos para: {', '.join(missing)}. {details}"
        )
    return roles["red"], roles["green"], roles["blue"]


def multispectral_band_roles(
    src: Any,
    *,
    sensor: str | None = None,
    fallback_path: Path | None = None,
) -> dict[str, int]:
    roles: dict[str, int] = {}
    wavelengths = dataset_wavelengths(src)
    for index in range(1, src.count + 1):
        description = src.descriptions[index - 1] or ""
        tags = src.tags(index)
        metadata_text = " ".join([description, *[f"{key} {value}" for key, value in tags.items()]])
        role = band_role_from_text(metadata_text)
        if role not in {"blue", "green", "red", "rededge", "nir"}:
            wavelength = next(
                (
                    wavelength_nm(str(value))
                    for key, value in tags.items()
                    if "wavelength" in key.lower()
                ),
                None,
            )
            if wavelength is None and wavelengths:
                wavelength = wavelengths[index - 1]
            role = band_role_from_wavelength(wavelength)
        if role in {"blue", "green", "red", "rededge", "nir"}:
            roles.setdefault(role, index)

    selected_sensor = sensor
    if selected_sensor == "mavic3m" and src.count >= 4:
        roles.setdefault("green", 1)
        roles.setdefault("red", 2)
        roles.setdefault("rededge", 3)
        roles.setdefault("nir", 4)
    elif selected_sensor == "micasense":
        if src.count >= 6:
            roles.setdefault("blue", 1)
            roles.setdefault("green", 2)
            roles.setdefault("red", 4)
            roles.setdefault("rededge", 5)
            roles.setdefault("nir", 6)
        elif src.count >= 5:
            roles.setdefault("blue", 1)
            roles.setdefault("green", 2)
            roles.setdefault("red", 3)
            roles.setdefault("rededge", 4)
            roles.setdefault("nir", 5)
    return roles
