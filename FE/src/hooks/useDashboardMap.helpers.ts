/**
 * Utilidades puras del hook del mapa.
 * Reúnen funciones auxiliares de estado, filtrado, formateo y construcción
 * de popups para mantener el hook principal más legible.
 */
import type { Feature, FeatureCollection } from "geojson";
import type { OrthoMode, OrthoSensor } from "../services/api";
import type { TreeCollection, TreeFeature } from "../types/geo";
import type { MapState } from "./useDashboardMap";
import {
  diameterOf,
  filterTreesByDiameter,
  sizeOf,
  type VisibleTreeSize,
} from "../utils/tree";
import { ndviStats } from "../utils/ndvi";

/** Escapa propiedades externas antes de interpolarlas en contenido HTML Leaflet. */
export function escapePopupText(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ] ?? character,
  );
}

export function filterVisibleTrees(
  data: TreeCollection | null,
  range: { min: number; max: number },
  visibleSizes: Record<VisibleTreeSize, boolean>,
): TreeCollection | null {
  const ranged = filterTreesByDiameter(data, range.min, range.max);
  if (!ranged) return null;
  return {
    ...ranged,
    features: ranged.features.filter((feature) => {
      const category = sizeOf(diameterOf(feature));
      return category === "unknown" || visibleSizes[category];
    }),
  };
}

export function createInitialMapState(): MapState {
  return {
    orthoMode: null,
    sensor: null,
    orthomosaicId: null,
    ndvi: false,
    trees: false,
    labels: false,
    prescription: false,
    vari: false,
    exg: false,
    swipe: false,
    swipePosition: 50,
    loaded: false,
    rgb: false,
    uploading: false,
    roiSelected: false,
    selectedRoiId: null,
    selectedRoiIds: [],
    treeDisplayMode: "points",
    visibleTreeSizes: { small: true, medium: true, large: true },
    detectionEditMode: null,
    error: null,
  };
}

export function createEmptyNdviAnalysis() {
  return {
    response: null,
    stats: ndviStats(null),
    roiResponse: null,
    roiStats: ndviStats(null),
    minimum: -1,
    maximum: 1,
  };
}

export function modeFromSensor(sensor: OrthoSensor | string): OrthoMode {
  return sensor === "mavic3m" || sensor === "micasense"
    ? "multispectral"
    : "rgb";
}

export function buildTreePopupHtml(feature: TreeFeature): string {
  const diameter = diameterOf(feature);
  const properties = feature.properties as Record<string, unknown> | null;
  const label =
    typeof properties?.name === "string"
      ? properties.name
      : typeof properties?.size_class === "string"
        ? properties.size_class
        : sizeOf(diameter);
  return `<strong>Detección:</strong> ${escapePopupText(label)}${Number.isFinite(diameter) ? `<br/><strong>Diámetro:</strong> ${diameter.toFixed(2)} m` : "<br/><strong>Diámetro:</strong> No disponible"}`;
}

export function buildGeometryPopupHtml(feature: Feature): string {
  const treeFeature = feature as TreeFeature;
  const diameter = diameterOf(treeFeature);
  const properties = feature.properties as Record<string, unknown> | null;
  const label =
    typeof properties?.name === "string"
      ? properties.name
      : typeof properties?.size_class === "string"
        ? properties.size_class
        : sizeOf(diameter);
  return `<strong>Geometría:</strong> ${escapePopupText(feature.geometry.type)}<br/><strong>Clase:</strong> ${escapePopupText(label)}${Number.isFinite(diameter) ? `<br/><strong>Diámetro:</strong> ${diameter.toFixed(2)} m` : ""}`;
}

export function buildRoiSelection(
  selections: Array<[string, unknown]>,
): { collection: FeatureCollection; roiIds: string[] } {
  const features = selections.flatMap(([, geojson]) => {
    const candidate = geojson as { type?: string; features?: Feature[] };
    return candidate.type === "FeatureCollection" &&
      Array.isArray(candidate.features)
      ? candidate.features
      : [geojson as Feature];
  });
  return {
    collection: { type: "FeatureCollection", features },
    roiIds: selections
      .map(([id]) => id)
      .filter((id) => id !== "__temporary__"),
  };
}
