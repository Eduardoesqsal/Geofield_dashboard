"""Reproduce la validacion visual y metrica de Zone detail sobre el caso Pix4D local."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyproj
import rasterio
from PIL import Image, ImageDraw
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import transform as project_geometry
from shapely.ops import unary_union

from geofield.config import Settings
from geofield.services.raster_service import RasterService


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "BE"
REFERENCE = ROOT / "referencias_pix4d"
SOURCE = BACKEND / "uploads" / "2026-09-01" / "d5f09b5ed5f0471a8951b66ee96d513e_Ortomosaico.data.tif"
PREVIOUS_COARSE = BACKEND / "static" / "prescriptions" / "c3c8f14c38274abbb5fb2e682bb6c7a7.tif"
OUTPUT = BACKEND / "static" / "validation"
DETAIL_LEVELS = (1.0, 0.75, 0.50, 0.25, 0.0)
REFERENCE_FRAMES = ("A.png", "C.png", "F.png", "H.png", "K.png")


def reference_roi() -> object:
    with rasterio.open(PREVIOUS_COARSE) as source:
        visible = source.read(4) > 0
        geometries = [
            shape(item)
            for item, value in shapes(
                visible.astype(np.uint8),
                mask=visible,
                transform=source.transform,
            )
            if value
        ]
        metric_geometry = unary_union(geometries).buffer(0)
        return project_geometry(
            pyproj.Transformer.from_crs(source.crs, "EPSG:4326", always_xy=True).transform,
            metric_geometry,
        )


def zone_image(zones: np.ndarray, palette: np.ndarray, scale: int = 6) -> Image.Image:
    rgba = np.zeros((*zones.shape, 4), dtype=np.uint8)
    for class_id, color in enumerate(palette, 1):
        selected = zones == class_id
        rgba[selected, :3] = color
        rgba[selected, 3] = 255
    image = Image.fromarray(rgba, mode="RGBA")
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def framed(image: Image.Image, title: str, width: int = 520, height: int = 620) -> Image.Image:
    canvas = Image.new("RGB", (width, height), "white")
    content = image.convert("RGBA")
    content.thumbnail((width - 20, height - 55), Image.Resampling.LANCZOS)
    x = (width - content.width) // 2
    y = 42 + (height - 52 - content.height) // 2
    canvas.paste(content, (x, y), content if content.mode == "RGBA" else None)
    ImageDraw.Draw(canvas).text((12, 12), title, fill="black")
    return canvas


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    service = RasterService(
        Settings(
            base_dir=BACKEND,
            raster_path=SOURCE,
            output_dir=BACKEND / "static",
            cache_dir=BACKEND / "cache",
            uploads_dir=BACKEND / "uploads",
        ),
    )
    service.active_path = SOURCE
    service.sensor = "mavic3m"
    data = service._prepare_index_classification(
        "NDVI",
        reference_roi(),
        zone_count=4,
        cell_size_m=3.0,
        analysis_min=0.040,
        analysis_max=0.952,
        classification_method="quantiles",
        cell_value_mode="mean",
        detail_level=1.0,
    )
    metrics: dict[str, object] = {
        "source": str(SOURCE.relative_to(ROOT)),
        "cell_size_m": 3.0,
        "thresholds": data["thresholds"],
        "levels": [],
    }
    results: list[np.ndarray] = []
    for detail_level in DETAIL_LEVELS:
        zones = service._regularize_zones(
            data["initial_zones"],
            data["initial_zones"] > 0,
            data["index_values"],
            np.asarray(data["thresholds"], dtype=np.float32),
            detail_level,
            data["cell_areas_m2"],
        )
        parameters = service._spatial_detail_parameters(
            detail_level,
            data["initial_zones"] > 0,
            data["cell_areas_m2"],
        )
        snapshot = service._zone_debug_snapshot(
            zones,
            data["initial_zones"] > 0,
            data["index_values"],
            data["cell_areas_m2"],
            4,
            float(parameters["minimum_region_area_m2"]),
        )
        metrics["levels"].append(
            {"detail_level": detail_level, "parameters": parameters, **snapshot},
        )
        results.append(zones)

    (OUTPUT / "zone_detail_metrics.json").write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )

    rows: list[Image.Image] = []
    for detail_level, zones, reference_name in zip(
        DETAIL_LEVELS,
        results,
        REFERENCE_FRAMES,
        strict=True,
    ):
        ours = framed(zone_image(zones, data["colors"]), f"GeoField detail={detail_level:.2f}")
        reference = Image.open(REFERENCE / reference_name).convert("RGB")
        reference = reference.crop((560, 25, 1360, reference.height - 15))
        pix4d = framed(reference, f"PIX4Dfields {reference_name}")
        row = Image.new("RGB", (ours.width + pix4d.width, ours.height), "white")
        row.paste(ours, (0, 0))
        row.paste(pix4d, (ours.width, 0))
        rows.append(row)
    sequence = Image.new("RGB", (rows[0].width, rows[0].height * len(rows)), "white")
    for index, row in enumerate(rows):
        sequence.paste(row, (0, index * row.height))
    sequence.save(OUTPUT / "zone_detail_sequence.png", optimize=True)

    previous = Image.open(PREVIOUS_COARSE).convert("RGBA")
    comparison_panels = [
        framed(zone_image(data["initial_zones"], data["colors"]), "Clasificacion inicial / Fine"),
        framed(previous, "Implementacion anterior / Coarse"),
        framed(zone_image(results[-1], data["colors"]), "Nueva implementacion / Coarse"),
        framed(
            Image.open(REFERENCE / "K.png").convert("RGB").crop((560, 25, 1360, 905)),
            "PIX4Dfields / Coarse",
        ),
    ]
    comparison = Image.new("RGB", (sum(panel.width for panel in comparison_panels), comparison_panels[0].height), "white")
    x = 0
    for panel in comparison_panels:
        comparison.paste(panel, (x, 0))
        x += panel.width
    comparison.save(OUTPUT / "zone_detail_comparison.png", optimize=True)

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
