import type { NdviResponse } from "../services/api";

/** Metadatos y rampas cromáticas compartidas por mapa, leyenda e histogramas. */
export const INDEX_COLOR_RAMPS = {
  NDVI: {
    label: "NDVI",
    fullLabel: "Normalized Difference Vegetation Index",
    description: "Low vegetation / stressed vegetation → high vegetation vigor",
    noDataColor: "#00000000",
    ramp: [
      "#FF7A00",
      "#FF9500",
      "#FFB000",
      "#FFC400",
      "#E4D200",
      "#ACF404",
      "#57F20A",
      "#27E833",
      "#00B824",
      "#009E1F",
    ],
  },
  GNDVI: {
    label: "GNDVI",
    fullLabel: "Green Normalized Difference Vegetation Index",
    description:
      "Low chlorophyll / bare soil → high chlorophyll / active vegetation",
    noDataColor: "#00000000",
    ramp: [
      "#f5f5dc",
      "#dff0b0",
      "#c8e6a0",
      "#a8d87a",
      "#7ac74f",
      "#55aa30",
      "#3d8c20",
      "#2e8b57",
      "#1a5c2a",
      "#0a2e14",
    ],
  },
  NDWI: {
    label: "NDWI",
    fullLabel: "Normalized Difference Water Index",
    description: "Dry / low water → high water / moisture",
    noDataColor: "#00000000",
    ramp: [
      "#c0003a",
      "#e01a00",
      "#ff5500",
      "#ffaa00",
      "#ffe066",
      "#a8e6a0",
      "#4dd4e0",
      "#2b9aff",
      "#1a4fff",
      "#0000ff",
    ],
  },
  NDRE: {
    label: "NDRE",
    fullLabel: "Normalized Difference Red Edge Index",
    description:
      "Low red-edge response / crop stress → high chlorophyll activity",
    noDataColor: "#00000000",
    ramp: [
      "#000000",
      "#1b0a2a",
      "#3d0965",
      "#6b0d8a",
      "#9b1f9e",
      "#c43c7e",
      "#e06030",
      "#f08c00",
      "#f5b800",
      "#ffe000",
    ],
  },
} as const;

export type IndexColorName = keyof typeof INDEX_COLOR_RAMPS;

/** Estadísticos descriptivos junto con los valores usados para recalcular filtros. */
export interface NdviStats {
  count: number;
  min: number;
  max: number;
  mean: number;
  median: number;
  standardDeviation: number;
  percentiles: { p10: number; p25: number; p75: number; p90: number };
  values: number[];
}

/** Convierte bytes 0..255 del backend al dominio canónico NDVI -1..1. */
export function ndviValue(value: number): number {
  return value > 1 ? (value / 255) * 2 - 1 : value;
}

/** Extrae únicamente píxeles finitos y válidos según la máscara del raster. */
export function ndviValues(response: NdviResponse): number[] {
  const values: number[] = [];
  response.matrix.forEach((row, y) =>
    row.forEach((value, x) => {
      const mask = response.mask?.[y]?.[x];
      const normalized = ndviValue(Number(value));
      if (
        Number.isFinite(normalized) &&
        (mask === undefined || Number(mask) > 0)
      )
        values.push(normalized);
    }),
  );
  return values;
}

/** Interpolación lineal de un percentil sobre un arreglo previamente ordenado. */
function percentile(sorted: number[], fraction: number): number {
  if (!sorted.length) return 0;
  const index = (sorted.length - 1) * fraction;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
}

/** Calcula el resumen estadístico que consumen los paneles e histogramas. */
export function ndviStatsFromValues(values: number[]): NdviStats {
  const sorted = [...values].sort((a, b) => a - b);
  const mean = values.length
    ? values.reduce((total, value) => total + value, 0) / values.length
    : 0;
  const variance = values.length
    ? values.reduce((total, value) => total + (value - mean) ** 2, 0) /
      values.length
    : 0;
  return {
    count: values.length,
    min: sorted[0] ?? 0,
    max: sorted[sorted.length - 1] ?? 0,
    mean,
    median: percentile(sorted, 0.5),
    standardDeviation: Math.sqrt(variance),
    percentiles: {
      p10: percentile(sorted, 0.1),
      p25: percentile(sorted, 0.25),
      p75: percentile(sorted, 0.75),
      p90: percentile(sorted, 0.9),
    },
    values,
  };
}

/** Atajo para obtener estadísticas directamente desde una respuesta raster. */
export function ndviStats(response: NdviResponse | null): NdviStats {
  return ndviStatsFromValues(response ? ndviValues(response) : []);
}

/** Convierte un color hexadecimal de la rampa a canales RGB. */
function rgb(hex: string): [number, number, number] {
  return [
    Number.parseInt(hex.slice(1, 3), 16),
    Number.parseInt(hex.slice(3, 5), 16),
    Number.parseInt(hex.slice(5, 7), 16),
  ];
}

/** Interpola el color correspondiente a un valor dentro del rango visible. */
export function indexColor(
  name: IndexColorName,
  value: number,
  minimum: number,
  maximum: number,
): string {
  const position = Math.max(
    0,
    Math.min(
      1,
      (value - minimum) / Math.max(maximum - minimum, Number.EPSILON),
    ),
  );
  const ramp = INDEX_COLOR_RAMPS[name].ramp;
  const raw = position * (ramp.length - 1);
  const start = rgb(ramp[Math.floor(raw)]);
  const end = rgb(ramp[Math.min(ramp.length - 1, Math.ceil(raw))]);
  const factor = raw - Math.floor(raw);
  return `rgb(${start.map((channel, index) => Math.round(channel + (end[index] - channel) * factor)).join(", ")})`;
}

/** Construye los segmentos de un gradiente CSS consistente con la capa del mapa. */
export function indexGradient(
  name: IndexColorName,
  minimum: number,
  maximum: number,
): string {
  const ramp = INDEX_COLOR_RAMPS[name].ramp;
  return ramp
    .map(
      (_, index) =>
        `${indexColor(name, minimum + ((maximum - minimum) * index) / (ramp.length - 1), minimum, maximum)} ${(index / (ramp.length - 1)) * 100}%`,
    )
    .join(", ");
}
export const ndviColor = (value: number, minimum: number, maximum: number) =>
  indexColor("NDVI", value, minimum, maximum);
export const ndviGradient = (minimum: number, maximum: number) =>
  indexGradient("NDVI", minimum, maximum);
