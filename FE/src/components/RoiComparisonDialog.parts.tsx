/**
 * Helpers and presentational subcomponents for the ROI comparison dashboard.
 */
import {
  IconArrowDownRight,
  IconArrowUpRight,
  IconMinus,
} from "@tabler/icons-react";
import type {
  RoiAnalysisRecord,
  RoiAnalysisStats,
} from "../services/api";

export interface RoiComparisonDialogProps {
  open: boolean;
  activeIndex: "NDVI" | "NDWI" | "NDRE";
  items: RoiAnalysisRecord[];
  loading: boolean;
  exporting: boolean;
  deletingId: string | null;
  error: string | null;
  syncedAt: string | null;
  activeOrthomosaicId: string | null;
  onRefresh: () => Promise<void>;
  onExport: () => void;
  onEditFlight: (orthomosaicId: string) => Promise<void>;
  onDelete: (analysis: RoiAnalysisRecord) => void;
  onClose: () => void;
}

export const metric = (value: number | null | undefined, digits = 3) =>
  value == null || !Number.isFinite(value) ? "-" : value.toFixed(digits);
export const recordDate = (analysis: RoiAnalysisRecord) =>
  analysis.orthomosaics?.capture_date ?? analysis.created_at;
export const chronologicalKey = (analysis: RoiAnalysisRecord) =>
  `${recordDate(analysis)}|${analysis.orthomosaics?.name ?? ""}|${analysis.orthomosaic_id}`;
export const flightLabel = (analysis: RoiAnalysisRecord, index: number) =>
  analysis.orthomosaics?.name?.trim() || `Vuelo ${index + 1}`;
export const shortDate = (value: string) => {
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? `${value}T00:00:00`
    : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("es-MX", {
        day: "2-digit",
        month: "short",
        year: "2-digit",
      });
};

interface TrendChartProps {
  title: string;
  description: string;
  items: RoiAnalysisRecord[];
  value: (analysis: RoiAnalysisRecord) => number | null;
  tone: "green" | "graphite";
  nonNegative?: boolean;
}

export interface HeatmapRow {
  key: string;
  label: string;
  suffix?: string;
  digits?: number;
  values: Array<number | null>;
}

export interface SummaryDetailRow {
  label: string;
  value: string;
  tone?: "neutral" | "up" | "down";
}

export interface MetricHistoryModalState {
  key: string;
  label: string;
  digits: number;
  suffix: string;
  values: Array<number | null>;
}

export const INDEX_SECTIONS = [
  {
    key: "ndvi",
    label: "NDVI",
    title: "Dashboard comparativo NDVI",
    description: "Vigor vegetal",
    tone: "green" as const,
  },
  {
    key: "ndwi",
    label: "NDWI",
    title: "Dashboard comparativo NDWI",
    description: "Humedad / agua",
    tone: "graphite" as const,
  },
  {
    key: "ndre",
    label: "NDRE",
    title: "Dashboard comparativo NDRE",
    description: "Respuesta red-edge",
    tone: "green" as const,
  },
] as const;

export type IndexKey = (typeof INDEX_SECTIONS)[number]["key"];
export type DashboardView =
  | "overview"
  | "trends"
  | "traceability"
  | "methodology";

export const DASHBOARD_VIEWS: Array<{
  key: DashboardView;
  label: string;
  description: string;
}> = [
  {
    key: "overview",
    label: "Ciclo",
    description: "Vuelos, KPIs y estado actual",
  },
  {
    key: "trends",
    label: "Temporal",
    description: "Curvas y mapa de calor real",
  },
  {
    key: "traceability",
    label: "Trazabilidad",
    description: "Tabla historica y registros guardados",
  },
  {
    key: "methodology",
    label: "GeoScore",
    description: "Marco visual y metodologia",
  },
];

export const GEOSCORE_WEIGHTS = [
  {
    weight: "35%",
    title: "Vigor relativo",
    description: "Media de la tabla Ã· media de sus hermanas",
  },
  {
    weight: "25%",
    title: "Uniformidad",
    description: "CV de la tabla contra el CV del grupo",
  },
  {
    weight: "20%",
    title: "Tendencia",
    description: "Cambio propio contra el cambio esperado del grupo",
  },
  {
    weight: "10%",
    title: "Cobertura de dosel",
    description: "Planta real presente, no solo verdor",
  },
  {
    weight: "10%",
    title: "Area bajo umbral",
    description: "Porcentaje de superficie por debajo del piso del lote",
  },
] as const;

export const statsOf = (
  analysis: RoiAnalysisRecord,
  key: IndexKey,
): RoiAnalysisStats | null =>
  key === "ndvi" ? analysis.ndvi : analysis[key];

export const scoreColor = (value: number) => {
  if (value >= 85) return "#12684A";
  if (value >= 72) return "#2E9E5B";
  if (value >= 58) return "#7FA95D";
  if (value >= 44) return "#E0952C";
  if (value >= 28) return "#D96A3A";
  return "#D6473F";
};

export const metricHeatColor = (
  value: number | null,
  minimum: number,
  maximum: number,
): string => {
  if (value == null || !Number.isFinite(value)) return "#D7DFD9";
  if (maximum - minimum <= Number.EPSILON) return scoreColor(76);
  const normalized = (value - minimum) / (maximum - minimum);
  return scoreColor(18 + normalized * 74);
};

/** Dibuja una serie temporal SVG como grÃ¡fica de barras con dominio adaptado. */
export function TrendChart({
  title,
  description,
  items,
  value,
  tone,
  nonNegative = false,
}: TrendChartProps) {
  const width = 720;
  const height = 250;
  const plot = { left: 48, right: 18, top: 20, bottom: 52 };
  const points = items
    .map((analysis, index) => ({ analysis, index, value: value(analysis) }))
    .filter(
      (
        point,
      ): point is {
        analysis: RoiAnalysisRecord;
        index: number;
        value: number;
      } => point.value != null && Number.isFinite(point.value),
    );
  if (!points.length)
    return (
      <div className="roi-trend-empty">
        No existen valores suficientes para construir esta tendencia.
      </div>
    );

  const values = points.map((point) => point.value);
  const observedMin = Math.min(...values);
  const observedMax = Math.max(...values);
  const baseline = nonNegative || observedMin >= 0 ? 0 : observedMin;
  const chartHeight = height - plot.top - plot.bottom;
  const maximum =
    baseline >= 0
      ? observedMax + Math.max(observedMax * 0.18, 0.05)
      : observedMax + Math.max((observedMax - baseline) * 0.12, 0.02);
  const domain = Math.max(maximum - baseline, Number.EPSILON);
  const y = (pointValue: number) =>
    plot.top + ((maximum - pointValue) / domain) * chartHeight;
  const slotWidth = (width - plot.left - plot.right) / items.length;
  const baselineY = y(baseline);
  const linePoints = points.map((point) => ({
    ...point,
    x: plot.left + (point.index + 0.5) * slotWidth,
    y: y(point.value),
  }));
  const trendPath = linePoints
    .map((point, index) =>
      `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`,
    )
    .join(" ");
  const areaPath =
    linePoints.length > 0
      ? [
          `M ${linePoints[0].x.toFixed(2)} ${baselineY.toFixed(2)}`,
          ...linePoints.map(
            (point) => `L ${point.x.toFixed(2)} ${point.y.toFixed(2)}`,
          ),
          `L ${linePoints[linePoints.length - 1].x.toFixed(2)} ${baselineY.toFixed(2)}`,
          "Z",
        ].join(" ")
      : "";
  const labelIndexes =
    items.length <= 6
      ? items.map((_, index) => index)
      : [0, Math.floor((items.length - 1) / 2), items.length - 1];
  const focusPoint = linePoints[linePoints.length - 1] ?? null;

  return (
    <article className={`roi-trend-card is-${tone}`}>
      <header>
        <div>
          <strong>{title}</strong>
          <span>{description}</span>
        </div>
        <i>{points.length} mediciones</i>
      </header>
      <svg
        className="roi-trend-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${title}: ${description}`}
      >
        {[0, 1, 2, 3, 4].map((line) => {
          const lineY = plot.top + (line / 4) * chartHeight;
          const axisValue = maximum - (line / 4) * domain;
          return (
            <g key={line}>
              <line
                className="roi-trend-gridline"
                x1={plot.left}
                x2={width - plot.right}
                y1={lineY}
                y2={lineY}
              />
              <text
                className="roi-trend-axis"
                x={plot.left - 8}
                y={lineY + 3}
                textAnchor="end"
              >
                {axisValue.toFixed(2)}
              </text>
            </g>
          );
        })}
        <line
          className="roi-trend-baseline"
          x1={plot.left}
          x2={width - plot.right}
          y1={baselineY}
          y2={baselineY}
        />
        {focusPoint && (
          <line
            className="roi-trend-focus"
            x1={focusPoint.x}
            x2={focusPoint.x}
            y1={plot.top}
            y2={height - plot.bottom + 4}
          />
        )}
        {areaPath && <path className="roi-trend-area" d={areaPath} />}
        {trendPath && <path className="roi-trend-line" d={trendPath} />}
        {linePoints.map((point) => {
          return (
            <g key={point.analysis.id}>
              <circle
                className="roi-trend-point-ring"
                cx={point.x}
                cy={point.y}
                r={6.4}
              >
                <title>{`${point.analysis.orthomosaics?.name ?? "Ortomosaico"} Â· ${shortDate(recordDate(point.analysis))}: ${point.value}`}</title>
              </circle>
              <text
                className="roi-trend-bar-label"
                x={point.x}
                y={point.y - 14}
                textAnchor="middle"
              >
                {point.value.toFixed(2)}
              </text>
            </g>
          );
        })}
        {labelIndexes.map((index) => (
          <text
            key={items[index].id}
            className="roi-trend-date"
            x={plot.left + (index + 0.5) * slotWidth}
            y={height - 24}
            textAnchor={
              index === 0
                ? "start"
                : index === items.length - 1
                  ? "end"
                  : "middle"
            }
          >
            {shortDate(recordDate(items[index]))}
          </text>
        ))}
        {labelIndexes.map((index) => (
          <text
            key={`${items[index].id}-flight`}
            className="roi-trend-flight"
            x={plot.left + (index + 0.5) * slotWidth}
            y={height - 8}
            textAnchor={
              index === 0
                ? "start"
                : index === items.length - 1
                  ? "end"
                  : "middle"
            }
          >
            {flightLabel(items[index], index)}
          </text>
        ))}
      </svg>
    </article>
  );
}

export function MetricHistoryChart({
  title,
  description,
  items,
  values,
  digits,
  suffix,
  relative = false,
}: {
  title: string;
  description: string;
  items: RoiAnalysisRecord[];
  values: Array<number | null>;
  digits: number;
  suffix: string;
  relative?: boolean;
}) {
  const width = 760;
  const height = 280;
  const plot = { left: 54, right: 22, top: 24, bottom: 58 };
  const source =
    relative && values.some((value) => value != null && Number.isFinite(value))
      ? (() => {
          const baseline =
            values.find(
              (value): value is number =>
                value != null &&
                Number.isFinite(value) &&
                Math.abs(value) > Number.EPSILON,
            ) ?? null;
          return values.map((value) =>
            baseline == null || value == null || !Number.isFinite(value)
              ? null
              : value / baseline,
          );
        })()
      : values;
  const points = source
    .map((value, index) => ({ value, index, analysis: items[index] }))
    .filter(
      (
        point,
      ): point is {
        value: number;
        index: number;
        analysis: RoiAnalysisRecord;
      } => point.value != null && Number.isFinite(point.value),
    );

  if (!points.length) {
    return (
      <div className="roi-trend-empty">
        No hay suficientes valores para construir este historial.
      </div>
    );
  }

  const observedMin = Math.min(...points.map((point) => point.value));
  const observedMax = Math.max(...points.map((point) => point.value));
  const baseline = relative ? 1 : observedMin >= 0 ? 0 : observedMin;
  const chartHeight = height - plot.top - plot.bottom;
  const maximum =
    Math.max(observedMax, baseline) +
    Math.max(Math.abs(observedMax - baseline) * 0.16, 0.04);
  const minimum =
    Math.min(observedMin, baseline) -
    Math.max(Math.abs(observedMax - baseline) * 0.08, 0.02);
  const domain = Math.max(maximum - minimum, Number.EPSILON);
  const y = (pointValue: number) =>
    plot.top + ((maximum - pointValue) / domain) * chartHeight;
  const slotWidth = (width - plot.left - plot.right) / items.length;
  const baselineY = y(baseline);
  const linePoints = points.map((point) => ({
    ...point,
    x: plot.left + (point.index + 0.5) * slotWidth,
    y: y(point.value),
  }));
  const trendPath = linePoints
    .map((point, index) =>
      `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`,
    )
    .join(" ");
  const labelIndexes =
    items.length <= 6
      ? items.map((_, index) => index)
      : [0, Math.floor((items.length - 1) / 2), items.length - 1];

  return (
    <article className="roi-metric-history-chart">
      <header>
        <div>
          <strong>{title}</strong>
          <span>{description}</span>
        </div>
      </header>
      <svg
        className="roi-trend-svg roi-metric-history-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={title}
      >
        {[0, 1, 2, 3, 4].map((line) => {
          const lineY = plot.top + (line / 4) * chartHeight;
          const axisValue = maximum - (line / 4) * (maximum - minimum);
          return (
            <g key={line}>
              <line
                className="roi-trend-gridline"
                x1={plot.left}
                x2={width - plot.right}
                y1={lineY}
                y2={lineY}
              />
              <text
                className="roi-trend-axis"
                x={plot.left - 8}
                y={lineY + 3}
                textAnchor="end"
              >
                {axisValue.toFixed(relative ? 2 : digits)}
                {suffix}
              </text>
            </g>
          );
        })}
        <line
          className="roi-trend-baseline"
          x1={plot.left}
          x2={width - plot.right}
          y1={baselineY}
          y2={baselineY}
        />
        {trendPath && (
          <path className="roi-trend-line roi-metric-history-line" d={trendPath} />
        )}
        {linePoints.map((point) => (
          <g key={`${title}-${point.analysis.id}`}>
            <circle
              className="roi-trend-point-ring"
              cx={point.x}
              cy={point.y}
              r={6}
            />
            <text
              className="roi-trend-bar-label"
              x={point.x}
              y={point.y - 14}
              textAnchor="middle"
            >
              {point.value.toFixed(relative ? 2 : digits)}
              {suffix}
            </text>
          </g>
        ))}
        {labelIndexes.map((index) => (
          <text
            key={`${title}-date-${items[index].id}`}
            className="roi-trend-date"
            x={plot.left + (index + 0.5) * slotWidth}
            y={height - 24}
            textAnchor={
              index === 0
                ? "start"
                : index === items.length - 1
                  ? "end"
                  : "middle"
            }
          >
            {shortDate(recordDate(items[index]))}
          </text>
        ))}
        {labelIndexes.map((index) => (
          <text
            key={`${title}-flight-${items[index].id}`}
            className="roi-trend-flight"
            x={plot.left + (index + 0.5) * slotWidth}
            y={height - 8}
            textAnchor={
              index === 0
                ? "start"
                : index === items.length - 1
                  ? "end"
                  : "middle"
            }
          >
            {flightLabel(items[index], index)}
          </text>
        ))}
      </svg>
    </article>
  );
}

/** Expresa el cambio contra la mediciÃ³n cronolÃ³gica inmediatamente anterior. */
export function Delta({ value }: { value: number | null }) {
  if (value == null)
    return (
      <span className="roi-metric-delta is-neutral">
        <IconMinus aria-hidden="true" />
        Sin vuelo anterior
      </span>
    );
  if (value > 0)
    return (
      <span className="roi-metric-delta is-up">
        <IconArrowUpRight aria-hidden="true" />+{value.toFixed(3)} vs. anterior
      </span>
    );
  if (value < 0)
    return (
      <span className="roi-metric-delta is-down">
        <IconArrowDownRight aria-hidden="true" />
        {value.toFixed(3)} vs. anterior
      </span>
    );
  return (
    <span className="roi-metric-delta is-neutral">
      <IconMinus aria-hidden="true" />
      Sin cambio
    </span>
  );
}

/**
 * Dashboard temporal de un ROI. Resume el historial vigente y expone acciones
 * de actualizaciÃ³n, exportaciÃ³n y eliminaciÃ³n controladas por `MapView`.
 */

