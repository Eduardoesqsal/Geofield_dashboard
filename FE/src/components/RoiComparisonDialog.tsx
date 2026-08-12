import {
  IconArrowDownRight,
  IconArrowUpRight,
  IconChartLine,
  IconDownload,
  IconLoader2,
  IconMinus,
  IconRefresh,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import type {
  RoiAnalysisRecord,
  RoiAnalysisStats,
} from "../services/api";

interface RoiComparisonDialogProps {
  open: boolean;
  activeIndex: "NDVI" | "NDWI" | "NDRE";
  items: RoiAnalysisRecord[];
  loading: boolean;
  exporting: boolean;
  deletingId: string | null;
  error: string | null;
  syncedAt: string | null;
  onRefresh: () => Promise<void>;
  onExport: () => void;
  onDelete: (analysis: RoiAnalysisRecord) => void;
  onClose: () => void;
}

const metric = (value: number | null | undefined, digits = 3) =>
  value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
const recordDate = (analysis: RoiAnalysisRecord) =>
  analysis.orthomosaics?.capture_date ?? analysis.created_at;
const chronologicalKey = (analysis: RoiAnalysisRecord) =>
  `${recordDate(analysis)}|${analysis.created_at}`;
const shortDate = (value: string) => {
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

const ribbonMetric = (
  analysis: RoiAnalysisRecord,
  key: IndexKey,
): number | null => statsOf(analysis, key)?.mean ?? null;

interface TrendChartProps {
  title: string;
  description: string;
  items: RoiAnalysisRecord[];
  value: (analysis: RoiAnalysisRecord) => number | null;
  tone: "green" | "graphite";
  nonNegative?: boolean;
}

const INDEX_SECTIONS = [
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

type IndexKey = (typeof INDEX_SECTIONS)[number]["key"];

const statsOf = (
  analysis: RoiAnalysisRecord,
  key: IndexKey,
): RoiAnalysisStats | null =>
  key === "ndvi" ? analysis.ndvi : analysis[key];

/** Dibuja una serie temporal SVG como gráfica de barras con dominio adaptado. */
function TrendChart({
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
                <title>{`${point.analysis.orthomosaics?.name ?? "Ortomosaico"} · ${shortDate(recordDate(point.analysis))}: ${point.value}`}</title>
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
            {`V${index + 1}`}
          </text>
        ))}
      </svg>
    </article>
  );
}

/** Expresa el cambio contra la medición cronológica inmediatamente anterior. */
function Delta({ value }: { value: number | null }) {
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
 * de actualización, exportación y eliminación controladas por `MapView`.
 */
export function RoiComparisonDialog({
  open,
  activeIndex,
  items,
  loading,
  exporting,
  deletingId,
  error,
  syncedAt,
  onRefresh,
  onExport,
  onDelete,
  onClose,
}: RoiComparisonDialogProps) {
  if (!open) return null;

  const chronological = [...items].sort((left, right) =>
    chronologicalKey(left).localeCompare(chronologicalKey(right)),
  );
  const activeSection =
    INDEX_SECTIONS.find((section) => section.label === activeIndex) ??
    INDEX_SECTIONS[0];
  const busy = loading || exporting || deletingId !== null;
  const syncLabel = syncedAt
    ? new Date(syncedAt).toLocaleTimeString("es-MX", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "Pendiente";

  return (
    <div
      className="import-dialog-backdrop"
      role="presentation"
      onMouseDown={onClose}
    >
      <section
        className="import-dialog roi-comparison-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="roi-comparison-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="import-dialog-heading roi-dashboard-heading">
          <div className="modal-title-group">
            <span className="modal-title-icon">
              <IconChartLine aria-hidden="true" />
            </span>
            <div>
              <span className="import-eyebrow">INTELIGENCIA TEMPORAL</span>
              <h2 id="roi-comparison-title">
                Dashboard comparativo de índices
              </h2>
            </div>
          </div>
          <div className="roi-dashboard-toolbar">
            <button
              type="button"
              className="roi-dashboard-action is-secondary"
              onClick={() => void onRefresh()}
              disabled={busy}
            >
              {loading ? (
                <IconLoader2 className="spin" aria-hidden="true" />
              ) : (
                <IconRefresh aria-hidden="true" />
              )}
              <span>{loading ? "Actualizando…" : "Actualizar"}</span>
            </button>
            <button
              type="button"
              className="roi-dashboard-action is-primary"
              onClick={onExport}
              disabled={busy || !chronological.length}
            >
              {exporting ? (
                <IconLoader2 className="spin" aria-hidden="true" />
              ) : (
                <IconDownload aria-hidden="true" />
              )}
              <span>{exporting ? "Consultando…" : "Exportar CSV real"}</span>
            </button>
            <button
              className="dialog-close"
              type="button"
              onClick={onClose}
              disabled={deletingId !== null}
              aria-label="Cerrar"
            >
              <IconX aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="roi-dashboard-context">
          <div>
            <strong>Mismo ROI, distintos vuelos</strong>
            <span>
              La exportación vuelve a consultar Supabase y utiliza exactamente
              los registros vigentes.
            </span>
          </div>
          <div className="roi-sync-status">
            <i className={loading ? "is-loading" : ""} />
            <span>Última sincronización</span>
            <strong>{syncLabel}</strong>
          </div>
          <span className="modal-record-count">
            {items.length} {items.length === 1 ? "registro" : "registros"}
          </span>
        </div>

        {loading && !chronological.length && (
          <p className="roi-comparison-status">
            <IconLoader2 className="spin" aria-hidden="true" />
            Cargando estadísticas actualizadas…
          </p>
        )}
        {error && (
          <p className="library-error" role="alert">
            {error}
          </p>
        )}

        {chronological.length > 0 && (
          <div
            className={`roi-dashboard-body ${loading ? "is-refreshing" : ""}`}
          >
            {[activeSection].map((section) => {
              const latest = chronological[chronological.length - 1];
              const previous = chronological[chronological.length - 2];
              const latestStats = latest ? statsOf(latest, section.key) : null;
              const previousStats = previous
                ? statsOf(previous, section.key)
                : null;
              const meanDelta =
                latestStats?.mean != null && previousStats?.mean != null
                  ? latestStats.mean - previousStats.mean
                  : null;
              const deviationDelta =
                latestStats?.standard_deviation != null &&
                previousStats?.standard_deviation != null
                  ? latestStats.standard_deviation -
                    previousStats.standard_deviation
                  : null;
              const observedMinimums = chronological
                .map((analysis) => statsOf(analysis, section.key)?.min)
                .filter(
                  (value): value is number =>
                    value != null && Number.isFinite(value),
                );
              const observedMaximums = chronological
                .map((analysis) => statsOf(analysis, section.key)?.max)
                .filter(
                  (value): value is number =>
                    value != null && Number.isFinite(value),
                );
              const globalMinimum = observedMinimums.length
                ? Math.min(...observedMinimums)
                : null;
              const globalMaximum = observedMaximums.length
                ? Math.max(...observedMaximums)
                : null;
              const ribbonValues = chronological
                .map((analysis) => ribbonMetric(analysis, section.key))
                .filter(
                  (value): value is number =>
                    value != null && Number.isFinite(value),
                );
              const ribbonMin = ribbonValues.length
                ? Math.min(...ribbonValues)
                : null;
              const ribbonMax = ribbonValues.length
                ? Math.max(...ribbonValues)
                : null;

              return (
                <section
                  key={section.key}
                  className="roi-index-dashboard-section"
                >
                  <div className="roi-section-heading">
                    <div>
                      <span className="import-eyebrow">{section.label}</span>
                      <h3>{section.title}</h3>
                    </div>
                    <p>
                      Serie temporal del mismo ROI para {section.description.toLowerCase()}.
                    </p>
                  </div>

                  <section
                    className="roi-flight-ribbon"
                    aria-label={`Linea temporal de vuelos ${section.label}`}
                  >
                    <div className="roi-flight-ribbon-header">
                      <div>
                        <span className="import-eyebrow">
                          Mismo ROI, distintos vuelos
                        </span>
                        <strong>Lectura cronologica del indice guardado</strong>
                      </div>
                      <span>
                        {chronological.length}{" "}
                        {chronological.length === 1 ? "vuelo" : "vuelos"}
                      </span>
                    </div>
                    <div className="roi-flight-ribbon-cards">
                      {chronological.map((analysis, index) => {
                        const stats = statsOf(analysis, section.key);
                        const value = stats?.mean ?? null;
                        const normalized =
                          value == null ||
                          ribbonMin == null ||
                          ribbonMax == null ||
                          ribbonMax - ribbonMin <= Number.EPSILON
                            ? 1
                            : (value - ribbonMin) / (ribbonMax - ribbonMin);
                        const isCurrent = index === chronological.length - 1;

                        return (
                          <article
                            key={`ribbon-${section.key}-${analysis.id}`}
                            className={`roi-flight-card ${isCurrent ? "is-current" : ""}`}
                          >
                            <span className="roi-flight-card-label">
                              Vuelo {index + 1}
                            </span>
                            <strong className="roi-flight-card-date">
                              {shortDate(recordDate(analysis))}
                            </strong>
                            <div className="roi-flight-card-metric">
                              {metric(value)}
                            </div>
                            <span className="roi-flight-card-name">
                              {analysis.orthomosaics?.name ?? "Ortomosaico"}
                            </span>
                            <div className="roi-flight-card-bar" aria-hidden="true">
                              <i
                                style={{
                                  width: `${Math.max(8, normalized * 100)}%`,
                                }}
                              />
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  </section>

                  <section
                    className="roi-kpi-grid"
                    aria-label={`Resumen de la comparación ${section.label}`}
                  >
                    <article>
                      <small>Último promedio</small>
                      <strong>{metric(latestStats?.mean)}</strong>
                      <Delta value={meanDelta} />
                    </article>
                    <article>
                      <small>Desviación actual</small>
                      <strong>{metric(latestStats?.standard_deviation)}</strong>
                      <Delta value={deviationDelta} />
                    </article>
                    <article>
                      <small>Rango histórico</small>
                      <strong>
                        {metric(globalMinimum)} <i>—</i> {metric(globalMaximum)}
                      </strong>
                      <span>{chronological.length} vuelos comparados</span>
                    </article>
                    <article>
                      <small>Píxeles del último vuelo</small>
                      <strong>
                        {latestStats?.count.toLocaleString("es-MX") ?? "—"}
                      </strong>
                      <span>
                        {latest ? shortDate(recordDate(latest)) : "Sin fecha"}
                      </span>
                    </article>
                  </section>

                  <section
                    className="roi-kpi-grid"
                    aria-label={`Resumen ampliado de ${section.label}`}
                  >
                    <article>
                      <small>Mediana</small>
                      <strong>{metric(latestStats?.median)}</strong>
                    </article>
                    <article>
                      <small>P10 / P25</small>
                      <strong>
                        {metric(latestStats?.p10)} <i>â€”</i> {metric(latestStats?.p25)}
                      </strong>
                    </article>
                    <article>
                      <small>P75 / P90</small>
                      <strong>
                        {metric(latestStats?.p75)} <i>â€”</i> {metric(latestStats?.p90)}
                      </strong>
                    </article>
                    <article>
                      <small>Rango guardado</small>
                      <strong>
                        {metric(latestStats?.range_min)} <i>â€”</i> {metric(latestStats?.range_max)}
                      </strong>
                    </article>
                  </section>

                  <section
                    className="roi-trends-grid"
                    aria-label={`Tendencias temporales ${section.label}`}
                  >
                    <TrendChart
                      title={`Promedio ${section.label}`}
                      description={`Evolución media de ${section.description.toLowerCase()}`}
                      items={chronological}
                      value={(analysis) => statsOf(analysis, section.key)?.mean ?? null}
                      tone={section.tone}
                    />
                    <TrendChart
                      title="Desviación estándar"
                      description="Dispersión y heterogeneidad dentro del ROI"
                      items={chronological}
                      value={(analysis) =>
                        statsOf(analysis, section.key)?.standard_deviation ?? null
                      }
                      tone="graphite"
                      nonNegative
                    />
                  </section>

                  <section className="roi-detail-section">
                    <div className="roi-section-heading">
                      <div>
                        <span className="import-eyebrow">TRAZABILIDAD</span>
                        <h3>Detalle de mediciones {section.label}</h3>
                      </div>
                      <p>
                        La tabla está ordenada cronológicamente. El CSV conserva
                        toda la precisión recibida, sin redondeo.
                      </p>
                    </div>
                    <div className="roi-comparison-table-wrap">
                      <table className="roi-table roi-comparison-table">
                        <thead>
                          <tr>
                            <th>Fecha</th>
                            <th>Ortomosaico</th>
                            <th>Mín.</th>
                            <th>Máx.</th>
                            <th>Promedio</th>
                            <th>Δ prom.</th>
                            <th>Desv.</th>
                            <th>Δ desv.</th>
                            <th>Píxeles</th>
                            <th aria-label="Acciones" />
                          </tr>
                        </thead>
                        <tbody>
                          {chronological.map((analysis, index) => {
                            const previousAnalysis = chronological[index - 1];
                            const currentStats = statsOf(analysis, section.key);
                            const previousCurrentStats = previousAnalysis
                              ? statsOf(previousAnalysis, section.key)
                              : null;
                            const deviationDifference =
                              currentStats?.standard_deviation != null &&
                              previousCurrentStats?.standard_deviation != null
                                ? currentStats.standard_deviation -
                                  previousCurrentStats.standard_deviation
                                : null;
                            const averageDifference =
                              currentStats?.mean != null &&
                              previousCurrentStats?.mean != null
                                ? currentStats.mean - previousCurrentStats.mean
                                : null;
                            return (
                              <tr key={`${section.key}-${analysis.id}`}>
                                <td>
                                  <strong>{shortDate(recordDate(analysis))}</strong>
                                  <small>
                                    {new Date(analysis.created_at).toLocaleString(
                                      "es-MX",
                                    )}
                                  </small>
                                </td>
                                <td>
                                  <strong>
                                    {analysis.orthomosaics?.name ??
                                      "Ortomosaico eliminado"}
                                  </strong>
                                  <small title={analysis.orthomosaic_id}>
                                    {analysis.orthomosaic_id.slice(0, 8)}…
                                  </small>
                                </td>
                                <td>{metric(currentStats?.min)}</td>
                                <td>{metric(currentStats?.max)}</td>
                                <td>
                                  <strong>{metric(currentStats?.mean)}</strong>
                                </td>
                                <td
                                  className={
                                    averageDifference == null
                                      ? ""
                                      : averageDifference > 0
                                        ? "mean-up"
                                        : averageDifference < 0
                                          ? "mean-down"
                                          : ""
                                  }
                                >
                                  {averageDifference == null
                                    ? "—"
                                    : `${averageDifference > 0 ? "+" : ""}${averageDifference.toFixed(3)}`}
                                </td>
                                <td>
                                  <strong>
                                    {metric(currentStats?.standard_deviation)}
                                  </strong>
                                </td>
                                <td
                                  className={
                                    deviationDifference == null
                                      ? ""
                                      : deviationDifference > 0
                                        ? "metric-up"
                                        : deviationDifference < 0
                                          ? "metric-down"
                                          : ""
                                  }
                                >
                                  {deviationDifference == null
                                    ? "—"
                                    : `${deviationDifference > 0 ? "+" : ""}${deviationDifference.toFixed(3)}`}
                                </td>
                                <td>
                                  {currentStats?.count.toLocaleString("es-MX") ??
                                    "—"}
                                </td>
                                <td className="roi-comparison-actions">
                                  <button
                                    type="button"
                                    className="roi-analysis-delete"
                                    onClick={() => onDelete(analysis)}
                                    disabled={busy}
                                    aria-label={`Eliminar estadísticas de ${analysis.orthomosaics?.name ?? "este ortomosaico"}`}
                                    title="Eliminar estadísticas"
                                  >
                                    {deletingId === analysis.id ? (
                                      <IconLoader2
                                        className="spin"
                                        aria-hidden="true"
                                      />
                                    ) : (
                                      <IconTrash aria-hidden="true" />
                                    )}
                                    <span>
                                      {deletingId === analysis.id
                                        ? "Eliminando…"
                                        : "Eliminar"}
                                    </span>
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </section>
                </section>
              );
            })}
          </div>
        )}
        {!loading && chronological.length === 0 && (
          <div className="roi-dashboard-empty">
            <IconChartLine aria-hidden="true" />
            <strong>No hay estadísticas vigentes</strong>
            <span>
              Guarda una medición multiespectral para comenzar la comparación temporal.
            </span>
          </div>
        )}
      </section>
    </div>
  );
}
