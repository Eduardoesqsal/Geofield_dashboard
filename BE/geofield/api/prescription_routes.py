"""Rutas de zonificacion y prescripcion."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, TypeVar

import rasterio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ValidationError

from geofield.api.request_utils import geojson_geometry, payload_object, require_string
from geofield.api.schemas import ClassificationPayload, PrescriptionPayload
from geofield.services.raster_service import RasterService


PayloadModel = TypeVar("PayloadModel", bound=BaseModel)
NUMERIC_CLASSIFICATION_FIELDS = {
    "zone_count",
    "cell_size_m",
    "grid_angle_deg",
    "detail_level",
}


def _parse_payload(model: type[PayloadModel], payload: dict[str, Any]) -> PayloadModel:
    try:
        validator = getattr(model, "model_validate", None)
        if validator is not None:
            return validator(payload)
        return model.parse_obj(payload)
    except ValidationError as exc:
        fields = {str(error.get("loc", [""])[0]) for error in exc.errors()}
        if fields & NUMERIC_CLASSIFICATION_FIELDS:
            raise HTTPException(422, "Zonas, tamano de celda, rotacion y detalle deben ser numericos.") from exc
        raise HTTPException(422, str(exc)) from exc


def register_prescription_routes(
    router: APIRouter,
    raster: RasterService,
    output_dir: Path,
    ensure_orthomosaic: Callable[[str | None], None],
) -> None:
    """Registra rutas asociadas a clasificacion, tiles y descarga JSON."""

    @router.post("/ndvi_zoning")
    async def create_ndvi_zoning(request: Request) -> dict[str, Any]:
        payload = payload_object(await request.json())
        require_string(
            payload,
            "orthomosaic_id",
            "Selecciona un vuelo antes de generar la zonificacion.",
        )
        model = _parse_payload(ClassificationPayload, payload)
        geometry = geojson_geometry(payload)
        ensure_orthomosaic(model.orthomosaic_id)
        try:
            return raster.ndvi_zoning_map(
                geometry,
                model.index_name,
                model.zone_count,
                model.cell_size_m,
                model.grid_angle_deg,
                model.classification_method,
                model.cell_value_mode,
                model.manual_breaks,
                model.detail_level,
                model.analysis_min,
                model.analysis_max,
            )
        except (ValueError, rasterio.errors.RasterioIOError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/prescriptions")
    async def create_prescription(request: Request) -> dict[str, Any]:
        payload = payload_object(await request.json())
        require_string(
            payload,
            "orthomosaic_id",
            "Selecciona un vuelo antes de generar la prescripción.",
        )
        model = _parse_payload(PrescriptionPayload, payload)
        geometry = geojson_geometry(payload)
        ensure_orthomosaic(model.orthomosaic_id)
        try:
            return raster.prescription_map_with_doses(
                geometry,
                model.index_name,
                model.zone_count,
                model.cell_size_m,
                model.grid_angle_deg,
                model.classification_method,
                model.cell_value_mode,
                model.manual_breaks,
                model.detail_level,
                model.analysis_min,
                model.analysis_max,
                model.doses,
            )
        except (ValueError, rasterio.errors.RasterioIOError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/tiles/prescription/{artifact_id}/{z}/{x}/{y}.png")
    def prescription_tile(artifact_id: str, z: int, x: int, y: int) -> Response:
        try:
            return Response(
                raster.prescription_tile(artifact_id, z, x, y),
                media_type="image/png",
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/prescriptions/{artifact_id}/download.json")
    def download_prescription_json(artifact_id: str) -> FileResponse:
        if len(artifact_id) != 32 or any(character not in "0123456789abcdef" for character in artifact_id):
            raise HTTPException(404, "La prescripcion solicitada no es valida.")
        path = output_dir / "prescriptions" / f"{artifact_id}.json"
        if not path.is_file():
            raise HTTPException(404, "La prescripcion ya no esta disponible.")
        return FileResponse(
            path,
            media_type="application/json",
            filename=f"prescripcion_{artifact_id[:8]}.json",
        )
