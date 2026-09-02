/**
 * Cliente HTTP tipado del frontend.
 * Expone contratos y funciones para hablar con el backend sin dispersar URLs,
 * payloads ni transformaciones de respuesta por toda la aplicación.
 */
import type { TreeCollection } from "../types/geo";

// Contratos serializados por la API FastAPI.
export interface BoundsResponse {
  bounds: [[number, number], [number, number]];
  tile_version?: string;
}

export interface NdviResponse {
  matrix: number[][];
  mask?: number[][];
  rgb_matrix?: number[][][];
  bounds: [[number, number], [number, number]];
  range_min?: number | null;
  range_max?: number | null;
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
  tile_version?: string;
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
    agricultural_cycle_id: string | null;
  };
  analysis?: OrthoAnalysisResponse;
}

export interface AgriculturalCycleRecord {
  id: string;
  name: string;
  crop_name: string | null;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  created_at: string;
}

export interface CreateAgriculturalCyclePayload {
  name: string;
  crop_name?: string;
  start_date: string;
  end_date?: string;
  notes?: string;
}

export interface UpdateAgriculturalCyclePayload {
  name: string;
}

export interface OrthomosaicRecord {
  id: string;
  name: string;
  original_filename: string;
  capture_date: string;
  sensor_type: string;
  agricultural_cycle_id: string | null;
  display_order?: number | null;
}

export interface PrescriptionLegendEntry {
  class_id: number;
  label: string;
  ndvi_min: number;
  ndvi_max: number;
  percentile_min: number;
  percentile_max: number;
  mean: number;
  color: string;
  cell_count: number;
  initial_cell_count?: number;
  area_hectares: number;
  coverage_percent?: number;
  deviation_percent?: number;
  dosage?: number;
}

export interface PrescriptionHistogram {
  minimum: number;
  maximum: number;
  bins: number[];
  breaks: number[];
}

export interface NdviZoningResponse {
  status: string;
  stage: "zoning";
  title: string;
  index_name?: "NDVI" | "NDWI" | "NDRE";
  zoning_id: string;
  image_url: string;
  tile_url: string;
  bounds: [[number, number], [number, number]];
  zone_count: number;
  cell_size_m: number;
  grid_angle_deg: number;
  classification_method?: "quantiles" | "equal_intervals" | "manual";
  cell_value_mode?: "mean" | "min" | "max";
  detail_level?: number;
  field_mean?: number | null;
  histogram?: PrescriptionHistogram;
  thresholds?: number[];
  valid_cell_count: number;
  area_hectares: number;
  legend: PrescriptionLegendEntry[];
}

export interface PrescriptionMapResponse {
  status: string;
  stage: "prescription";
  title: string;
  index_name?: "NDVI" | "NDWI" | "NDRE";
  prescription_id: string;
  image_url: string;
  tile_url: string;
  json_url?: string;
  /** Compatibilidad con prescripciones generadas por versiones anteriores. */
  geojson_url?: string;
  bounds: [[number, number], [number, number]];
  zone_count: number;
  cell_size_m: number;
  grid_angle_deg: number;
  classification_method?: "quantiles" | "equal_intervals" | "manual";
  cell_value_mode?: "mean" | "min" | "max";
  detail_level?: number;
  field_mean?: number | null;
  histogram?: PrescriptionHistogram;
  thresholds?: number[];
  valid_cell_count: number;
  area_hectares: number;
  legend: PrescriptionLegendEntry[];
}

export interface UpdateOrthomosaicPayload {
  capture_date: string;
}
export interface RoiRecord {
  id: string;
  name: string;
  geojson: unknown;
  orthomosaic_id: string | null;
  agricultural_cycle_id?: string | null;
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

const API_BASE_URL = (() => {
  const configured = String(import.meta.env.VITE_BACKEND_URL ?? "").trim();
  if (configured) return configured.replace(/\/$/, "");
  // En desarrollo, si Vite vive en :3000 y no hay variable configurada,
  // hablamos directo con FastAPI en :8005 para no depender del proxy.
  if (typeof window !== "undefined" && window.location.port === "3000") {
    return `${window.location.protocol}//${window.location.hostname}:8005`;
  }
  return "";
})();

/** Resuelve rutas relativas mediante el proxy de Vite o una URL configurada. */
export const backendUrl = (path: string) => `${API_BASE_URL}${path}`;

/** Obtiene el JSON de prescripcion sin navegar hacia el origen del backend. */
export async function fetchPrescriptionJson(path: string): Promise<Blob> {
  const response = await fetch(backendUrl(path), {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    let message = `No se pudo descargar la prescripción (error ${response.status}).`;
    try {
      const data = (await response.json()) as { detail?: string; message?: string };
      message = data.detail ?? data.message ?? message;
    } catch {
      // Conserva el mensaje HTTP cuando la respuesta no es JSON.
    }
    throw new Error(message);
  }
  return response.blob();
}

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

async function download(url: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(backendUrl(url), { cache: "no-store" });
  if (!response.ok) {
    const body = await response.text();
    let message: string | undefined;
    try {
      const error = JSON.parse(body) as { detail?: string; message?: string };
      message = error.detail ?? error.message;
    } catch {
      // Las descargas pueden devolver texto plano desde proxies intermedios.
    }
    throw new Error(message ?? `Error ${response.status} en ${url}`);
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  return {
    blob: await response.blob(),
    filename: filename ?? "recorte_ortomosaico.tif",
  };
}

/** Fachada tipada de todos los endpoints consumidos por el dashboard. */
export const dashboardApi = {
  agriculturalCycles: () =>
    request<{ status: string; items: AgriculturalCycleRecord[] }>(
      "/agricultural_cycles",
    ),
  createAgriculturalCycle: (payload: CreateAgriculturalCyclePayload) =>
    request<{ status: string; cycle: AgriculturalCycleRecord }>(
      "/agricultural_cycles",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  updateAgriculturalCycle: (
    id: string,
    payload: UpdateAgriculturalCyclePayload,
  ) =>
    request<{ status: string; cycle: AgriculturalCycleRecord }>(
      `/agricultural_cycles/${id}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  deleteAgriculturalCycle: (id: string) =>
    request<{
      status: string;
      cycle: AgriculturalCycleRecord;
      deleted_orthomosaics: number;
      deleted_rois: number;
    }>(`/agricultural_cycles/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  bounds: (orthomosaicId?: string) =>
    request<BoundsResponse>(
      `/bounds${orthomosaicId ? `?orthomosaic_id=${encodeURIComponent(orthomosaicId)}` : ""}`,
    ),
  ndvi: () => request<NdviResponse>("/ndvi_data"),
  vegetationIndex: (name: "NDWI" | "NDRE") =>
    request<NdviResponse>(`/vegetation_indices/${name}`),
  createNdviZoning: (
    orthomosaicId: string,
    indexName: "NDVI" | "NDWI" | "NDRE",
    geojson: unknown,
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
    options?: {
      classificationMethod?: "quantiles" | "equal_intervals" | "manual";
      cellValueMode?: "mean" | "min" | "max";
      detailLevel?: number;
      manualBreaks?: number[];
      analysisMin?: number;
      analysisMax?: number;
      doses?: number[];
    },
  ) =>
    request<NdviZoningResponse>("/ndvi_zoning", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        orthomosaic_id: orthomosaicId,
        index_name: indexName,
        geojson,
        zone_count: zoneCount,
        cell_size_m: cellSizeM,
        grid_angle_deg: gridAngleDeg,
        classification_method: options?.classificationMethod ?? "quantiles",
        cell_value_mode: options?.cellValueMode ?? "mean",
        detail_level: options?.detailLevel ?? 1,
        manual_breaks: options?.manualBreaks,
        analysis_min: options?.analysisMin,
        analysis_max: options?.analysisMax,
        doses: options?.doses,
      }),
    }),
  createPrescription: (
    orthomosaicId: string,
    indexName: "NDVI" | "NDWI" | "NDRE",
    geojson: unknown,
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
    options?: {
      classificationMethod?: "quantiles" | "equal_intervals" | "manual";
      cellValueMode?: "mean" | "min" | "max";
      detailLevel?: number;
      manualBreaks?: number[];
      analysisMin?: number;
      analysisMax?: number;
      doses?: number[];
    },
  ) =>
    request<PrescriptionMapResponse>("/prescriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        orthomosaic_id: orthomosaicId,
        index_name: indexName,
        geojson,
        zone_count: zoneCount,
        cell_size_m: cellSizeM,
        grid_angle_deg: gridAngleDeg,
        classification_method: options?.classificationMethod ?? "quantiles",
        cell_value_mode: options?.cellValueMode ?? "mean",
        detail_level: options?.detailLevel ?? 1,
        manual_breaks: options?.manualBreaks,
        analysis_min: options?.analysisMin,
        analysis_max: options?.analysisMax,
        doses: options?.doses,
      }),
    }),
  roiVegetationIndex: (name: "NDWI" | "NDRE", geojson: unknown) =>
    request<NdviResponse>(`/roi_indices/${name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geojson }),
    }),
  orthomosaics: (cycleId?: string) =>
    request<{ status: string; items: OrthomosaicRecord[] }>(
      `/orthomosaics${cycleId ? `?cycle_id=${encodeURIComponent(cycleId)}` : ""}`,
    ),
  reorderOrthomosaics: (cycleId: string, orthomosaicIds: string[]) =>
    request<{ status: string; items: OrthomosaicRecord[] }>(
      `/agricultural_cycles/${encodeURIComponent(cycleId)}/orthomosaics/order`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ orthomosaic_ids: orthomosaicIds }),
      },
    ),
  deleteOrthomosaic: (id: string) =>
    request<{ status: string }>(`/orthomosaics/${id}`, { method: "DELETE" }),
  updateOrthomosaic: (id: string, payload: UpdateOrthomosaicPayload) =>
    request<{ status: string; orthomosaic: OrthomosaicRecord }>(
      `/orthomosaics/${id}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
  activateOrthomosaic: (id: string) =>
    request<{ status: string; orthomosaic: OrthomosaicRecord }>(
      `/orthomosaics/${id}/activate`,
      { method: "POST" },
    ),
  rois: (cycleId?: string | null) =>
    request<{ status: string; items: RoiRecord[] }>(
      `/rois${cycleId ? `?cycle_id=${encodeURIComponent(cycleId)}` : ""}`,
    ),
  saveRoi: (
    geojson: unknown,
    orthomosaicId: string | null,
    cycleId: string | null,
    name = "ROI",
  ) =>
    request<{ status: string; roi: RoiRecord }>("/rois", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        geojson,
        orthomosaic_id: orthomosaicId,
        cycle_id: cycleId,
      }),
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
    cycleId: string | null,
    payload: SaveRoiAnalysisPayload,
  ) =>
    request<{ status: string; analysis: RoiAnalysisRecord }>(
      `/rois/${roiId}/analyses`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          orthomosaic_id: orthomosaicId,
          cycle_id: cycleId,
          index: payload.index,
          stats: payload.stats,
        }),
      },
    ),
  roiAnalyses: (
    roiId: string,
    index: "NDVI" | "NDWI" | "NDRE",
    cycleId: string | null,
  ) =>
    request<{ status: string; items: RoiAnalysisRecord[] }>(
      `/rois/${roiId}/analyses?index=${encodeURIComponent(index)}${cycleId ? `&cycle_id=${encodeURIComponent(cycleId)}` : ""}&fresh=${Date.now()}`,
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
  downloadCrop: (cropId: string, variant: "visual" | "analytical") =>
    download(
      `/crop_tiles/${encodeURIComponent(cropId)}/download?variant=${variant}`,
    ),
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
  uploadOrthomosaic: (
    file: File,
    sensor: OrthoSensor,
    captureDate: string,
    agriculturalCycleId: string,
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("agricultural_cycle_id", agriculturalCycleId);
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
