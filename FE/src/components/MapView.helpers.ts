import type { AgriculturalCycleRecord, RoiAnalysisRecord, RoiAnalysisStats } from "../services/api";

export type ComparisonIndex = "NDVI" | "NDWI" | "NDRE";

export const ACTIVE_CYCLE_STORAGE_KEY = "geofield.activeCycle";

export const loadStoredActiveCycle = (): AgriculturalCycleRecord | null => {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(ACTIVE_CYCLE_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AgriculturalCycleRecord;
  } catch {
    window.localStorage.removeItem(ACTIVE_CYCLE_STORAGE_KEY);
    return null;
  }
};

export const sameMetric = (
  left: number | null | undefined,
  right: number | null | undefined,
) => {
  if (left == null && right == null) return true;
  if (left == null || right == null) return false;
  return Math.abs(left - right) < 1e-6;
};

export const statsForIndex = (
  analysis: RoiAnalysisRecord,
  index: ComparisonIndex,
): RoiAnalysisStats | null =>
  index === "NDVI"
    ? analysis.ndvi
    : index === "NDWI"
      ? analysis.ndwi
      : analysis.ndre;

export const chronologicalKey = (analysis: RoiAnalysisRecord) =>
  `${analysis.orthomosaics?.capture_date ?? analysis.created_at}|${analysis.orthomosaics?.name ?? ""}|${analysis.orthomosaic_id}`;

export const sameStats = (
  current: RoiAnalysisStats | null,
  expected: RoiAnalysisStats,
) =>
  current != null &&
  current.count === expected.count &&
  sameMetric(current.min, expected.min) &&
  sameMetric(current.max, expected.max) &&
  sameMetric(current.mean, expected.mean) &&
  sameMetric(current.median, expected.median) &&
  sameMetric(current.standard_deviation, expected.standard_deviation) &&
  sameMetric(current.p10, expected.p10) &&
  sameMetric(current.p25, expected.p25) &&
  sameMetric(current.p75, expected.p75) &&
  sameMetric(current.p90, expected.p90) &&
  sameMetric(current.range_min, expected.range_min) &&
  sameMetric(current.range_max, expected.range_max);
