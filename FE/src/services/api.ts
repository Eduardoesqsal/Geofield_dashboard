/**
 * Cliente HTTP tipado del frontend.
 * Expone contratos y funciones para hablar con el backend sin dispersar URLs,
 * payloads ni transformaciones de respuesta por toda la aplicación.
 */
import type { TreeCollection } from "../types/geo";

// Contratos serializados por la API FastAPI.
export interface BoundsResponse {
  bounds: [[number, number], [number, number]];
}

export interface NdviResponse {
  matrix: number[][];
  mask?: number[][];
  rgb_matrix?: number[][][];
  bounds: [[number, number], [number, number]];
}

export interface CropResponse extends BoundsResponse {
  overlay_path: string;
}
export interface CropTilesResponse extends BoundsResponse {
  crop_id: string;
}

export type OrthoMode = "rgb" | "multispectral";
export type OrthoSensor = "mavic3m" | "mavic3rgb" | "rgb" | "micasense";

export interface OrthoAnalysisResponse {
  bounds: [[number, number], [number, number]];
  rgb_matrix?: number[][][];
  ndvi_matrix?: number[][];
  mask?: number[][];
}

export interface OrthomosaicUploadResponse {
  status: string;
  orthomosaic: {
    id: string;
    name: string;
    capture_date: string;
    sensor_type: string;
  };
  analysis?: OrthoAnalysisResponse;
}

export interface OrthomosaicRecord {
  id: string;
  name: string;
  original_filename: string;
  capture_date: string;
  sensor_type: string;
}
export interface RoiRecord {
  id: string;
  name: string;
  geojson: unknown;
  orthomosaic_id: string | null;
  is_active: boolean;
  created_at: string;
}
export interface RoiAnalysisStats {
  count: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  median?: number | null;
  standard_deviation: number | null;
  p10?: number | null;
  p25?: number | null;
  p75?: number | null;
  p90?: number | null;
  range_min?: number | null;
  range_max?: number | null;
}
export interface SaveRoiAnalysisPayload {
  index: "NDVI" | "NDWI" | "NDRE";
  stats: RoiAnalysisStats;
}
export interface RoiAnalysisRecord {
  id: string;
  roi_id: string;
  orthomosaic_id: string;
  ndvi: RoiAnalysisStats;
  ndwi: RoiAnalysisStats | null;
  ndre: RoiAnalysisStats | null;
  created_at: string;
  orthomosaics: { name: string; capture_date: string } | null;
}

/** Estadísticas calculadas por el normalizador canónico de detecciones. */
export interface TreePointsStats {
  count: number;
  diameter_min: number | null;
  diameter_max: number | null;
  diameter_mean: number | null;
  class_counts: Record<"small" | "medium" | "large" | "unknown", number>;
  has_diameter: boolean;
}

const API_BASE_URL = (import.meta.env.VITE_BACKEND_URL ?? "").replace(
  /\/$/,
  "",
);

/** Resuelve rutas relativas mediante el proxy de Vite o una URL configurada. */
export const backendUrl = (path: string) => `${API_BASE_URL}${path}`;

/**
 * Cliente HTTP común: exige JSON incluso en errores para evitar interpretar
 * páginas HTML del servidor de desarrollo como respuestas válidas.
 */
async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(backendUrl(url), options);
  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();

  if (!contentType.includes("application/json")) {
    throw new Error(
      response.ok
        ? `La ruta ${url} devolvió HTML en lugar de JSON. Revisa la URL/proxy del backend.`
        : `Error ${response.status} en ${url}. El backend no está disponible o la ruta no existe.`,
    );
  }

  const data = JSON.parse(body) as T & { message?: string; detail?: string };

  if (!response.ok) {
    throw new Error(data.message ?? data.detail ?? `Error en ${url}`);
  }

  return data;
}

/** Fachada tipada de todos los endpoints consumidos por el dashboard. */
export const dashboardApi = {
  bounds: (orthomosaicId?: string) =>
    request<BoundsResponse>(
      `/bounds${orthomosaicId ? `?orthomosaic_id=${encodeURIComponent(orthomosaicId)}` : ""}`,
    ),
  ndvi: () => request<NdviResponse>("/ndvi_data"),
  vegetationIndex: (name: "NDWI" | "NDRE") =>
    request<NdviResponse>(`/vegetation_indices/${name}`),
  roiVegetationIndex: (name: "NDWI" | "NDRE", geojson: unknown) =>
    request<NdviResponse>(`/roi_indices/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geojson }),
    }),
  orthomosaics: () =>
    request<{ status: string; items: OrthomosaicRecord[] }>("/orthomosaics"),
  deleteOrthomosaic: (id: string) =>
    request<{ status: string }>(`/orthomosaics/${id}`, { method: "DELETE" }),
  activateOrthomosaic: (id: string) =>
    request<{ status: string; orthomosaic: OrthomosaicRecord }>(
      `/orthomosaics/${id}/activate`,
      { method: "POST" },
    ),
  rois: () => request<{ status: string; items: RoiRecord[] }>("/rois"),
  saveRoi: (geojson: unknown, orthomosaicId: string | null, name = "ROI") =>
    request<{ status: string; roi: RoiRecord }>("/rois", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, geojson, orthomosaic_id: orthomosaicId }),
    }),
  setRoiActive: (id: string, active: boolean) =>
    request<{ status: string; roi: RoiRecord }>(`/rois/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: active }),
    }),
  deleteRoi: (id: string) =>
    request<{ status: string }>(`/rois/${id}`, { method: "DELETE" }),
  saveRoiAnalysis: (
    roiId: string,
    orthomosaicId: string,
    payload: SaveRoiAnalysisPayload,
  ) =>
    request<{ status: string; analysis: RoiAnalysisRecord }>(
      `/rois/${roiId}/analyses`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          orthomosaic_id: orthomosaicId,
          index: payload.index,
          stats: payload.stats,
        }),
      },
    ),
  roiAnalyses: (roiId: string, index: "NDVI" | "NDWI" | "NDRE") =>
    request<{ status: string; items: RoiAnalysisRecord[] }>(
      `/rois/${roiId}/analyses?index=${encodeURIComponent(index)}&fresh=${Date.now()}`,
      // Las comparaciones y exportaciones deben reflejar eliminaciones recientes.
      { cache: "no-store", headers: { "Cache-Control": "no-cache" } },
    ),
  deleteRoiAnalysis: (roiId: string, analysisId: string) =>
    request<{ status: string }>(`/rois/${roiId}/analyses/${analysisId}`, {
      method: "DELETE",
    }),
  roi: (geojson: unknown) =>
    request<NdviResponse>("/roi_ndvi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geojson }),
    }),
  roiIndices: (geojson: unknown) =>
    request<{
      status: string;
      indices: Record<"NDVI" | "NDWI" | "NDRE", NdviResponse>;
    }>("/roi_indices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geojson }),
    }),
  crop: (geojson: unknown) =>
    request<CropResponse>("/recortar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geojson }),
    }),
  cropTiles: (geojson: unknown) =>
    request<CropTilesResponse>("/crop_tiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geojson }),
    }),
  treePoints: (geojson: TreeCollection) =>
    request<{
      status: string;
      geojson: TreeCollection;
      stats: TreePointsStats;
    }>("/tree_points", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geojson }),
    }),
  orthoAnalysis: (file: File, sensor: OrthoSensor) => {
    const type: OrthoMode =
      sensor === "mavic3m" || sensor === "micasense" ? "multispectral" : "rgb";
    return request<OrthoAnalysisResponse>(
      `/ortho_analysis?type=${type}&sensor=${sensor}`,
      {
        method: "POST",
        headers: {
          "Content-Type": file.type || "application/octet-stream",
          "X-Filename": file.name,
        },
        body: file,
      },
    );
  },
  uploadOrthomosaic: (file: File, sensor: OrthoSensor, captureDate: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("capture_date", captureDate);
    form.append("sensor_type", sensor);
    form.append("name", file.name.replace(/\.[^.]+$/, ""));
    form.append("activate", "true");
    return request<OrthomosaicUploadResponse>("/orthomosaics/upload", {
      method: "POST",
      body: form,
    });
  },
};
