/**
 * Utilidades para detecciones arbóreas.
 * Normalizan atributos, calculan diámetros, clasifican tamaños y generan
 * estadísticas para el mapa y el panel de control.
 */
import type { TreeCollection, TreeFeature, TreeStats } from "../types/geo";

export type TreeSize = "small" | "medium" | "large" | "unknown";
export type VisibleTreeSize = Exclude<TreeSize, "unknown">;

/** Colores compartidos entre símbolos del mapa, leyendas e histograma. */
export const treeSizeColors = {
  small: "#ff1a1a",
  medium: "#ffea00",
  large: "#7cfc00",
  unknown: "#64748b",
} as const;

const directDiameterKeys = [
  "diam_avg_m",
  "diameter_m",
  "diametro_m",
  "diam_m",
  "tree_diameter_m",
  "canopy_diameter_m",
  "dbh_m",
  "diameter",
  "diametro",
  "dbh",
] as const;

const radiusKeys = ["radius_m", "radio_m", "canopy_radius_m"] as const;
const bboxWidthKeys = ["bbox_w_px", "bbox_width_px", "bbox_width"] as const;
const bboxHeightKeys = ["bbox_h_px", "bbox_height_px", "bbox_height"] as const;
const diameterWidthKeys = [
  "diam_x_m",
  "diameter_x_m",
  "crown_width_m",
  "canopy_width_m",
  "copa_ancho_m",
] as const;
const diameterHeightKeys = [
  "diam_y_m",
  "diameter_y_m",
  "crown_height_m",
  "canopy_height_m",
  "copa_alto_m",
] as const;
const pixelSizeKeys = [
  "pixel_size_m",
  "pixel_size",
  "pixel_resolution_m",
] as const;

/** Uniforma nombres de propiedades provenientes de GeoJSON y tablas DBF. */
function normalizePropertyKey(key: string): string {
  return key
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** Crea un índice de propiedades insensible a mayúsculas, espacios y acentos. */
function normalizedProperties(
  properties: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(properties).map(([key, value]) => [
      normalizePropertyKey(key),
      value,
    ]),
  );
}

/** Convierte valores numéricos de JSON o DBF, incluidos decimales con coma. */
function positiveNumber(source: unknown): number | null {
  const value = Number(
    typeof source === "string" ? source.trim().replace(",", ".") : source,
  );
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Devuelve el primer número positivo disponible según la prioridad indicada. */
function firstPositiveNumber(
  properties: Record<string, unknown>,
  keys: readonly string[],
): number | null {
  for (const key of keys) {
    const value = positiveNumber(properties[key]);
    if (value !== null) return value;
  }
  return null;
}

/** Redondea medidas normalizadas para estabilizar estadísticas y etiquetas. */
function roundDiameter(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Normaliza detecciones en el navegador para que el mapa no dependa de la
 * disponibilidad del backend. El servidor puede validar nuevamente el mismo
 * contrato cuando se encuentre activo.
 */
export function normalizeTreeCollection(
  data: TreeCollection,
  diameterField?: string | null,
): TreeCollection {
  const features = data.features.flatMap((feature) => {
    const [longitude, latitude] = feature.geometry.coordinates.map(Number);
    if (
      !Number.isFinite(longitude) ||
      !Number.isFinite(latitude) ||
      longitude < -180 ||
      longitude > 180 ||
      latitude < -90 ||
      latitude > 90
    )
      return [];

    const original = feature.properties ?? {};
    const properties = normalizedProperties(original);
    const inferredDiameterKey = Object.keys(properties).find(
      (key) =>
        /(diam|diametro|diameter)/.test(key) &&
        !/(_x_|_y_|width|height|ancho|alto|px|class)/.test(key),
    );
    const selected = diameterField
      ? firstPositiveNumber(properties, [normalizePropertyKey(diameterField)])
      : null;
    const direct =
      selected ??
      firstPositiveNumber(properties, directDiameterKeys) ??
      (inferredDiameterKey
        ? firstPositiveNumber(properties, [inferredDiameterKey])
        : null);
    const radius = firstPositiveNumber(properties, radiusKeys);
    const diameterWidth = firstPositiveNumber(properties, diameterWidthKeys);
    const diameterHeight = firstPositiveNumber(properties, diameterHeightKeys);
    const bboxWidth = firstPositiveNumber(properties, bboxWidthKeys);
    const bboxHeight = firstPositiveNumber(properties, bboxHeightKeys);
    const pixelSize = firstPositiveNumber(properties, pixelSizeKeys);

    let diameter: number | null = direct;
    let diameterX: number | null = direct;
    let diameterY: number | null = direct;
    if (diameter === null && radius !== null) {
      diameter = radius * 2;
      diameterX = diameter;
      diameterY = diameter;
    } else if (
      diameter === null &&
      (diameterWidth !== null || diameterHeight !== null)
    ) {
      diameterX = diameterWidth ?? diameterHeight;
      diameterY = diameterHeight ?? diameterWidth;
      diameter = ((diameterX ?? 0) + (diameterY ?? 0)) / 2;
    } else if (
      diameter === null &&
      bboxWidth !== null &&
      bboxHeight !== null &&
      pixelSize !== null
    ) {
      diameterX = bboxWidth * pixelSize;
      diameterY = bboxHeight * pixelSize;
      diameter = (diameterX + diameterY) / 2;
    }

    const normalized = { ...original };
    let category: TreeSize = "unknown";
    if (diameter !== null) {
      diameter = roundDiameter(diameter);
      diameterX = roundDiameter(diameterX ?? diameter);
      diameterY = roundDiameter(diameterY ?? diameter);
      category = sizeOf(diameter);
      Object.assign(normalized, {
        diam_avg_m: diameter,
        diameter_m: diameter,
        diam_x_m: diameterX,
        diam_y_m: diameterY,
        size_class: category,
      });
    } else {
      const originalCategory = String(
        properties.size_class ?? "unknown",
      ).toLowerCase();
      category = (["small", "medium", "large"] as const).includes(
        originalCategory as VisibleTreeSize,
      )
        ? (originalCategory as VisibleTreeSize)
        : "unknown";
      Object.assign(normalized, {
        diam_x_m: original.diam_x_m ?? null,
        diam_y_m: original.diam_y_m ?? null,
        size_class: category,
      });
    }

    const color = treeSizeColors[category];
    Object.assign(normalized, {
      "marker-color": color,
      "marker-opacity": 0.5,
      "marker-size": "medium",
      "marker-symbol": "circle",
      stroke: color,
      "stroke-opacity": 0.5,
      "stroke-width": 1,
      fill: color,
      "fill-opacity": 0.5,
    });

    return [
      {
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [longitude, latitude] as [number, number],
        },
        properties: normalized,
      },
    ];
  });

  if (!features.length)
    throw new Error(
      "No hay puntos WGS84 válidos. Verifica coordenadas [longitud, latitud] en EPSG:4326.",
    );
  return { type: "FeatureCollection", features };
}

/**
 * Enumera campos numéricos disponibles para permitir una asignación manual
 * cuando una fuente utiliza un nombre de diámetro propio.
 */
export function numericTreeFields(data: TreeCollection | null): string[] {
  const counts = new Map<string, number>();
  data?.features.forEach((feature) => {
    Object.entries(feature.properties ?? {}).forEach(([key, value]) => {
      if (positiveNumber(value) !== null)
        counts.set(key, (counts.get(key) ?? 0) + 1);
    });
  });
  const preferred = /(diam|radio|radius|copa|crown|canopy|width|ancho|size)/i;
  const excluded = /(opacity|stroke|marker|fill|color|^id$)/i;
  return [...counts]
    .filter(([key]) => !excluded.test(key))
    .sort(([left, leftCount], [right, rightCount]) => {
      const relevance =
        Number(preferred.test(right)) - Number(preferred.test(left));
      return relevance || rightCount - leftCount || left.localeCompare(right);
    })
    .map(([key]) => key);
}

/**
 * Obtiene el diámetro sin depender del nombre de campo usado por cada fuente.
 * Devuelve `NaN` cuando el feature no contiene un valor numérico utilizable.
 */
export function diameterOf(feature: TreeFeature): number {
  const properties = normalizedProperties(feature.properties ?? {});
  return firstPositiveNumber(properties, directDiameterKeys) ?? NaN;
}

/** Clasifica un diámetro con los umbrales de dominio definidos por el producto. */
export function sizeOf(value: number): TreeSize {
  if (!Number.isFinite(value)) return "unknown";
  if (value <= 2.5) return "small";
  if (value <= 3.5) return "medium";
  return "large";
}

/** Calcula conteos y estadísticos descriptivos de una colección de árboles. */
export function treeStats(data: TreeCollection | null): TreeStats {
  const features = data?.features ?? [];
  const values = features.map(diameterOf);
  const valid = values.filter(Number.isFinite);
  const counts = { small: 0, medium: 0, large: 0, unknown: 0 };

  values.forEach((value) => {
    counts[sizeOf(value)]++;
  });

  return {
    count: features.length,
    mean: valid.length ? valid.reduce((a, b) => a + b, 0) / valid.length : 0,
    min: valid.length ? Math.min(...valid) : 0,
    max: valid.length ? Math.max(...valid) : 0,
    ...counts,
  };
}

/**
 * Conserva detecciones sin diámetro conocido y filtra únicamente las que sí
 * pueden evaluarse contra el rango solicitado.
 */
export function filterTreesByDiameter(
  data: TreeCollection | null,
  min: number,
  max: number,
): TreeCollection | null {
  if (!data) return null;

  return {
    ...data,
    features: data.features.filter((feature) => {
      const diameter = diameterOf(feature);
      return !Number.isFinite(diameter) || (diameter >= min && diameter <= max);
    }),
  };
}
