import type { NdviResponse } from "../services/api";

interface IndexColorRampDefinition {
  label: string;
  fullLabel: string;
  description: string;
  noDataColor: string;
  ramp: readonly string[];
  stops?: readonly number[];
}

const VEGETATION_COLOR_RAMP = [
  "#FF1F1F",
  "#FF4A1F",
  "#FF741F",
  "#FF9B1F",
  "#FFC21F",
  "#FFDD1F",
  "#F3EB23",
  "#D6E428",
  "#A9D83A",
  "#6CCF45",
] as const;
const VEGETATION_COLOR_STOPS = [
  0.0,
  0.12,
  0.24,
  0.38,
  0.5,
  0.6,
  0.68,
  0.76,
  0.88,
  1.0,
] as const;
const PRESCRIPTION_HISTOGRAM_STOPS = [
  0.0,
  0.12,
  0.24,
  0.4,
  0.56,
  0.66,
  0.74,
  0.82,
  0.91,
  1.0,
] as const;

/** Metadatos y rampas cromaticas compartidas por mapa, leyenda e histogramas. */
export const INDEX_COLOR_RAMPS: Record<
  "NDVI" | "GNDVI" | "NDWI" | "NDRE",
  IndexColorRampDefinition
> = {
  NDVI: {
    label: "NDVI",
    fullLabel: "Normalized Difference Vegetation Index",
    description: "Low vegetation / stressed vegetation -> high vegetation vigor",
    noDataColor: "#00000000",
    ramp: VEGETATION_COLOR_RAMP,
    stops: VEGETATION_COLOR_STOPS,
  },
  GNDVI: {
    label: "GNDVI",
    fullLabel: "Green Normalized Difference Vegetation Index",
    description:
      "Low chlorophyll / bare soil -> high chlorophyll / active vegetation",
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
    description: "Dry / low water -> high water / moisture",
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
    stops: undefined,
  },
  NDRE: {
    label: "NDRE",
    fullLabel: "Normalized Difference Red Edge Index",
    description:
      "Low red-edge response / crop stress -> high chlorophyll activity",
    noDataColor: "#00000000",
    ramp: VEGETATION_COLOR_RAMP,
    stops: VEGETATION_COLOR_STOPS,
  },
} as const;

export type IndexColorName = keyof typeof INDEX_COLOR_RAMPS;

/** Estadisticos descriptivos junto con los valores usados para recalcular filtros. */
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

/** Convierte bytes 0..255 del backend al dominio canonico NDVI -1..1. */
export function ndviValue(value: number): number {
  return value > 1 ? (value / 255) * 2 - 1 : value;
}

/** Extrae unicamente pixeles finitos y validos segun la mascara del raster. */
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

/** Interpolacion lineal de un percentil sobre un arreglo previamente ordenado. */
function percentile(sorted: number[], fraction: number): number {
  if (!sorted.length) return 0;
  const index = (sorted.length - 1) * fraction;
  const lower = Math.floor(index);
  const upper = Math.ceil(index);
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
}

/** Calcula el resumen estadistico que consumen los paneles e histogramas. */
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

/** Atajo para obtener estadisticas directamente desde una respuesta raster. */
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

function rampStops(name: IndexColorName): readonly number[] {
  const rampDefinition = INDEX_COLOR_RAMPS[name] as {
    ramp: readonly string[];
    stops?: readonly number[];
  };
  const stops = rampDefinition.stops;
  if (stops) return stops;
  const ramp = rampDefinition.ramp;
  return Array.from(
    { length: ramp.length },
    (_, index) => index / Math.max(ramp.length - 1, 1),
  );
}

function interpolateRampColor(
  ramp: readonly string[],
  stops: readonly number[],
  position: number,
): string {
  let upperIndex = stops.findIndex((stop) => position <= stop);
  if (upperIndex <= 0) upperIndex = 1;
  if (upperIndex === -1) upperIndex = stops.length - 1;
  const lowerIndex = upperIndex - 1;
  const lowerStop = stops[lowerIndex];
  const upperStop = stops[upperIndex];
  const start = rgb(ramp[lowerIndex]);
  const end = rgb(ramp[upperIndex]);
  const factor =
    (position - lowerStop) / Math.max(upperStop - lowerStop, Number.EPSILON);
  return `rgb(${start
    .map((channel, index) =>
      Math.round(channel + (end[index] - channel) * factor),
    )
    .join(", ")})`;
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
  const stops = rampStops(name);
  return interpolateRampColor(ramp, stops, position);
}

/** Construye los segmentos de un gradiente CSS consistente con la capa del mapa. */
export function indexGradient(
  name: IndexColorName,
  minimum: number,
  maximum: number,
): string {
  const ramp = INDEX_COLOR_RAMPS[name].ramp;
  const stops = rampStops(name);
  return ramp
    .map(
      (_, index) =>
        `${ramp[index]} ${stops[index] * 100}%`,
    )
    .join(", ");
}

export function prescriptionHistogramColor(
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
  const stops =
    name === "NDVI" || name === "NDRE"
      ? PRESCRIPTION_HISTOGRAM_STOPS
      : rampStops(name);
  return interpolateRampColor(ramp, stops, position);
}

export function prescriptionHistogramGradient(name: IndexColorName): string {
  const ramp = INDEX_COLOR_RAMPS[name].ramp;
  const stops =
    name === "NDVI" || name === "NDRE"
      ? PRESCRIPTION_HISTOGRAM_STOPS
      : rampStops(name);
  return ramp
    .map((color, index) => `${color} ${stops[index] * 100}%`)
    .join(", ");
}
export const ndviColor = (value: number, minimum: number, maximum: number) =>
  indexColor("NDVI", value, minimum, maximum);
export const ndviGradient = (minimum: number, maximum: number) =>
  indexGradient("NDVI", minimum, maximum);
