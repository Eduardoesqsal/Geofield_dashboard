from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from typing import Any

import rasterio
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from shapely.geometry import shape
from shapely.ops import unary_union

from geofield.errors import OrthomosaicNotFoundError, RoiAnalysisNotFoundError, SupabaseNotConfiguredError
from geofield.services.application_service import OrthomosaicApplicationService, RoiApplicationService
from geofield.services.raster_service import RasterService
from geofield.services.supabase_service import SupabaseService
from geofield.services.tree_service import TreeService


def create_router(raster: RasterService, output_dir: Path, base_dir: Path, supabase: SupabaseService) -> APIRouter:
    router = APIRouter()
    orthomosaics = OrthomosaicApplicationService(raster, supabase)
    rois = RoiApplicationService(raster, supabase)

    def payload_geometry(payload: Any) -> Any:
        if not isinstance(payload, dict) or "geojson" not in payload:
            raise HTTPException(400, "No GeoJSON recibido")
        geojson = payload["geojson"]
        if not isinstance(geojson, dict):
            raise HTTPException(400, "El campo geojson debe ser un objeto GeoJSON")
        if geojson.get("type") == "Feature":
            geojson = geojson.get("geometry")
        elif geojson.get("type") == "FeatureCollection":
            geometries = [item.get("geometry") for item in geojson.get("features", []) if isinstance(item, dict) and isinstance(item.get("geometry"), dict)]
            if not geometries:
                raise HTTPException(400, "El FeatureCollection no contiene geometrías")
            try:
                return unary_union([shape(item) for item in geometries])
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "Geometrías GeoJSON inválidas") from exc
        elif "geometry" in geojson and geojson.get("type") != "FeatureCollection":
            geojson = geojson["geometry"]
        if not isinstance(geojson, dict) or not geojson.get("type") or "coordinates" not in geojson:
            raise HTTPException(400, "Se requiere una geometría GeoJSON válida")
        try:
            return shape(geojson)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Geometría GeoJSON inválida") from exc

    def ensure_orthomosaic(orthomosaic_id: str | None) -> None:
        if not orthomosaic_id:
            return
        try:
            orthomosaics.activate_orthomosaic(orthomosaic_id)
        except SupabaseNotConfiguredError as exc:
            raise HTTPException(503, str(exc)) from exc
        except OrthomosaicNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"No se pudo activar el ortomosaico {orthomosaic_id}: {exc}") from exc

    @router.get("/")
    def index() -> FileResponse:
        index_path = base_dir / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="Frontend no encontrado en el backend.")
        return FileResponse(index_path)

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/supabase/health")
    def supabase_health() -> dict[str, Any]:
        if not supabase.enabled:
            return {"status": "not_configured", "bucket": supabase.settings.supabase_bucket}
        try:
            result = supabase.healthcheck()
            return {"status": "ok", "bucket": supabase.settings.supabase_bucket, **result}
        except SupabaseNotConfiguredError as exc:
            raise HTTPException(503, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"Supabase no responde correctamente: {exc}") from exc

    @router.get("/orthomosaics")
    def list_orthomosaics(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
        try:
            items = supabase.list_orthomosaics(limit)
        except SupabaseNotConfiguredError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {"status": "ok", "items": items}

    @router.post("/orthomosaics/upload")
    async def upload_orthomosaic(
        file: UploadFile = File(...),
        capture_date: date = Form(...),
        sensor_type: str = Form(...),
        name: str | None = Form(None),
        activate: bool = Form(True),
    ) -> dict[str, Any]:
        content = await file.read()
        if not content:
            raise HTTPException(400, "No se recibió ningún archivo.")
        try:
            result = orthomosaics.upload_orthomosaic(
                content=content,
                filename=file.filename or "upload.tif",
                capture_date=capture_date,
                sensor_type=sensor_type,
                name=name,
                content_type=file.content_type,
                activate=activate,
            )
            return {"status": "ok", **result}
        except SupabaseNotConfiguredError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"No se pudo guardar el ortomosaico en Supabase: {exc}") from exc

    @router.post("/orthomosaics/{orthomosaic_id}/activate")
    def activate_orthomosaic(orthomosaic_id: str) -> dict[str, Any]:
        try:
            record = orthomosaics.activate_orthomosaic(orthomosaic_id)
            return {"status": "ok", "orthomosaic": record}
        except SupabaseNotConfiguredError as exc:
            raise HTTPException(503, str(exc)) from exc
        except OrthomosaicNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"No se pudo activar el ortomosaico {orthomosaic_id}: {exc}") from exc

    @router.delete("/orthomosaics/{orthomosaic_id}")
    def delete_orthomosaic(orthomosaic_id: str) -> dict[str, Any]:
        try:
            record = orthomosaics.delete_orthomosaic(orthomosaic_id)
            return {"status": "ok", "orthomosaic": record}
        except OrthomosaicNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (SupabaseNotConfiguredError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"No se pudo eliminar el ortomosaico: {exc}") from exc

    @router.get("/rois")
    def list_rois() -> dict[str, Any]:
        return {"status": "ok", "items": supabase.list_rois()}

    @router.post("/rois")
    async def create_roi(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
            geojson = payload.get("geojson") if isinstance(payload, dict) else None
            if not isinstance(geojson, dict): raise HTTPException(400, "Se requiere un GeoJSON válido.")
            payload_geometry({"geojson": geojson})
            name = str(payload.get("name") or "ROI").strip() or "ROI"
            record = rois.create_roi(name=name, geojson=geojson, orthomosaic_id=payload.get("orthomosaic_id"))
            return {"status": "ok", "roi": record}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"No se pudo guardar el ROI en Supabase: {exc}") from exc

    @router.patch("/rois/{roi_id}")
    async def update_roi(roi_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        return {"status": "ok", "roi": supabase.set_roi_active(roi_id, bool(payload.get("is_active")))}

    @router.delete("/rois/{roi_id}")
    def delete_roi(roi_id: str) -> dict[str, str]:
        supabase.delete_roi(roi_id)
        return {"status": "ok"}

    @router.get("/rois/{roi_id}/analyses")
    def roi_analyses(roi_id: str, index: str | None = Query(None)) -> dict[str, Any]:
        try:
            normalized_index = index.upper() if index else None
            return {"status": "ok", "items": supabase.list_roi_analyses(roi_id, normalized_index)}
        except Exception as exc:
            raise HTTPException(502, "No se pudo consultar el historial. Ejecuta BE/sql/002_create_roi_analyses.sql en Supabase.") from exc

    @router.post("/rois/{roi_id}/analyses")
    async def save_roi_analysis(roi_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        orthomosaic_id = str(payload.get("orthomosaic_id") or "")
        if not orthomosaic_id: raise HTTPException(400, "Selecciona un ortomosaico.")
        selected_index = str(payload.get("index") or "").upper() or None
        selected_stats = payload.get("stats")
        roi = supabase.get_roi(roi_id)
        ensure_orthomosaic(orthomosaic_id)
        geometry = payload_geometry({"geojson": roi["geojson"]})
        try:
            record = rois.save_roi_analysis(
                roi_id=roi_id,
                orthomosaic_id=orthomosaic_id,
                geometry=geometry,
                selected_index=selected_index,
                selected_stats=selected_stats,
            )
            if selected_index and selected_stats:
                persisted_stats = record.get(selected_index.lower())
                normalized_stats = rois.normalize_roi_analysis_stats(selected_stats)
                if not rois.stats_match(persisted_stats, normalized_stats):
                    raise HTTPException(
                        502,
                        f"Se guardo un registro distinto al resumen numerico actual de {selected_index}. "
                        "La base de datos devolvio estadisticas diferentes a las enviadas desde el histograma.",
                    )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            print(f"[ROI_ANALYSIS_SAVE_ERROR] {exc}", flush=True)
            raise HTTPException(
                502,
                f"No se pudieron guardar las estadisticas en index_results: {exc}",
            ) from exc
        return {"status": "ok", "analysis": record}

    async def save_global_analysis(request: Request) -> dict[str, Any]:
        payload = await request.json()
        orthomosaic_id = str(payload.get("orthomosaic_id") or "")
        if not orthomosaic_id:
            raise HTTPException(400, "Selecciona un ortomosaico.")
        ensure_orthomosaic(orthomosaic_id)
        try:
            record = rois.save_global_analysis(orthomosaic_id=orthomosaic_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, "No se pudieron guardar las estadísticas globales. Ejecuta BE/sql/003_create_global_analyses.sql en Supabase.") from exc
        return {"status": "ok", "analysis": record}

    @router.delete("/rois/{roi_id}/analyses/{analysis_id}")
    def delete_roi_analysis(roi_id: str, analysis_id: str) -> dict[str, str]:
        try:
            supabase.delete_roi_analysis(roi_id, analysis_id)
        except RoiAnalysisNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, "No se pudo eliminar la estadística de Supabase.") from exc
        return {"status": "ok"}

    def delete_global_analysis(analysis_id: str) -> dict[str, str]:
        try:
            supabase.delete_global_analysis(analysis_id)
        except RoiAnalysisNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, "No se pudo eliminar la estadística global de Supabase.") from exc
        return {"status": "ok"}

    @router.get("/bounds")
    def bounds(orthomosaic_id: str | None = Query(None)) -> dict[str, Any]:
        ensure_orthomosaic(orthomosaic_id)
        raster.ensure_overlay()
        path = output_dir / "bounds_overlay.txt"
        return {"status": "ok", "bounds": ast.literal_eval(path.read_text(encoding="utf-8"))}

    @router.get("/tiles/rgb/{z}/{x}/{y}.png")
    def rgb_tile(z: int, x: int, y: int, orthomosaic_id: str | None = Query(None)) -> Response:
        ensure_orthomosaic(orthomosaic_id)
        return Response(raster.tile("rgb", z, x, y), media_type="image/png")

    @router.get("/tiles/crop/{crop_id}/{z}/{x}/{y}.png")
    def crop_tile(crop_id: str, z: int, x: int, y: int) -> Response:
        try:
            return Response(raster.crop_tile(crop_id, z, x, y), media_type="image/png", headers={"Cache-Control": "no-store"})
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/tiles/crop-index/{name}/{crop_id}/{z}/{x}/{y}.png")
    def crop_index_tile(name: str, crop_id: str, z: int, x: int, y: int, low: float | None = Query(None), high: float | None = Query(None)) -> Response:
        try:
            return Response(raster.crop_index_tile(name.upper(), crop_id, z, x, y, low, high), media_type="image/png", headers={"Cache-Control": "no-store"})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/tiles/ndvi/{z}/{x}/{y}.png")
    def ndvi_tile(z: int, x: int, y: int, low: float = Query(-0.05), high: float = Query(1.0), orthomosaic_id: str | None = Query(None)) -> Response:
        ensure_orthomosaic(orthomosaic_id)
        try:
            return Response(raster.tile("ndvi", z, x, y, low, high), media_type="image/png")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/tiles/index/{name}/{z}/{x}/{y}.png")
    def index_tile(
        name: str,
        z: int,
        x: int,
        y: int,
        low: float | None = Query(None),
        high: float | None = Query(None),
        orthomosaic_id: str | None = Query(None),
    ) -> Response:
        ensure_orthomosaic(orthomosaic_id)
        try:
            return Response(
                raster.index_tile(name.upper(), z, x, y, low, high),
                media_type="image/png",
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/rgb_data")
    def rgb_data() -> JSONResponse:
        return JSONResponse({"status": "error", "message": "Usa /tiles/rgb/{z}/{x}/{y}.png para evitar cargar el RGB completo."}, status_code=503)

    @router.post("/ortho_analysis")
    async def ortho_analysis(request: Request, type: str = Query("rgb"), sensor: str = Query("rgb")) -> dict[str, Any]:
        if type not in {"rgb", "multispectral"}:
            raise HTTPException(400, "Tipo de ortomosaico no válido")
        if sensor not in {"mavic3m", "mavic3rgb", "rgb", "micasense"}:
            raise HTTPException(400, "Sensor no válido")
        expected_type = "multispectral" if sensor in {"mavic3m", "micasense"} else "rgb"
        if type != expected_type:
            raise HTTPException(400, "El tipo de ortomosaico no coincide con el sensor")
        content = await request.body()
        if not content:
            raise HTTPException(400, "No se recibió ningún ortomosaico")
        filename = request.headers.get("x-filename", "upload.tif")
        try:
            return raster.analyze_uploaded(content, type, filename, sensor)
        except (ValueError, rasterio.errors.RasterioIOError) as exc:
            raise HTTPException(422, f"No se pudo leer el ortomosaico: {exc}") from exc

    @router.get("/ndvi_data")
    def ndvi_data(orthomosaic_id: str | None = Query(None)) -> dict[str, Any]:
        ensure_orthomosaic(orthomosaic_id)
        try:
            data = raster.ndvi_data()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return data | {"matrix": data["ndvi_matrix"], "mask": data["ndvi_mask"]}

    @router.get("/vegetation_indices/{name}")
    def vegetation_index(name: str, orthomosaic_id: str | None = Query(None)) -> dict[str, Any]:
        ensure_orthomosaic(orthomosaic_id)
        try:
            return raster.vegetation_index_data(name.upper())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/roi_ndvi")
    async def roi_ndvi(request: Request, orthomosaic_id: str | None = Query(None)) -> dict[str, Any]:
        ensure_orthomosaic(orthomosaic_id)
        payload = await request.json()
        try:
            data = raster.roi_ndvi(payload_geometry(payload))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return data | {"matrix": data["ndvi_matrix"], "mask": data["ndvi_mask"]}

    @router.post("/roi_indices")
    async def roi_indices(request: Request, orthomosaic_id: str | None = Query(None)) -> dict[str, Any]:
        ensure_orthomosaic(orthomosaic_id)
        payload = await request.json()
        try:
            geometry = payload_geometry(payload)
            indices = {name: raster.roi_vegetation_index(geometry, name) for name in ("NDVI", "NDWI", "NDRE")}
            ndvi = indices["NDVI"]
            indices["NDVI"] = ndvi | {"matrix": ndvi["ndvi_matrix"], "mask": ndvi["ndvi_mask"]}
            return {"status": "ok", "indices": indices}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/roi_indices/{name}")
    async def roi_index(
        name: str,
        request: Request,
        orthomosaic_id: str | None = Query(None),
    ) -> dict[str, Any]:
        ensure_orthomosaic(orthomosaic_id)
        payload = await request.json()
        try:
            data = raster.roi_vegetation_index(
                payload_geometry(payload),
                name.upper(),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if name.upper() == "NDVI":
            return data | {"matrix": data["ndvi_matrix"], "mask": data["ndvi_mask"]}
        return data

    @router.post("/recortar")
    async def crop(request: Request, orthomosaic_id: str | None = Query(None)) -> dict[str, Any]:
        ensure_orthomosaic(orthomosaic_id)
        payload = await request.json()
        return raster.crop(payload_geometry(payload))

    @router.post("/crop_tiles")
    async def crop_tiles(request: Request, orthomosaic_id: str | None = Query(None)) -> dict[str, Any]:
        ensure_orthomosaic(orthomosaic_id)
        payload = await request.json()
        return raster.begin_crop_tiles(payload_geometry(payload))

    @router.post("/tree_points")
    async def tree_points(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict) or "geojson" not in payload:
            raise HTTPException(400, "No GeoJSON recibido")
        try:
            return TreeService.process(payload["geojson"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router
