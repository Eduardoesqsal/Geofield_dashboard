import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  IconChartLine,
  IconChevronDown,
  IconDeviceFloppy,
  IconEye,
  IconEyeOff,
  IconX,
} from "@tabler/icons-react";
import type { TreeCollection } from "../types/geo";
import {
  diameterOf,
  sizeOf,
  treeSizeColors,
  treeStats,
  type VisibleTreeSize,
} from "../utils/tree";
import type { IndexAnalysis, NdviAnalysis } from "../hooks/useDashboardMap";
import {
  INDEX_COLOR_RAMPS,
  indexGradient,
  ndviGradient,
  ndviStatsFromValues,
} from "../utils/ndvi";
import type { SaveRoiAnalysisPayload } from "../services/api";

type ComparisonIndex = "NDVI" | "NDWI" | "NDRE";

interface ControlPanelProps {
  data: TreeCollection | null;
  filteredData: TreeCollection | null;
  selectedIndex: ComparisonIndex | null;
  visibleTreeSizes: Record<VisibleTreeSize, boolean>;
  onToggleTreeSize: (size: VisibleTreeSize) => void;
  onDiameterRangeChange: (min: number, max: number) => void;
  ndvi: NdviAnalysis;
  onNdviRangeChange: (min: number, max: number) => void;
  indices: IndexAnalysis[];
  onIndexRangeChange: (
    name: IndexAnalysis["name"],
    min: number,
    max: number,
  ) => void;
  ndviVisible: boolean;
  onToggleNdvi: () => void;
  onToggleIndex: (name: IndexAnalysis["name"]) => void;
  onHideNdvi: () => void;
  onHideIndex: (name: IndexAnalysis["name"]) => void;
  canSaveRoiAnalysis: boolean;
  roiAnalysisSaving: boolean;
  onSaveRoiAnalysis: (payload: SaveRoiAnalysisPayload) => void;
  onOpenRoiComparison: (index: ComparisonIndex) => void;
}

interface EqualizationHistogramProps {
  id: string;
  label: string;
  bins: number[];
  ramp: readonly string[];
  selection: { left: number; right: number };
  meanPosition: number;
  medianPosition: number;
  minimum: number;
  maximum: number;
  selectedCount: number;
  totalCount: number;
  visible: boolean;
  onToggleVisibility: () => void;
  onClose: () => void;
}

function EqualizationHistogram({
  id,
  label,
  bins,
  ramp,
  selection,
  meanPosition,
  medianPosition,
  minimum,
  maximum,
  selectedCount,
  totalCount,
  visible,
  onToggleVisibility,
  onClose,
}: EqualizationHistogramProps) {
  const coverage = totalCount
    ? Math.round((selectedCount / totalCount) * 100)
    : 0;
  const peak = Math.max(...bins, 1);

  return (
    <div className="equalization-card">
      <div className="equalization-toolbar">
        <span className="equalization-badge">Ecualizacion</span>
        <span>
          <b>{selectedCount.toLocaleString()}</b> /{" "}
          {totalCount.toLocaleString()} pixeles
        </span>
        <button
          className={`equalization-visibility ${visible ? "is-on" : "is-off"}`}
          type="button"
          onClick={onToggleVisibility}
          aria-pressed={visible}
          aria-label={visible ? `Apagar ${label}` : `Encender ${label}`}
          title={visible ? `Apagar ${label}` : `Encender ${label}`}
        >
          {visible ? (
            <IconEye aria-hidden="true" />
          ) : (
            <IconEyeOff aria-hidden="true" />
          )}
        </button>
        <button
          className="equalization-dismiss"
          type="button"
          onClick={onClose}
          aria-label="Cerrar histograma"
          title={`Cerrar ${label}`}
        >
          <IconX aria-hidden="true" />
        </button>
      </div>
      <div
        className="equalization-histogram"
        role="img"
        aria-label={`Distribucion y rango activo de ${label}`}
      >
        <div className="equalization-grid" aria-hidden="true">
          {Array.from({ length: 5 }, (_, index) => (
            <i key={index} />
          ))}
        </div>
        <div className="equalization-bars" aria-hidden="true">
          {bins.map((value, index) => {
            const colorIndex = Math.round(
              (index / Math.max(bins.length - 1, 1)) *
                Math.max(ramp.length - 1, 0),
            );
            return (
              <i
                key={`${id}-${index}`}
                style={{
                  height: (value ? Math.max(4, (value / peak) * 100) : 0) + "%",
                  backgroundColor: ramp[colorIndex],
                }}
              />
            );
          })}
        </div>
        <div
          className="equalization-selection"
          style={{
            left: `${selection.left}%`,
            width: `${Math.max(0, selection.right - selection.left)}%`,
          }}
          aria-hidden="true"
        />
        <div
          className="equalization-shade is-left"
          style={{ width: `${selection.left}%` }}
          aria-hidden="true"
        />
        <div
          className="equalization-shade is-right"
          style={{ width: `${100 - selection.right}%` }}
          aria-hidden="true"
        />
        <div
          className="equalization-marker is-mean"
          style={{ left: `${meanPosition}%` }}
          aria-hidden="true"
        >
          <span>u</span>
        </div>
        <div
          className="equalization-marker is-median"
          style={{ left: `${medianPosition}%` }}
          aria-hidden="true"
        >
          <span>M</span>
        </div>
        <div
          className="equalization-color-ramp"
          style={{ background: `linear-gradient(to right, ${ramp.join(", ")})` }}
          aria-hidden="true"
        />
      </div>
      <div className="equalization-readout">
        <span>
          <small>Rango activo</small>
          <strong>
            {minimum.toFixed(2)} - {maximum.toFixed(2)}
          </strong>
        </span>
        <span>
          <small>Cobertura</small>
          <strong>{coverage}%</strong>
        </span>
        <span className="equalization-key">
          <i className="is-mean" />u promedio <i className="is-median" />M
          mediana
        </span>
      </div>
    </div>
  );
}

interface StatisticsDisclosureProps {
  expanded: boolean;
  onToggle: () => void;
  children: ReactNode;
}

function StatisticsDisclosure({
  expanded,
  onToggle,
  children,
}: StatisticsDisclosureProps) {
  return (
    <div className={`statistics-section ${expanded ? "is-expanded" : ""}`}>
      <button
        className="statistics-disclosure"
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span>
          <small>RESUMEN NUMERICO</small>
          <strong>
            {expanded ? "Ocultar estadisticas" : "Mostrar estadisticas"}
          </strong>
        </span>
        <span className="statistics-disclosure-icon">
          <IconChevronDown aria-hidden="true" />
        </span>
      </button>
      {expanded && <div className="statistics-drawer">{children}</div>}
    </div>
  );
}

export function ControlPanel({
  data,
  filteredData,
  selectedIndex,
  visibleTreeSizes,
  onToggleTreeSize,
  onDiameterRangeChange,
  ndvi,
  onNdviRangeChange,
  indices,
  onIndexRangeChange,
  ndviVisible,
  onToggleNdvi,
  onToggleIndex,
  onHideNdvi,
  onHideIndex,
  canSaveRoiAnalysis,
  roiAnalysisSaving,
  onSaveRoiAnalysis,
  onOpenRoiComparison,
}: ControlPanelProps) {
  const stats = treeStats(filteredData);
  const domainStats = treeStats(data);
  const [minimum, setMinimum] = useState(stats.min);
  const [maximum, setMaximum] = useState(stats.max);
  const [detectionPanelVisible, setDetectionPanelVisible] = useState(true);
  const [expandedStatistics, setExpandedStatistics] = useState<
    Record<string, boolean>
  >({});
  const diameters = useMemo(
    () => (data?.features ?? []).map(diameterOf).filter(Number.isFinite),
    [data],
  );
  const domainMax = Math.max(domainStats.max, domainStats.min + 1);
  const toggleStatistics = (key: string) =>
    setExpandedStatistics((current) => ({ ...current, [key]: !current[key] }));

  useEffect(() => {
    setMinimum(stats.min);
    setMaximum(stats.max);
    setDetectionPanelVisible(true);
  }, [data, stats.min, stats.max]);

  const updateRange = (nextMinimum: number, nextMaximum: number) => {
    const safeMinimum = Math.min(nextMinimum, nextMaximum);
    const safeMaximum = Math.max(nextMinimum, nextMaximum);
    setMinimum(safeMinimum);
    setMaximum(safeMaximum);
    onDiameterRangeChange(safeMinimum, safeMaximum);
  };

  const diameterBinEdges = Array.from(
    { length: 29 },
    (_, index) =>
      domainStats.min + ((domainMax - domainStats.min) * index) / 28,
  );
  const diameterBins = Array.from({ length: 28 }, (_, index) => {
    const start = diameterBinEdges[index];
    const end = diameterBinEdges[index + 1];
    return diameters.filter(
      (value) => value >= start && (index === 27 ? value <= end : value < end),
    ).length;
  });
  const diameterPeak = Math.max(...diameterBins, 1);
  const visibleDiameterCount = diameters.filter((diameter) => {
    const category = sizeOf(diameter);
    return (
      diameter >= minimum &&
      diameter <= maximum &&
      category !== "unknown" &&
      visibleTreeSizes[category]
    );
  }).length;

  const histogramBins = (values: number[], min: number, max: number) => {
    const count = 32;
    const range = Math.max(max - min, Number.EPSILON);
    const bins = Array.from({ length: count }, () => 0);
    values.forEach((value) => {
      const index = Math.max(
        0,
        Math.min(count - 1, Math.floor(((value - min) / range) * count)),
      );
      bins[index] += 1;
    });
    return bins;
  };

  const positionInRange = (
    value: number,
    range: { min: number; max: number },
  ) =>
    Math.max(
      0,
      Math.min(
        100,
        ((value - range.min) / Math.max(range.max - range.min, Number.EPSILON)) *
          100,
      ),
    );

  const activeNdviStats = ndvi.roiResponse ? ndvi.roiStats : ndvi.stats;
  const selectedNdviStats = ndviStatsFromValues(
    activeNdviStats.values.filter(
      (value) => value >= ndvi.minimum && value <= ndvi.maximum,
    ),
  );
  const ndviSelection = {
    left: positionInRange(ndvi.minimum, activeNdviStats),
    right: positionInRange(ndvi.maximum, activeNdviStats),
  };
  const roiAnalysisReady = canSaveRoiAnalysis && Boolean(ndvi.roiResponse);
  const hasVisiblePanel = Boolean(selectedIndex || data);

  if (!hasVisiblePanel) return null;

  return (
    <aside className="controls visible">
      {selectedIndex === "NDVI" && ndvi.response && (
        <section className="panel-section ndvi-section">
        <div className="panel-heading">
          <strong>Analisis NDVI</strong>
          <span className="ndvi-range-readout">
            {ndvi.minimum.toFixed(2)} a {ndvi.maximum.toFixed(2)}
          </span>
        </div>
        <EqualizationHistogram
          id="ndvi"
          label="NDVI"
          bins={histogramBins(
            activeNdviStats.values,
            activeNdviStats.min,
            activeNdviStats.max,
          )}
          ramp={INDEX_COLOR_RAMPS.NDVI.ramp}
          selection={ndviSelection}
          meanPosition={positionInRange(activeNdviStats.mean, activeNdviStats)}
          medianPosition={positionInRange(
            activeNdviStats.median,
            activeNdviStats,
          )}
          minimum={ndvi.minimum}
          maximum={ndvi.maximum}
          selectedCount={selectedNdviStats.count}
          totalCount={activeNdviStats.count}
          visible={ndviVisible}
          onToggleVisibility={onToggleNdvi}
          onClose={onHideNdvi}
        />
        <div
          className="ndvi-scale"
          style={{
            background: `linear-gradient(to right, ${ndviGradient(
              ndvi.minimum,
              ndvi.maximum,
            )})`,
          }}
        />
        <div className="ndvi-scale-labels">
          <span>{ndvi.minimum.toFixed(2)}</span>
          <span>NDVI</span>
          <span>{ndvi.maximum.toFixed(2)}</span>
        </div>
        <div className="ndvi-range" aria-label="Rango de contraste NDVI">
          <input
            className="range range-min"
            type="range"
            min={activeNdviStats.min}
            max={activeNdviStats.max}
            step="0.01"
            value={ndvi.minimum}
            onChange={(event) =>
              onNdviRangeChange(
                Math.min(Number(event.target.value), ndvi.maximum),
                Math.max(Number(event.target.value), ndvi.maximum),
              )
            }
            aria-label="Valor minimo NDVI"
          />
          <input
            className="range range-max"
            type="range"
            min={activeNdviStats.min}
            max={activeNdviStats.max}
            step="0.01"
            value={ndvi.maximum}
            onChange={(event) =>
              onNdviRangeChange(
                Math.min(ndvi.minimum, Number(event.target.value)),
                Math.max(ndvi.minimum, Number(event.target.value)),
              )
            }
            aria-label="Valor maximo NDVI"
          />
        </div>
        <StatisticsDisclosure
          expanded={Boolean(expandedStatistics.ndvi)}
          onToggle={() => toggleStatistics("ndvi")}
        >
          <div className="stats-grid ndvi-stats">
            <div>
              <strong>{selectedNdviStats.min.toFixed(2)}</strong>
              <br />
              minimo
            </div>
            <div>
              <strong>{selectedNdviStats.max.toFixed(2)}</strong>
              <br />
              maximo
            </div>
            <div>
              <strong>{selectedNdviStats.mean.toFixed(2)}</strong>
              <br />
              promedio
            </div>
            <div>
              <strong>{selectedNdviStats.median.toFixed(2)}</strong>
              <br />
              mediana
            </div>
            <div>
              <strong>{selectedNdviStats.standardDeviation.toFixed(2)}</strong>
              <br />
              desv. estandar
            </div>
            <div>
              <strong>{selectedNdviStats.count.toLocaleString()}</strong>
              <br />
              pixeles validos
            </div>
            <div>
              <strong>{selectedNdviStats.percentiles.p10.toFixed(2)}</strong>
              <br />
              P10
            </div>
            <div>
              <strong>{selectedNdviStats.percentiles.p25.toFixed(2)}</strong>
              <br />
              P25
            </div>
            <div>
              <strong>{selectedNdviStats.percentiles.p75.toFixed(2)}</strong>
              <br />
              P75
            </div>
            <div>
              <strong>{selectedNdviStats.percentiles.p90.toFixed(2)}</strong>
              <br />
              P90
            </div>
          </div>
          <div className="roi-summary">
            <strong>
              {roiAnalysisReady ? "ROI seleccionada" : "Sin ROI guardable"}
            </strong>
            <span>
              {roiAnalysisReady
                ? "El recorte ya esta listo. Puedes guardar las estadisticas del vuelo actual o abrir el dashboard comparativo."
                : "Recortar un ROI no guarda ni compara por si solo. Activa el flujo correspondiente antes de persistir datos."}
            </span>
            <div className="roi-analysis-actions">
              <button
                type="button"
                onClick={() =>
                  onSaveRoiAnalysis({
                    index: "NDVI",
                    stats: {
                      count: selectedNdviStats.count,
                      min: selectedNdviStats.min,
                      max: selectedNdviStats.max,
                      mean: selectedNdviStats.mean,
                      median: selectedNdviStats.median,
                      standard_deviation:
                        selectedNdviStats.standardDeviation,
                      p10: selectedNdviStats.percentiles.p10,
                      p25: selectedNdviStats.percentiles.p25,
                      p75: selectedNdviStats.percentiles.p75,
                      p90: selectedNdviStats.percentiles.p90,
                      range_min: ndvi.minimum,
                      range_max: ndvi.maximum,
                    },
                  })
                }
                disabled={!canSaveRoiAnalysis || roiAnalysisSaving}
              >
                <IconDeviceFloppy aria-hidden="true" />
                {roiAnalysisSaving ? "Guardando..." : "Guardar estadisticas"}
              </button>
              <button
                type="button"
                onClick={() => onOpenRoiComparison("NDVI")}
                disabled={!canSaveRoiAnalysis}
              >
                <IconChartLine aria-hidden="true" />
                Comparar vuelos
              </button>
            </div>
          </div>
        </StatisticsDisclosure>
        </section>
      )}

      {indices
        .filter((analysis) => analysis.name === selectedIndex)
        .map((analysis) => {
        const selectedStats = ndviStatsFromValues(
          analysis.stats.values.filter(
            (value) => value >= analysis.minimum && value <= analysis.maximum,
          ),
        );
        const selection = {
          left: positionInRange(analysis.minimum, analysis.stats),
          right: positionInRange(analysis.maximum, analysis.stats),
        };

        return (
          <section
            className="panel-section index-histogram-section ndvi-section"
            key={analysis.name}
          >
            <div className="panel-heading">
              <strong>Analisis {analysis.name}</strong>
              <span className="ndvi-range-readout">
                {analysis.minimum.toFixed(2)} a {analysis.maximum.toFixed(2)}
              </span>
            </div>
            <EqualizationHistogram
              id={`index-${analysis.name.toLowerCase()}`}
              label={analysis.name}
              bins={histogramBins(
                analysis.stats.values,
                analysis.stats.min,
                analysis.stats.max,
              )}
              ramp={INDEX_COLOR_RAMPS[analysis.name].ramp}
              selection={selection}
              meanPosition={positionInRange(
                analysis.stats.mean,
                analysis.stats,
              )}
              medianPosition={positionInRange(
                analysis.stats.median,
                analysis.stats,
              )}
              minimum={analysis.minimum}
              maximum={analysis.maximum}
              selectedCount={selectedStats.count}
              totalCount={analysis.stats.count}
              visible={analysis.visible}
              onToggleVisibility={() => onToggleIndex(analysis.name)}
              onClose={() => onHideIndex(analysis.name)}
            />
            <div
              className="ndvi-scale"
              style={{
                background: `linear-gradient(to right, ${indexGradient(
                  analysis.name,
                  analysis.minimum,
                  analysis.maximum,
                )})`,
              }}
            />
            <div className="ndvi-scale-labels">
              <span>{analysis.minimum.toFixed(2)}</span>
              <span>{analysis.name}</span>
              <span>{analysis.maximum.toFixed(2)}</span>
            </div>
            <div
              className="ndvi-range"
              aria-label={`Rango de contraste ${analysis.name}`}
            >
              <input
                className="range range-min"
                type="range"
                min={analysis.stats.min}
                max={analysis.stats.max}
                step="0.01"
                value={analysis.minimum}
                onChange={(event) =>
                  onIndexRangeChange(
                    analysis.name,
                    Number(event.target.value),
                    analysis.maximum,
                  )
                }
                aria-label={`Valor minimo ${analysis.name}`}
              />
              <input
                className="range range-max"
                type="range"
                min={analysis.stats.min}
                max={analysis.stats.max}
                step="0.01"
                value={analysis.maximum}
                onChange={(event) =>
                  onIndexRangeChange(
                    analysis.name,
                    analysis.minimum,
                    Number(event.target.value),
                  )
                }
                aria-label={`Valor maximo ${analysis.name}`}
              />
            </div>
            <StatisticsDisclosure
              expanded={Boolean(expandedStatistics[analysis.name])}
              onToggle={() => toggleStatistics(analysis.name)}
            >
              <div className="stats-grid ndvi-stats">
                <div>
                  <strong>{selectedStats.min.toFixed(2)}</strong>
                  <br />
                  minimo
                </div>
                <div>
                  <strong>{selectedStats.max.toFixed(2)}</strong>
                  <br />
                  maximo
                </div>
                <div>
                  <strong>{selectedStats.mean.toFixed(2)}</strong>
                  <br />
                  promedio
                </div>
                <div>
                  <strong>{selectedStats.median.toFixed(2)}</strong>
                  <br />
                  mediana
                </div>
                <div>
                  <strong>{selectedStats.standardDeviation.toFixed(2)}</strong>
                  <br />
                  desv. estandar
                </div>
                <div>
                  <strong>{selectedStats.count.toLocaleString()}</strong>
                  <br />
                  pixeles validos
                </div>
                <div>
                  <strong>{selectedStats.percentiles.p10.toFixed(2)}</strong>
                  <br />
                  P10
                </div>
                <div>
                  <strong>{selectedStats.percentiles.p25.toFixed(2)}</strong>
                  <br />
                  P25
                </div>
                <div>
                  <strong>{selectedStats.percentiles.p75.toFixed(2)}</strong>
                  <br />
                  P75
                </div>
                <div>
                  <strong>{selectedStats.percentiles.p90.toFixed(2)}</strong>
                  <br />
                  P90
                </div>
              </div>
              <div className="roi-analysis-actions">
                <button
                  type="button"
                  onClick={() =>
                    onSaveRoiAnalysis({
                      index: analysis.name,
                      stats: {
                        count: selectedStats.count,
                        min: selectedStats.min,
                        max: selectedStats.max,
                        mean: selectedStats.mean,
                        median: selectedStats.median,
                        standard_deviation:
                          selectedStats.standardDeviation,
                        p10: selectedStats.percentiles.p10,
                        p25: selectedStats.percentiles.p25,
                        p75: selectedStats.percentiles.p75,
                        p90: selectedStats.percentiles.p90,
                        range_min: analysis.minimum,
                        range_max: analysis.maximum,
                      },
                    })
                  }
                  disabled={!canSaveRoiAnalysis || roiAnalysisSaving}
                >
                  <IconDeviceFloppy aria-hidden="true" />
                  {roiAnalysisSaving ? "Guardando..." : "Guardar estadisticas"}
                </button>
                <button
                  type="button"
                  onClick={() => onOpenRoiComparison(analysis.name)}
                  disabled={!canSaveRoiAnalysis}
                >
                  <IconChartLine aria-hidden="true" />
                  Comparar vuelos
                </button>
              </div>
            </StatisticsDisclosure>
          </section>
        );
      })}

      {data && detectionPanelVisible && (
        <section className="panel-section detection-section">
          <div className="panel-heading">
            <strong>Detecciones por diametro</strong>
            <div
              className="histogram-legend"
              aria-label="Categorias de diametro"
            >
              {(["small", "medium", "large"] as const).map((size) => (
                <button
                  className={`legend-toggle ${visibleTreeSizes[size] ? "is-active" : ""}`}
                  key={size}
                  type="button"
                  aria-pressed={visibleTreeSizes[size]}
                  title={`${visibleTreeSizes[size] ? "Ocultar" : "Mostrar"} detecciones ${size === "small" ? "pequenas" : size === "medium" ? "medianas" : "grandes"}`}
                  onClick={() => onToggleTreeSize(size)}
                >
                  <span
                    className="legend-swatch"
                    style={{ backgroundColor: treeSizeColors[size] }}
                  />
                  {size === "small"
                    ? "<= 2.5 m"
                    : size === "medium"
                      ? "2.5-3.5 m"
                      : "> 3.5 m"}
                </button>
              ))}
              <button
                className="index-close"
                type="button"
                onClick={() => setDetectionPanelVisible(false)}
                aria-label="Cerrar histograma de detecciones"
                title="Cerrar histograma"
              >
                <IconX aria-hidden="true" />
              </button>
            </div>
          </div>
          <div className="tree-histogram" aria-label="Distribucion de diametros">
            <div className="tree-histogram-counter" aria-live="polite">
              <strong>{visibleDiameterCount.toLocaleString()}</strong>
              <span>de {diameters.length.toLocaleString()} en rango</span>
            </div>
            <div className="tree-histogram-bars">
              {diameterBins.map((count, index) => {
                const start = diameterBinEdges[index];
                const end = diameterBinEdges[index + 1];
                const category = sizeOf((start + end) / 2);
                const active =
                  category === "unknown" || visibleTreeSizes[category];
                return (
                  <button
                    key={`${start}-${index}`}
                    className={active ? "is-active" : ""}
                    type="button"
                    disabled={count === 0 || category === "unknown"}
                    style={{
                      height:
                        (count
                          ? Math.max(4, (count / diameterPeak) * 100)
                          : 0) + "%",
                      backgroundColor: treeSizeColors[category],
                    }}
                    title={`${start.toFixed(2)}-${end.toFixed(2)} m: ${count} detecciones`}
                    onClick={() =>
                      category !== "unknown" && onToggleTreeSize(category)
                    }
                    aria-label={`${count} detecciones entre ${start.toFixed(2)} y ${end.toFixed(2)} metros`}
                    aria-pressed={active}
                  />
                );
              })}
            </div>
            <div className="tree-histogram-axis">
              <span>{domainStats.min.toFixed(2)} m</span>
              <span>{domainStats.max.toFixed(2)} m</span>
            </div>
          </div>
          <div className="range-label">
            Filtrando: {minimum.toFixed(2)} m - {maximum.toFixed(2)} m
          </div>
          <div className="diameter-range" aria-label="Rango de diametros">
            <input
              className="range range-min"
              type="range"
              min={domainStats.min}
              max={domainMax}
              step="0.01"
              value={minimum}
              onChange={(event) =>
                updateRange(Number(event.target.value), maximum)
              }
              disabled={!data}
              aria-label="Diametro minimo"
            />
            <input
              className="range range-max"
              type="range"
              min={domainStats.min}
              max={domainMax}
              step="0.01"
              value={maximum}
              onChange={(event) =>
                updateRange(minimum, Number(event.target.value))
              }
              disabled={!data}
              aria-label="Diametro maximo"
            />
          </div>
          <StatisticsDisclosure
            expanded={Boolean(expandedStatistics.trees)}
            onToggle={() => toggleStatistics("trees")}
          >
            <div className="stats-grid">
              <div>
                <strong>{stats.count}</strong>
                <br />
                puntos
              </div>
              <div>
                <strong>{stats.mean.toFixed(2)}</strong>
                <br />
                promedio m
              </div>
              <div>
                <strong>{stats.small}</strong>
                <br />
                pequenos
              </div>
              <div>
                <strong>{stats.medium}</strong>
                <br />
                medianos
              </div>
              <div>
                <strong>{stats.large}</strong>
                <br />
                grandes
              </div>
              <div>
                <strong>{stats.unknown}</strong>
                <br />
                sin diametro
              </div>
            </div>
          </StatisticsDisclosure>
        </section>
      )}
    </aside>
  );
}
