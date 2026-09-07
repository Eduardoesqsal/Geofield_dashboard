import type { AgriculturalCycleRecord, OrthomosaicRecord, RoiAnalysisRecord, RoiAnalysisStats } from "../services/api";
import { sameStats, statsForIndex } from "./MapView.helpers";

export type DeleteTarget =
  | { kind: "cycle"; record: AgriculturalCycleRecord }
  | { kind: "orthomosaic"; record: OrthomosaicRecord }
  | { kind: "roi"; record: { name: string; id: string } }
  | { kind: "analysis"; record: RoiAnalysisRecord };

export type PrescriptionRange = {
  minimum: number | null;
  maximum: number | null;
} | null;

type RangeSource = {
  min: number | null;
  max: number | null;
};

export type ComparisonIndex = "NDVI" | "NDWI" | "NDRE";

export const csvCell = (value: string | number | null | undefined) => {
  if (value == null) return "";
  if (typeof value === "number") {
    return Number.isFinite(value) ? String(value) : "";
  }
  const protectedValue = /^[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${protectedValue.replace(/"/g, '""')}"`;
};

export const chronologicalKey = (analysis: RoiAnalysisRecord) =>
  `${analysis.orthomosaics?.capture_date ?? analysis.created_at}|${analysis.orthomosaics?.name ?? ""}|${analysis.orthomosaic_id}`;

export const getDeleteDialogContent = (target: DeleteTarget | null) =>
  target?.kind === "cycle"
    ? {
        title: "¿Eliminar este ciclo agrícola?",
        description:
          "Se eliminarán todos sus ortomosaicos, archivos, ROI y análisis asociados. Esta acción no se puede deshacer.",
        subject: target.record.name,
      }
    : target?.kind === "orthomosaic"
      ? {
          title: "¿Eliminar este ortomosaico?",
          description:
            "Se eliminarán el registro y su archivo almacenado. Esta acción no se puede deshacer.",
          subject: target.record.name,
        }
      : target?.kind === "roi"
        ? {
            title: "¿Eliminar esta región?",
            description:
              "El ROI y su historial asociado dejarán de estar disponibles. Esta acción no se puede deshacer.",
            subject: target.record.name,
          }
        : target?.kind === "analysis"
          ? {
              title: "¿Eliminar estas estadísticas?",
              description:
                "Se quitará este registro del historial comparativo del ROI. Esta acción no se puede deshacer.",
              subject:
                target.record.orthomosaics?.name ?? "Ortomosaico eliminado",
            }
          : { title: "", description: "", subject: "" };

export const getActivePrescriptionDisplayRange = (
  selectedIndex: ComparisonIndex | null,
  ndvi: {
    roiResponse: { range_min?: number | null; range_max?: number | null } | null;
    response: { range_min?: number | null; range_max?: number | null } | null;
    roiStats: RangeSource;
    stats: RangeSource;
  },
  indexAnalyses: Array<{
    name: "NDVI" | "NDWI" | "NDRE";
    response: { range_min?: number | null; range_max?: number | null };
    stats: RangeSource;
  }>,
): PrescriptionRange => {
  if (selectedIndex === "NDVI") {
    if (ndvi.roiResponse) {
      return {
        minimum: ndvi.roiResponse.range_min ?? ndvi.roiStats.min,
        maximum: ndvi.roiResponse.range_max ?? ndvi.roiStats.max,
      };
    }
    if (ndvi.response) {
      return {
        minimum: ndvi.response.range_min ?? ndvi.stats.min,
        maximum: ndvi.response.range_max ?? ndvi.stats.max,
      };
    }
    return null;
  }
  if (!selectedIndex) return null;
  const analysis = indexAnalyses.find((item) => item.name === selectedIndex);
  return analysis
    ? {
        minimum: analysis.response.range_min ?? analysis.stats.min,
        maximum: analysis.response.range_max ?? analysis.stats.max,
      }
    : null;
};

export const buildRoiComparisonCsv = (items: RoiAnalysisRecord[]) => {
  const rows: Array<Array<string | number | null | undefined>> = [
    [
      "registro_id",
      "roi_id",
      "orthomosaico_id",
      "ortomosaico",
      "fecha_captura",
      "fecha_guardado",
      "pixeles_ndvi",
      "ndvi_minimo",
      "ndvi_maximo",
      "ndvi_promedio",
      "ndvi_mediana",
      "ndvi_desviacion_estandar",
      "ndvi_p10",
      "ndvi_p25",
      "ndvi_p75",
      "ndvi_p90",
      "pixeles_ndwi",
      "ndwi_minimo",
      "ndwi_maximo",
      "ndwi_promedio",
      "ndwi_mediana",
      "ndwi_desviacion_estandar",
      "ndwi_p10",
      "ndwi_p25",
      "ndwi_p75",
      "ndwi_p90",
      "pixeles_ndre",
      "ndre_minimo",
      "ndre_maximo",
      "ndre_promedio",
      "ndre_mediana",
      "ndre_desviacion_estandar",
      "ndre_p10",
      "ndre_p25",
      "ndre_p75",
      "ndre_p90",
    ],
    ...[...items]
      .sort((left, right) => chronologicalKey(left).localeCompare(chronologicalKey(right)))
      .map((analysis) => [
        analysis.id,
        analysis.roi_id,
        analysis.orthomosaic_id,
        analysis.orthomosaics?.name ?? "Ortomosaico eliminado",
        analysis.orthomosaics?.capture_date ?? "",
        analysis.created_at,
        analysis.ndvi.count,
        analysis.ndvi.min,
        analysis.ndvi.max,
        analysis.ndvi.mean,
        analysis.ndvi.median ?? null,
        analysis.ndvi.standard_deviation,
        analysis.ndvi.p10 ?? null,
        analysis.ndvi.p25 ?? null,
        analysis.ndvi.p75 ?? null,
        analysis.ndvi.p90 ?? null,
        analysis.ndwi?.count ?? null,
        analysis.ndwi?.min ?? null,
        analysis.ndwi?.max ?? null,
        analysis.ndwi?.mean ?? null,
        analysis.ndwi?.median ?? null,
        analysis.ndwi?.standard_deviation ?? null,
        analysis.ndwi?.p10 ?? null,
        analysis.ndwi?.p25 ?? null,
        analysis.ndwi?.p75 ?? null,
        analysis.ndwi?.p90 ?? null,
        analysis.ndre?.count ?? null,
        analysis.ndre?.min ?? null,
        analysis.ndre?.max ?? null,
        analysis.ndre?.mean ?? null,
        analysis.ndre?.median ?? null,
        analysis.ndre?.standard_deviation ?? null,
        analysis.ndre?.p10 ?? null,
        analysis.ndre?.p25 ?? null,
        analysis.ndre?.p75 ?? null,
        analysis.ndre?.p90 ?? null,
      ]),
  ];
  return `\uFEFF${rows.map((row) => row.map(csvCell).join(";")).join("\r\n")}`;
};

export const analysisMatchesSavedStats = (
  analysis: RoiAnalysisRecord,
  roiId: string,
  orthomosaicId: string,
  index: ComparisonIndex,
  stats: RoiAnalysisStats,
) => {
  if (analysis.roi_id !== roiId || analysis.orthomosaic_id !== orthomosaicId) {
    return false;
  }
  return sameStats(statsForIndex(analysis, index), stats);
};
