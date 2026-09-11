import { useEffect, useState } from "react";
import {
  IconChartLine,
  IconDownload,
  IconGripVertical,
  IconLoader2,
  IconPencil,
  IconRefresh,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import type { RoiAnalysisRecord } from "../services/api";
import {
  DASHBOARD_VIEWS,
  Delta,
  GEOSCORE_WEIGHTS,
  INDEX_SECTIONS,
  MetricHistoryChart,
  TrendChart,
  chronologicalKey,
  flightLabel,
  metric,
  metricHeatColor,
  recordDate,
  scoreColor,
  shortDate,
  statsOf,
  type DashboardView,
  type HeatmapRow,
  type IndexKey,
  type MetricHistoryModalState,
  type RoiComparisonDialogProps,
  type SummaryDetailRow,
} from "./RoiComparisonDialog.parts";
export function RoiComparisonDialog({
  open,
  activeIndex,
  items,
  loading,
  exporting,
  deletingId,
  error,
  syncedAt,
  activeOrthomosaicId,
  onRefresh,
  onExport,
  onEditFlight,
  onDelete,
  onClose,
}: RoiComparisonDialogProps) {
  const [dashboardView, setDashboardView] =
    useState<DashboardView>("overview");
  const [metricHistory, setMetricHistory] =
    useState<MetricHistoryModalState | null>(null);
  const [selectedOrthomosaicId, setSelectedOrthomosaicId] = useState<
    string | null
  >(null);
  const [editingOrthomosaicId, setEditingOrthomosaicId] = useState<
    string | null
  >(null);
  const [flightOrder, setFlightOrder] = useState<string[]>([]);
  const [draggedFlightId, setDraggedFlightId] = useState<string | null>(null);
  const [dragOverFlightId, setDragOverFlightId] = useState<string | null>(null);
  const orderStorageKey = items[0]?.roi_id
    ? `geofield:roi-flight-order:${items[0].roi_id}`
    : null;
  useEffect(() => {
    setDashboardView("overview");
    setMetricHistory(null);
  }, [activeIndex, open]);
  useEffect(() => {
    if (!open || !items.length) return;
    const activeExists = items.some(
      (analysis) => analysis.orthomosaic_id === activeOrthomosaicId,
    );
    setSelectedOrthomosaicId((current) => {
      if (activeExists) return activeOrthomosaicId;
      if (items.some((analysis) => analysis.orthomosaic_id === current))
        return current;
      return items[0].orthomosaic_id;
    });
  }, [activeOrthomosaicId, items, open]);
  useEffect(() => {
    const defaultOrder = [...items]
      .sort((left, right) =>
        chronologicalKey(left).localeCompare(chronologicalKey(right)),
      )
      .map((analysis) => analysis.orthomosaic_id);
    if (!orderStorageKey) {
      setFlightOrder(defaultOrder);
      return;
    }
    try {
      const stored = JSON.parse(
        window.localStorage.getItem(orderStorageKey) ?? "[]",
      );
      const validStored = Array.isArray(stored)
        ? stored.filter(
            (id): id is string =>
              typeof id === "string" && defaultOrder.includes(id),
          )
        : [];
      setFlightOrder([
        ...validStored,
        ...defaultOrder.filter((id) => !validStored.includes(id)),
      ]);
    } catch {
      setFlightOrder(defaultOrder);
    }
  }, [items, orderStorageKey]);
  if (!open) return null;
  const chronologicalFallback = [...items].sort((left, right) =>
    chronologicalKey(left).localeCompare(chronologicalKey(right)),
  );
  const orderPositions = new Map(
    flightOrder.map((orthomosaicId, index) => [orthomosaicId, index]),
  );
  const chronological = [...chronologicalFallback].sort((left, right) => {
    const leftPosition = orderPositions.get(left.orthomosaic_id);
    const rightPosition = orderPositions.get(right.orthomosaic_id);
    if (leftPosition == null && rightPosition == null) return 0;
    if (leftPosition == null) return 1;
    if (rightPosition == null) return -1;
    return leftPosition - rightPosition;
  });
  const moveFlight = (sourceId: string, targetId: string) => {
    if (sourceId === targetId) return;
    const currentOrder = chronological.map(
      (analysis) => analysis.orthomosaic_id,
    );
    const sourceIndex = currentOrder.indexOf(sourceId);
    const originalTargetIndex = currentOrder.indexOf(targetId);
    if (sourceIndex < 0 || originalTargetIndex < 0) return;
    const nextOrder = [...currentOrder];
    const [moved] = nextOrder.splice(sourceIndex, 1);
    const targetIndex = nextOrder.indexOf(targetId);
    nextOrder.splice(
      sourceIndex < originalTargetIndex ? targetIndex + 1 : targetIndex,
      0,
      moved,
    );
    setFlightOrder(nextOrder);
    if (orderStorageKey) {
      try {
        window.localStorage.setItem(orderStorageKey, JSON.stringify(nextOrder));
      } catch {
        // El orden visual sigue funcionando aunque el navegador bloquee storage.
      }
    }
    setDraggedFlightId(null);
    setDragOverFlightId(null);
  };
  const resetFlightOrder = () => {
    const defaultOrder = chronologicalFallback.map(
      (analysis) => analysis.orthomosaic_id,
    );
    setFlightOrder(defaultOrder);
    if (orderStorageKey) {
      try {
        window.localStorage.removeItem(orderStorageKey);
      } catch {
        // No interrumpir el restablecimiento visual si storage no esta disponible.
      }
    }
  };
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
                Dashboard comparativo de Ã­ndices
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
              <span>{loading ? "Actualizandoâ€¦" : "Actualizar"}</span>
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
              <span>{exporting ? "Consultandoâ€¦" : "Exportar CSV real"}</span>
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
              La exportaciÃ³n vuelve a consultar Supabase y utiliza exactamente
              los registros vigentes.
            </span>
          </div>
          <div className="roi-sync-status">
            <i className={loading ? "is-loading" : ""} />
            <span>Ãšltima sincronizaciÃ³n</span>
            <strong>{syncLabel}</strong>
          </div>
          <span className="modal-record-count">
            {items.length} {items.length === 1 ? "registro" : "registros"}
          </span>
        </div>
        {loading && !chronological.length && (
          <p className="roi-comparison-status">
            <IconLoader2 className="spin" aria-hidden="true" />
            Cargando estadÃ­sticas actualizadasâ€¦
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
              const selectedFlightIndex = chronological.findIndex(
                (analysis) =>
                  analysis.orthomosaic_id === selectedOrthomosaicId,
              );
              const currentFlightIndex =
                selectedFlightIndex >= 0
                  ? selectedFlightIndex
                  : chronological.length - 1;
              const latest = chronological[currentFlightIndex];
              const previous = chronological[currentFlightIndex - 1];
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
              const latestAverageTone =
                latestStats?.mean == null
                  ? "Sin lectura disponible."
                  : meanDelta == null
                    ? "Primer vuelo comparable disponible para este indice."
                    : meanDelta > 0
                      ? "El promedio actual esta por encima del vuelo anterior."
                      : meanDelta < 0
                        ? "El promedio actual esta por debajo del vuelo anterior."
                        : "El promedio se mantuvo estable frente al vuelo anterior.";
              const latestDispersionTone =
                latestStats?.standard_deviation == null
                  ? "No hay dispersion calculable."
                  : deviationDelta == null
                    ? "Aun no existe vuelo previo para contrastar heterogeneidad."
                    : deviationDelta > 0
                      ? "La heterogeneidad interna aumento respecto al vuelo anterior."
                      : deviationDelta < 0
                        ? "La heterogeneidad interna disminuyo frente al vuelo anterior."
                        : "La dispersion se mantuvo sin cambios relevantes.";
              const latestCaptureLabel = latest
                ? shortDate(recordDate(latest))
                : "Sin fecha";
              const realDataChecklist = [
                latestStats?.mean != null
                  ? `Promedio real ${section.label}: ${metric(latestStats.mean)}`
                  : null,
                latestStats?.standard_deviation != null
                  ? `Desviacion real: ${metric(latestStats.standard_deviation)}`
                  : null,
                latestStats?.count != null
                  ? `Pixeles validos guardados: ${latestStats.count.toLocaleString("es-MX")}`
                  : null,
                latest?.orthomosaics?.name
                  ? `Ortomosaico seleccionado: ${latest.orthomosaics.name}`
                  : null,
              ].filter((item): item is string => Boolean(item));
              const heatmapRows: HeatmapRow[] = [
                {
                  key: "mean",
                  label: `Promedio ${section.label}`,
                  digits: 3,
                  values: chronological.map(
                    (analysis) => statsOf(analysis, section.key)?.mean ?? null,
                  ),
                },
                {
                  key: "stddev",
                  label: "Desviacion",
                  digits: 3,
                  values: chronological.map(
                    (analysis) =>
                      statsOf(analysis, section.key)?.standard_deviation ?? null,
                  ),
                },
                {
                  key: "median",
                  label: "Mediana",
                  digits: 3,
                  values: chronological.map(
                    (analysis) => statsOf(analysis, section.key)?.median ?? null,
                  ),
                },
                {
                  key: "p10",
                  label: "P10",
                  digits: 3,
                  values: chronological.map(
                    (analysis) => statsOf(analysis, section.key)?.p10 ?? null,
                  ),
                },
                {
                  key: "p90",
                  label: "P90",
                  digits: 3,
                  values: chronological.map(
                    (analysis) => statsOf(analysis, section.key)?.p90 ?? null,
                  ),
                },
                {
                  key: "pixels",
                  label: "Pixeles",
                  digits: 0,
                  values: chronological.map(
                    (analysis) => statsOf(analysis, section.key)?.count ?? null,
                  ),
                },
              ];
              const latestDetailRows: SummaryDetailRow[] = [
                {
                  label: "Vuelo seleccionado",
                  value: latestCaptureLabel,
                },
                {
                  label: "Ortomosaico",
                  value: latest?.orthomosaics?.name ?? "Sin ortomosaico",
                },
                {
                  label: "Promedio",
                  value: metric(latestStats?.mean),
                  tone:
                    meanDelta == null
                      ? "neutral"
                      : meanDelta > 0
                        ? "up"
                        : meanDelta < 0
                          ? "down"
                          : "neutral",
                },
                {
                  label: "Desviacion",
                  value: metric(latestStats?.standard_deviation),
                  tone:
                    deviationDelta == null
                      ? "neutral"
                      : deviationDelta > 0
                        ? "down"
                        : deviationDelta < 0
                          ? "up"
                          : "neutral",
                },
                {
                  label: "Mediana",
                  value: metric(latestStats?.median),
                },
                {
                  label: "Pixeles",
                  value:
                    latestStats?.count?.toLocaleString("es-MX") ?? "-",
                },
              ];
              const watchlistItems = [
                meanDelta == null
                  ? `Aun no existe un vuelo previo para contrastar ${section.label}.`
                  : meanDelta < 0
                    ? `El promedio actual de ${section.label} cayo ${Math.abs(meanDelta).toFixed(3)} frente al vuelo anterior.`
                    : meanDelta > 0
                      ? `El promedio actual de ${section.label} subio ${meanDelta.toFixed(3)} frente al vuelo anterior.`
                      : `El promedio actual de ${section.label} se mantuvo estable frente al vuelo anterior.`,
                deviationDelta == null
                  ? "La dispersion todavia no tiene referencia previa."
                  : deviationDelta > 0
                    ? `La heterogeneidad interna aumento ${deviationDelta.toFixed(3)} y conviene revisar focos dentro del ROI.`
                    : deviationDelta < 0
                      ? `La heterogeneidad interna disminuyo ${Math.abs(deviationDelta).toFixed(3)} respecto al vuelo anterior.`
                      : "La dispersion no cambio de forma relevante.",
                latestStats?.count != null && latestStats.count < 500
                  ? "La muestra de pixeles validos es reducida; conviene revisar el recorte o el umbral aplicado."
                  : `La muestra actual contiene ${latestStats?.count?.toLocaleString("es-MX") ?? "0"} pixeles validos persistidos.`,
              ];
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
                  <nav
                    className="roi-dashboard-view-switcher"
                    aria-label={`Vistas del dashboard ${section.label}`}
                  >
                    {DASHBOARD_VIEWS.map((view) => (
                      <button
                        key={view.key}
                        type="button"
                        className={dashboardView === view.key ? "is-active" : ""}
                        onClick={() => setDashboardView(view.key)}
                      >
                        <strong>{view.label}</strong>
                        <span>{view.description}</span>
                      </button>
                    ))}
                  </nav>
                  <section
                    className={`roi-flight-ribbon ${dashboardView !== "overview" ? "is-hidden-view" : ""}`}
                    aria-label={`Linea temporal de vuelos ${section.label}`}
                  >
                    <div className="roi-flight-ribbon-header">
                      <div>
                        <span className="import-eyebrow">
                          Mismo ROI, distintos vuelos
                        </span>
                        <strong>Orden de lectura del indice guardado</strong>
                      </div>
                      <div className="roi-flight-ribbon-tools">
                        <button type="button" onClick={resetFlightOrder}>
                          Orden cronologico
                        </button>
                        <span>
                          {chronological.length}{" "}
                          {chronological.length === 1 ? "vuelo" : "vuelos"}
                        </span>
                      </div>
                    </div>
                    <p className="roi-flight-reorder-help">
                      Arrastra las tarjetas para acomodar los vuelos. El orden se conserva para este ROI.
                    </p>
                    <div className="roi-flight-ribbon-cards">
                      {chronological.map((analysis, index) => {
                        const stats = statsOf(analysis, section.key);
                        const value = stats?.mean ?? null;
                        const isCurrent =
                          analysis.orthomosaic_id === latest?.orthomosaic_id;
                        const isActive =
                          analysis.orthomosaic_id === activeOrthomosaicId;
                        return (
                          <button
                            type="button"
                            key={`ribbon-${section.key}-${analysis.id}`}
                            className={`roi-flight-card ${isCurrent ? "is-current" : ""} ${isActive ? "is-active-flight" : ""} ${draggedFlightId === analysis.orthomosaic_id ? "is-dragging" : ""} ${dragOverFlightId === analysis.orthomosaic_id ? "is-drag-over" : ""}`}
                            draggable={chronological.length > 1}
                            onDragStart={(event) => {
                              event.dataTransfer.effectAllowed = "move";
                              event.dataTransfer.setData(
                                "text/plain",
                                analysis.orthomosaic_id,
                              );
                              setDraggedFlightId(analysis.orthomosaic_id);
                            }}
                            onDragOver={(event) => {
                              if (
                                !draggedFlightId ||
                                draggedFlightId === analysis.orthomosaic_id
                              )
                                return;
                              event.preventDefault();
                              event.dataTransfer.dropEffect = "move";
                              setDragOverFlightId(analysis.orthomosaic_id);
                            }}
                            onDrop={(event) => {
                              event.preventDefault();
                              if (draggedFlightId) {
                                moveFlight(
                                  draggedFlightId,
                                  analysis.orthomosaic_id,
                                );
                              }
                            }}
                            onDragEnd={() => {
                              setDraggedFlightId(null);
                              setDragOverFlightId(null);
                            }}
                            onClick={() =>
                              setSelectedOrthomosaicId(analysis.orthomosaic_id)
                            }
                            aria-pressed={isCurrent}
                          >
                            <span className="roi-flight-card-grip">
                              <IconGripVertical aria-hidden="true" />
                              Mover
                            </span>
                            <span className="roi-flight-card-label">
                              {flightLabel(analysis, index)}
                              {isActive && <i>Activo</i>}
                            </span>
                            <strong className="roi-flight-card-date">
                              {shortDate(recordDate(analysis))}
                            </strong>
                            <div className="roi-flight-card-metric">
                              {metric(value)}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                    {latest && (
                      <div className="roi-flight-selection-actions">
                        <span>
                          Seleccionado:{" "}
                          <strong>{flightLabel(latest, currentFlightIndex)}</strong>
                        </span>
                        <button
                          type="button"
                          disabled={busy || editingOrthomosaicId !== null}
                          onClick={() => {
                            setEditingOrthomosaicId(latest.orthomosaic_id);
                            void onEditFlight(latest.orthomosaic_id)
                              .catch(() => undefined)
                              .finally(() => setEditingOrthomosaicId(null));
                          }}
                        >
                          {editingOrthomosaicId === latest.orthomosaic_id ? (
                            <IconLoader2 className="spin" aria-hidden="true" />
                          ) : (
                            <IconPencil aria-hidden="true" />
                          )}
                          Editar estadÃ­sticas de este vuelo
                        </button>
                      </div>
                    )}
                  </section>
                  <section
                    className={`roi-kpi-grid ${dashboardView !== "overview" ? "is-hidden-view" : ""}`}
                    aria-label={`Resumen de la comparaciÃ³n ${section.label}`}
                  >
                    <article>
                      <small>Promedio seleccionado</small>
                      <strong>{metric(latestStats?.mean)}</strong>
                      <Delta value={meanDelta} />
                    </article>
                    <article>
                      <small>DesviaciÃ³n seleccionada</small>
                      <strong>{metric(latestStats?.standard_deviation)}</strong>
                      <Delta value={deviationDelta} />
                    </article>
                    <article>
                      <small>Rango histÃ³rico</small>
                      <strong>
                        {metric(globalMinimum)} <i>â€”</i> {metric(globalMaximum)}
                      </strong>
                      <span>{chronological.length} vuelos comparados</span>
                    </article>
                    <article>
                      <small>PÃ­xeles del vuelo seleccionado</small>
                      <strong>
                        {latestStats?.count.toLocaleString("es-MX") ?? "-"}
                      </strong>
                      <span>
                        {latest ? shortDate(recordDate(latest)) : "Sin fecha"}
                      </span>
                    </article>
                  </section>
                  <section
                    className={`roi-kpi-grid ${dashboardView !== "overview" ? "is-hidden-view" : ""}`}
                    aria-label={`Resumen ampliado de ${section.label}`}
                  >
                    <article>
                      <small>Mediana</small>
                      <strong>{metric(latestStats?.median)}</strong>
                    </article>
                    <article>
                      <small>P10 / P25</small>
                      <strong>
                        {metric(latestStats?.p10)} <i>-</i> {metric(latestStats?.p25)}
                      </strong>
                    </article>
                    <article>
                      <small>P75 / P90</small>
                      <strong>
                        {metric(latestStats?.p75)} <i>-</i> {metric(latestStats?.p90)}
                      </strong>
                    </article>
                    <article>
                      <small>Rango guardado</small>
                      <strong>
                        {metric(latestStats?.range_min)} <i>-</i> {metric(latestStats?.range_max)}
                      </strong>
                    </article>
                  </section>
                  <div
                    className={`roi-dashboard-note ${dashboardView !== "overview" ? "is-hidden-view" : ""}`}
                  >
                    <strong>Lectura del vuelo seleccionado</strong>
                    <span>
                      {latestAverageTone} {latestDispersionTone}
                    </span>
                  </div>
                  <section
                    className={`roi-trends-grid ${dashboardView !== "trends" ? "is-hidden-view" : ""}`}
                    aria-label={`Tendencias temporales ${section.label}`}
                  >
                    <TrendChart
                      title={`Promedio ${section.label}`}
                      description={`EvoluciÃ³n media de ${section.description.toLowerCase()}`}
                      items={chronological}
                      value={(analysis) => statsOf(analysis, section.key)?.mean ?? null}
                      tone={section.tone}
                    />
                    <TrendChart
                      title="DesviaciÃ³n estÃ¡ndar"
                      description="DispersiÃ³n y heterogeneidad dentro del ROI"
                      items={chronological}
                      value={(analysis) =>
                        statsOf(analysis, section.key)?.standard_deviation ?? null
                      }
                      tone="graphite"
                      nonNegative
                    />
                  </section>
                  <section
                    className={`roi-heatmap-card ${dashboardView !== "trends" ? "is-hidden-view" : ""}`}
                    aria-label={`Mapa de calor temporal ${section.label}`}
                  >
                    <div className="roi-heatmap-heading">
                      <div>
                        <strong>Evolucion real del ROI por vuelo</strong>
                        <span>
                          Una fila por mÃ©trica persistida. El recuadro oscuro marca
                          el vuelo seleccionado.
                        </span>
                      </div>
                    </div>
                    <div className="roi-heatmap-wrap">
                      <table className="roi-heatmap-table">
                        <thead>
                          <tr>
                            <th />
                            {chronological.map((analysis, index) => (
                              <th key={`${section.key}-flight-${analysis.id}`}>
                                {flightLabel(analysis, index)}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {heatmapRows.map((row) => {
                            const numericValues = row.values.filter(
                              (value): value is number =>
                                value != null && Number.isFinite(value),
                            );
                            const minimum = numericValues.length
                              ? Math.min(...numericValues)
                              : 0;
                            const maximum = numericValues.length
                              ? Math.max(...numericValues)
                              : 1;
                            return (
                              <tr
                                key={`${section.key}-${row.key}`}
                                className="is-clickable"
                                onClick={() =>
                                  setMetricHistory({
                                    key: row.key,
                                    label: row.label,
                                    digits: row.digits ?? 3,
                                    suffix: row.suffix ?? "",
                                    values: row.values,
                                  })
                                }
                                title={`Ver historial de ${row.label}`}
                              >
                                <td className="lbl">{row.label}</td>
                                {row.values.map((value, index) => (
                                  <td
                                    key={`${section.key}-${row.key}-${index}`}
                                    className={
                                      index === currentFlightIndex ? "now" : ""
                                    }
                                    style={{
                                      background: metricHeatColor(
                                        value,
                                        minimum,
                                        maximum,
                                      ),
                                    }}
                                    title={
                                      value == null
                                        ? `${row.label}: sin dato`
                                        : `${row.label}: ${metric(value, row.digits ?? 3)}${row.suffix ?? ""}`
                                    }
                                  >
                                    {value == null
                                      ? "-"
                                      : row.key === "pixels"
                                        ? value.toLocaleString("es-MX")
                                        : `${metric(value, row.digits ?? 3)}${row.suffix ?? ""}`}
                                  </td>
                                ))}
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <p className="roi-heatmap-note">
                      <b>Que buscar:</b> una fila que se oscurece o se apaga de
                      forma sostenida hacia la derecha revela un cambio real del
                      ROI entre vuelos guardados, no solo una variacion aislada.
                    </p>
                  </section>
                  <section
                    className={`roi-operational-grid ${dashboardView !== "trends" ? "is-hidden-view" : ""}`}
                  >
                    <article className="roi-operational-card">
                      <h3>Que revisar en campo</h3>
                      <p className="sub">
                        Alertas construidas con los cambios reales del ROI en el
                        vuelo seleccionado.
                      </p>
                      <div className="roi-operational-list">
                        {watchlistItems.map((item, index) => (
                          <article
                            key={`${section.key}-watch-${index}`}
                            className={`roi-operational-alert ${index === 0 && meanDelta != null && meanDelta < 0 ? "is-bad" : "is-warn"}`}
                          >
                            <div className="t">
                              {index === 0 && meanDelta != null && meanDelta < 0
                                ? "Cambio prioritario"
                                : "Seguimiento"}
                            </div>
                            <p>{item}</p>
                          </article>
                        ))}
                      </div>
                    </article>
                    <article className="roi-operational-card">
                      <h3>Detalle del vuelo</h3>
                      <p className="sub">
                        Resumen del ultimo registro persistido para {section.label}.
                      </p>
                      <table className="roi-detail-summary-table">
                        <tbody>
                          {latestDetailRows.map((row) => (
                            <tr key={`${section.key}-${row.label}`}>
                              <td>{row.label}</td>
                              <td
                                className={
                                  row.tone === "up"
                                    ? "is-up"
                                    : row.tone === "down"
                                      ? "is-down"
                                      : ""
                                }
                              >
                                {row.value}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p className="roi-heatmap-note">
                        <b>Lectura operativa:</b> este detalle sale del mismo
                        registro guardado que alimenta curvas, heatmap y
                        trazabilidad para este ROI.
                      </p>
                    </article>
                  </section>
                  <section
                    className={`roi-dashboard-insights roi-dashboard-insights--triple ${dashboardView !== "methodology" ? "is-hidden-view" : ""}`}
                  >
                    <article className="roi-dashboard-insight-card">
                      <small>Lectura rapida</small>
                      <strong>
                        {section.label} en {chronological.length} vuelos
                      </strong>
                      <p>
                        Esta serie muestra la evolucion del mismo ROI a lo largo
                        del tiempo y reemplaza por completo la vista al cambiar
                        de indice.
                      </p>
                    </article>
                    <article className="roi-dashboard-insight-card">
                      <small>Fuente de verdad</small>
                      <strong>Registros persistidos del ROI</strong>
                      <p>
                        Todas las metricas, curvas y la tabla historica se
                        construyen a partir de analisis guardados para este
                        indice y este mismo ROI.
                      </p>
                    </article>
                    <article className="roi-geoscore-card">
                      <div className="roi-geoscore-header">
                        <small>GeoScore</small>
                        <strong>Como se calcula</strong>
                        <p>
                          Escala 0-100 por tabla. El lote es el promedio
                          ponderado por hectareas.
                        </p>
                      </div>
                      <div className="roi-geoscore-list">
                        {GEOSCORE_WEIGHTS.map((item) => (
                          <article key={item.title} className="roi-geoscore-item">
                            <span>{item.weight}</span>
                            <div>
                              <strong>{item.title}</strong>
                              <p>{item.description}</p>
                            </div>
                          </article>
                        ))}
                      </div>
                      <div className="roi-geoscore-footnote">
                        <strong>Indice rector segun etapa</strong>
                        <p>
                          El vigor se mide con NDVI hasta cobertura plena, con
                          GNDVI en la meseta y con NDRE de ahi en adelante,
                          porque el NDVI se satura y deja de distinguir.
                        </p>
                      </div>
                    </article>
                  </section>
                  <section
                    className={`roi-detail-section ${dashboardView !== "traceability" ? "is-hidden-view" : ""}`}
                  >
                    <div className="roi-section-heading">
                      <div>
                        <span className="import-eyebrow">TRAZABILIDAD</span>
                        <h3>Detalle de mediciones {section.label}</h3>
                      </div>
                      <p>
                        La tabla estÃ¡ ordenada cronolÃ³gicamente. El CSV conserva
                        toda la precisiÃ³n recibida, sin redondeo.
                      </p>
                    </div>
                    <div className="roi-comparison-table-wrap">
                      <table className="roi-table roi-comparison-table">
                        <thead>
                          <tr>
                            <th>Fecha</th>
                            <th>Ortomosaico</th>
                            <th>MÃ­n.</th>
                            <th>MÃ¡x.</th>
                            <th>Promedio</th>
                            <th>Î” prom.</th>
                            <th>Desv.</th>
                            <th>Î” desv.</th>
                            <th>PÃ­xeles</th>
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
                                    {analysis.orthomosaic_id.slice(0, 8)}â€¦
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
                                    ? "-"
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
                                    ? "-"
                                    : `${deviationDifference > 0 ? "+" : ""}${deviationDifference.toFixed(3)}`}
                                </td>
                                <td>
                                  {currentStats?.count.toLocaleString("es-MX") ??
                                    "-"}
                                </td>
                                <td className="roi-comparison-actions">
                                  <button
                                    type="button"
                                    className="roi-analysis-delete"
                                    onClick={() => onDelete(analysis)}
                                    disabled={busy}
                                    aria-label={`Eliminar estadÃ­sticas de ${analysis.orthomosaics?.name ?? "este ortomosaico"}`}
                                    title="Eliminar estadÃ­sticas"
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
                                        ? "Eliminandoâ€¦"
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
                    <p className="roi-detail-note">
                      La trazabilidad conserva los valores historicos del indice
                      seleccionado y permite contrastar vuelo actual contra vuelo
                      anterior sin mezclar indices distintos.
                    </p>
                  </section>
                  <section
                    className={`roi-methodology-section ${dashboardView !== "methodology" ? "is-hidden-view" : ""}`}
                  >
                    <div className="roi-section-heading">
                      <div>
                        <span className="import-eyebrow">LECTURA REAL</span>
                        <h3>Que datos usa hoy este dashboard</h3>
                      </div>
                      <p>
                        Este panel solo muestra informacion persistida y real del
                        ROI seleccionado para el indice activo.
                      </p>
                    </div>
                    <div className="roi-methodology-grid">
                      <article className="roi-methodology-card">
                        <small>Fuente actual</small>
                        <strong>ROI + indice + vuelos guardados</strong>
                        <p>
                          La comparacion vigente se construye con los registros
                          guardados en base de datos para {section.label}, sin
                          mezclar otros indices.
                        </p>
                        <ul>
                          <li>{chronological.length} vuelos persistidos para este ROI.</li>
                          <li>Ultima lectura disponible: {latestCaptureLabel}.</li>
                          {realDataChecklist.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </article>
                      <article className="roi-methodology-card">
                        <small>Lo que ya se interpreta</small>
                        <strong>Temporalidad real del ROI</strong>
                        <p>
                          Con los datos actuales el panel puede mostrar tendencia,
                          dispersion, rango historico, diferencias entre vuelos y
                          trazabilidad completa del mismo ROI.
                        </p>
                        <ul>
                          <li>Resumen numerico del ultimo vuelo guardado.</li>
                          <li>Curvas temporales por indice.</li>
                          <li>Tabla historica cronologica con deltas.</li>
                          <li>CSV exportado desde registros vigentes.</li>
                        </ul>
                      </article>
                      <article className="roi-methodology-card">
                        <small>Lo que falta para el demo avanzado</small>
                        <strong>Datos que hoy no existen en esta API</strong>
                        <p>
                          La vista tipo cuadrantes, GeoScore por tabla, ranking de
                          tablas hermanas, mapa de calor por tabla y anotaciones
                          de campo requieren una fuente mas granular que el ROI.
                        </p>
                        <ul>
                          <li>Subdivision real por tablas o bloques productivos.</li>
                          <li>Hectareas por tabla y relacion de tablas hermanas.</li>
                          <li>CV relativo, cobertura y area bajo umbral por tabla.</li>
                          <li>Indice rector por etapa, incluyendo GNDVI.</li>
                          <li>Anotaciones de campo con estado, autor y evidencia.</li>
                        </ul>
                      </article>
                    </div>
                    <article className="roi-methodology-note">
                      <strong>Conclusion operativa</strong>
                      <p>
                        Si quieres esa experiencia completa como en el ejemplo,
                        hay que extender primero el modelo de datos y las
                        consultas del backend a nivel tabla. Mientras eso no
                        exista, cualquier cuadrante o GeoScore por tabla seria
                        decorativo y no representaria datos reales.
                      </p>
                    </article>
                  </section>
                </section>
              );
            })}
          </div>
        )}
        {!loading && chronological.length === 0 && (
          <div className="roi-dashboard-empty">
            <IconChartLine aria-hidden="true" />
            <strong>No hay estadÃ­sticas vigentes</strong>
            <span>
              Guarda una mediciÃ³n multiespectral para comenzar la comparaciÃ³n temporal.
            </span>
          </div>
        )}
        {metricHistory && chronological.length > 0 && (
          <div
            className="roi-metric-modal-backdrop"
            role="presentation"
            onMouseDown={() => setMetricHistory(null)}
          >
            <section
              className="roi-metric-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="roi-metric-modal-title"
              onMouseDown={(event) => event.stopPropagation()}
            >
              <div className="roi-metric-modal-head">
                <div>
                  <div className="roi-metric-modal-id" id="roi-metric-modal-title">
                    {metricHistory.label}
                    <em>{activeSection.label}</em>
                  </div>
                  <div className="roi-metric-modal-meta">
                    ROI actual Â· {chronological.length} vuelos guardados Â· ultimo vuelo{" "}
                    <b>{shortDate(recordDate(chronological[chronological.length - 1]))}</b>
                  </div>
                </div>
                <button
                  type="button"
                  className="roi-metric-modal-close"
                  onClick={() => setMetricHistory(null)}
                  aria-label="Cerrar historial"
                >
                  Ã—
                </button>
              </div>
              <div className="roi-metric-modal-kpis">
                <div>
                  <div className="l">Valor actual</div>
                  <div className="v">
                    {(() => {
                      const latestValue =
                        metricHistory.values[metricHistory.values.length - 1];
                      return latestValue == null
                        ? "-"
                        : `${metric(latestValue, metricHistory.digits)}${metricHistory.suffix}`;
                    })()}
                  </div>
                </div>
                <div>
                  <div className="l">Mejor vuelo</div>
                  <div className="v">
                    {(() => {
                      const enriched = metricHistory.values
                        .map((value, index) => ({ value, index }))
                        .filter(
                          (
                            item,
                          ): item is {
                            value: number;
                            index: number;
                          } => item.value != null && Number.isFinite(item.value),
                        );
                      if (!enriched.length) return "-";
                      const best = [...enriched].sort(
                        (left, right) => right.value - left.value,
                      )[0];
                      return flightLabel(chronological[best.index], best.index);
                    })()}
                  </div>
                </div>
                <div>
                  <div className="l">Peor vuelo</div>
                  <div className="v">
                    {(() => {
                      const enriched = metricHistory.values
                        .map((value, index) => ({ value, index }))
                        .filter(
                          (
                            item,
                          ): item is {
                            value: number;
                            index: number;
                          } => item.value != null && Number.isFinite(item.value),
                        );
                      if (!enriched.length) return "-";
                      const worst = [...enriched].sort(
                        (left, right) => left.value - right.value,
                      )[0];
                      return flightLabel(
                        chronological[worst.index],
                        worst.index,
                      );
                    })()}
                  </div>
                </div>
                <div>
                  <div className="l">Cambio total</div>
                  <div className="v">
                    {(() => {
                      const enriched = metricHistory.values.filter(
                        (value): value is number =>
                          value != null && Number.isFinite(value),
                      );
                      if (enriched.length < 2) return "-";
                      const delta = enriched[enriched.length - 1] - enriched[0];
                      return `${delta > 0 ? "+" : ""}${delta.toFixed(metricHistory.digits)}${metricHistory.suffix}`;
                    })()}
                  </div>
                </div>
              </div>
              <div className="roi-metric-modal-body">
                <MetricHistoryChart
                  title={`Historial de ${metricHistory.label}`}
                  description="Valores absolutos en los vuelos guardados del ROI."
                  items={chronological}
                  values={metricHistory.values}
                  digits={metricHistory.digits}
                  suffix={metricHistory.suffix}
                />
                <MetricHistoryChart
                  title={`Cambio relativo de ${metricHistory.label}`}
                  description="Cada vuelo se expresa respecto al primer vuelo valido de la serie."
                  items={chronological}
                  values={metricHistory.values}
                  digits={2}
                  suffix=""
                  relative
                />
                <div className="roi-metric-modal-read">
                  <p>
                    <b>Lectura:</b> esta grafica usa exclusivamente los registros
                    reales guardados para el ROI actual. La curva superior muestra
                    valores absolutos; la inferior muestra como cambia la metrica
                    respecto al primer vuelo valido de la serie.
                  </p>
                </div>
              </div>
            </section>
          </div>
        )}
      </section>
    </div>
  );
}

