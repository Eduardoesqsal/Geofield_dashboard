/**
 * Panel lateral principal del análisis.
 * Aquí se muestran histogramas, sliders, estadísticas, toggles de índices
 * y acciones de guardado/comparación vinculadas al ROI activo.
 */
import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  IconChartLine,
  IconChevronDown,
  IconDeviceFloppy,
  IconEye,
  IconEyeOff,
  IconGridDots,
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
  buildHistogramEqualization,
  equalizedPosition,
  type ClassificationFillMode,
  INDEX_COLOR_RAMPS,
  indexColorFromPosition,
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
  onNdviEqualizationChange: (enabled: boolean) => void;
  onNdviFillModeChange: (mode: ClassificationFillMode) => void;
  indices: IndexAnalysis[];
  onIndexRangeChange: (
    name: IndexAnalysis["name"],
    min: number,
    max: number,
  ) => void;
  onIndexEqualizationChange: (
    name: IndexAnalysis["name"],
    enabled: boolean,
  ) => void;
  onIndexFillModeChange: (
    name: IndexAnalysis["name"],
    mode: ClassificationFillMode,
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
  prescriptionMode: "idle" | "zoning" | "prescription";
  prescriptionLoading: boolean;
  onOpenPrescription: () => void;
  onExitPrescription: () => void;
}

interface EqualizationHistogramProps {
  id: string;
  label: string;
  indexName: ComparisonIndex;
  values: number[];
  domainMinimum: number;
  domainMaximum: number;
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
  equalized: boolean;
  fillMode: ClassificationFillMode;
  onEqualizationChange: (enabled: boolean) => void;
  onFillModeChange: (mode: ClassificationFillMode) => void;
  onToggleVisibility: () => void;
  onClose: () => void;
}

function formatIndexRangeValue(value: number): string {
  return Number.isFinite(value) ? value.toFixed(3) : "0.000";
}

function smoothHistogramBins(bins: number[]): number[] {
  if (bins.length <= 2) return bins;
  const kernel = [1, 4, 6, 4, 1];
  let current = [...bins];
  for (let pass = 0; pass < 2; pass += 1) {
    current = current.map((_value, index) => {
      let total = 0;
      let weight = 0;
      kernel.forEach((factor, offset) => {
        const sourceIndex = Math.max(
          0,
          Math.min(current.length - 1, index + offset - 2),
        );
        total += current[sourceIndex] * factor;
        weight += factor;
      });
      return total / Math.max(weight, 1);
    });
  }
  return current;
}

function gaussianWeight(distance: number, sigma: number): number {
  return Math.exp(-(distance * distance) / (2 * sigma * sigma));
}

function histogramAreaPath(values: number[], peak: number): string {
  if (!values.length || peak <= 0) return "M 0 100 L 100 100 Z";
  const baseline = 96;
  const crestHeight = 85;
  const points = values.map((value, index) => {
    const x = (index / Math.max(values.length - 1, 1)) * 100;
    const normalized = Math.max(0, Math.min(1, value / peak));
    const y = baseline - Math.pow(normalized, 1.46) * crestHeight;
    return { x, y };
  });
  const commands = [
    `M ${points[0]?.x ?? 0} ${baseline}`,
    `L ${points[0]?.x ?? 0} ${points[0]?.y ?? baseline}`,
  ];
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    const midX = (previous.x + current.x) / 2;
    commands.push(`Q ${midX} ${previous.y} ${current.x} ${current.y}`);
  }
  commands.push(`L 100 ${baseline} Z`);
  return commands.join(" ");
}

function EqualizationHistogram({
  id,
  label,
  indexName,
  values,
  domainMinimum,
  domainMaximum,
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
  equalized,
  fillMode,
  onEqualizationChange,
  onFillModeChange,
  onToggleVisibility,
  onClose,
}: EqualizationHistogramProps) {
  const coverage = totalCount
    ? Math.round((selectedCount / totalCount) * 100)
    : 0;
  const peak = Math.max(...bins, 1);
  const smoothedBins = smoothHistogramBins(bins);
  const areaPath = histogramAreaPath(smoothedBins, peak);
  const histogramStops = useMemo(() => {
    if (!equalized || bins.length === 0) {
      return ramp.map((color, index) => ({
        color,
        offset:
          (INDEX_COLOR_RAMPS[indexName].stops?.[index] ??
            index / Math.max(ramp.length - 1, 1)) * 100,
      }));
    }

    const equalization = buildHistogramEqualization(values, minimum, maximum);
    if (!equalization) {
      return ramp.map((color, index) => ({
        color,
        offset:
          (INDEX_COLOR_RAMPS[indexName].stops?.[index] ??
            index / Math.max(ramp.length - 1, 1)) * 100,
      }));
    }

    return bins.map((_bin, index) => {
      const ratio = index / Math.max(bins.length - 1, 1);
      const value = domainMinimum + (domainMaximum - domainMinimum) * ratio;
      const linearPosition = Math.max(
        0,
        Math.min(
          1,
          (value - minimum) / Math.max(maximum - minimum, Number.EPSILON),
        ),
      );
      const palettePosition =
        equalizedPosition(value, equalization) ?? linearPosition;
      return {
        color: indexColorFromPosition(indexName, palettePosition),
        offset: ratio * 100,
      };
    });
  }, [
    bins,
    domainMaximum,
    domainMinimum,
    equalized,
    indexName,
    maximum,
    minimum,
    ramp,
    values,
  ]);

  const histogramGradient = useMemo(() => {
    const segments = histogramStops.map(
      ({ color, offset }) => `${color} ${offset.toFixed(3)}%`,
    );
    return `linear-gradient(to right, ${segments.join(", ")})`;
  }, [histogramStops]);

  return (
    <div className="equalization-card">
      <div className="equalization-toolbar">
        <span className="equalization-badge">Ecualizacion</span>
        <span>
          <b>{selectedCount.toLocaleString()}</b> /{" "}
          {totalCount.toLocaleString()} pixeles
        </span>
        <div className="equalization-toggle-group" role="group" aria-label={`Modo de color ${label}`}>
          <button
            className={`equalization-toggle ${equalized ? "is-active" : ""}`}
            type="button"
            onClick={() => onEqualizationChange(!equalized)}
            aria-pressed={equalized}
          >
            {equalized ? "Eq ON" : "Eq OFF"}
          </button>
          <button
            className={`equalization-toggle ${fillMode === "transparent" ? "is-active" : ""}`}
            type="button"
            onClick={() => onFillModeChange("transparent")}
            aria-pressed={fillMode === "transparent"}
          >
            Transparente
          </button>
          <button
            className={`equalization-toggle ${fillMode === "solid" ? "is-active" : ""}`}
            type="button"
            onClick={() => onFillModeChange("solid")}
            aria-pressed={fillMode === "solid"}
          >
            Solido
          </button>
        </div>
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
        <div className="equalization-curve-shell" aria-hidden="true">
          <svg
            className="equalization-curve"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
          >
            <defs>
              <linearGradient id={`${id}-histogram-fill`} x1="0%" y1="0%" x2="100%" y2="0%">
                {histogramStops.map(({ color, offset }, index) => (
                  <stop
                    key={`${id}-stop-${color}-${index}`}
                    offset={`${offset}%`}
                    stopColor={color}
                  />
                ))}
              </linearGradient>
            </defs>
            <path
              d={areaPath}
              className="equalization-curve-fill"
              fill={`url(#${id}-histogram-fill)`}
              fillOpacity="1"
            />
            <path
              d={areaPath}
              className="equalization-curve-outline"
            />
          </svg>
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
          style={{ background: histogramGradient }}
          aria-hidden="true"
        />
      </div>
      <div className="equalization-readout">
        <span>
          <small>Rango activo</small>
            <strong>
            {minimum.toFixed(3)} - {maximum.toFixed(3)}
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
  onNdviEqualizationChange,
  onNdviFillModeChange,
  indices,
  onIndexRangeChange,
  onIndexEqualizationChange,
  onIndexFillModeChange,
  ndviVisible,
  onToggleNdvi,
  onToggleIndex,
  onHideNdvi,
  onHideIndex,
  canSaveRoiAnalysis,
  roiAnalysisSaving,
  onSaveRoiAnalysis,
  onOpenRoiComparison,
  prescriptionMode,
  prescriptionLoading,
  onOpenPrescription,
  onExitPrescription,
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
    const count = 96;
    const range = Math.max(max - min, Number.EPSILON);
    const bins = Array.from({ length: count }, () => 0);
    const sigma = Math.max(0.9, count / 34);
    const radius = Math.max(2, Math.ceil(sigma * 2.5));
    const gaussianScale = Array.from({ length: radius * 2 + 1 }, (_, offset) =>
      gaussianWeight(offset - radius, sigma),
    );
    values.forEach((value) => {
      const center = ((value - min) / range) * (count - 1);
      const base = Math.round(center);
      for (let offset = -radius; offset <= radius; offset += 1) {
        const index = base + offset;
        if (index < 0 || index >= count) continue;
        bins[index] += gaussianScale[offset + radius];
      }
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
  const activeNdviResponse = ndvi.roiResponse ?? ndvi.response;
  const ndviHistogramMinimum = activeNdviResponse?.range_min ?? activeNdviStats.min;
  const ndviHistogramMaximum = activeNdviResponse?.range_max ?? activeNdviStats.max;
  const roiAnalysisReady = canSaveRoiAnalysis && Boolean(ndvi.roiResponse);
  const hasSelectedSpectralPanel =
    selectedIndex === "NDVI"
      ? Boolean(ndvi.response)
      : selectedIndex != null
        ? indices.some((analysis) => analysis.name === selectedIndex)
        : false;
  const hasVisiblePanel =
    hasSelectedSpectralPanel || Boolean(data && detectionPanelVisible);

  if (!hasVisiblePanel) return null;

  return (
    <aside className="controls visible">
      {selectedIndex === "NDVI" && ndvi.response && (
        <section className="panel-section ndvi-section">
        <div className="panel-heading">
          <strong>Analisis NDVI</strong>
          <span className="ndvi-range-readout">
            {formatIndexRangeValue(ndviHistogramMinimum)} a {formatIndexRangeValue(ndviHistogramMaximum)}
          </span>
        </div>
        <EqualizationHistogram
          id="ndvi"
          label="NDVI"
              indexName="NDVI"
              values={activeNdviStats.values}
              domainMinimum={activeNdviStats.min}
              domainMaximum={activeNdviStats.max}
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
          equalized={ndvi.equalized}
          fillMode={ndvi.fillMode}
          onEqualizationChange={onNdviEqualizationChange}
          onFillModeChange={onNdviFillModeChange}
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
          <span>{formatIndexRangeValue(ndviHistogramMinimum)}</span>
          <span>NDVI</span>
          <span>{formatIndexRangeValue(ndviHistogramMaximum)}</span>
        </div>
        <div className="ndvi-range" aria-label="Rango de contraste NDVI">
          <input
            className="range range-min"
            type="range"
            min={activeNdviStats.min}
            max={activeNdviStats.max}
            step="0.001"
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
            step="0.001"
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
        {ndvi.roiResponse && (
          <button
            type="button"
            className={`prescription-panel-action ${prescriptionMode !== "idle" ? "is-active" : ""}`}
            onClick={
              prescriptionMode === "idle" ? onOpenPrescription : onExitPrescription
            }
            disabled={prescriptionLoading}
          >
            {prescriptionMode === "idle" ? (
              <IconGridDots aria-hidden="true" />
            ) : (
              <IconX aria-hidden="true" />
            )}
            {prescriptionLoading
              ? "Procesando zonificación..."
              : prescriptionMode === "prescription"
                ? "Salir de la prescripción"
                : prescriptionMode === "zoning"
                  ? "Salir de la zonificación"
                  : "Generar zonificación NDVI para este ROI"}
          </button>
        )}
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
        const histogramMinimum = analysis.response.range_min ?? analysis.stats.min;
        const histogramMaximum = analysis.response.range_max ?? analysis.stats.max;
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
                {formatIndexRangeValue(histogramMinimum)} a {formatIndexRangeValue(histogramMaximum)}
              </span>
            </div>
            <EqualizationHistogram
              id={`index-${analysis.name.toLowerCase()}`}
              label={analysis.name}
              indexName={analysis.name}
              values={analysis.stats.values}
              domainMinimum={analysis.stats.min}
              domainMaximum={analysis.stats.max}
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
              equalized={analysis.equalized}
              fillMode={analysis.fillMode}
              onEqualizationChange={(enabled) =>
                onIndexEqualizationChange(analysis.name, enabled)
              }
              onFillModeChange={(mode) =>
                onIndexFillModeChange(analysis.name, mode)
              }
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
              <span>{formatIndexRangeValue(histogramMinimum)}</span>
              <span>{analysis.name}</span>
              <span>{formatIndexRangeValue(histogramMaximum)}</span>
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
                step="0.001"
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
                step="0.001"
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
            <button
              type="button"
              className={`prescription-panel-action ${prescriptionMode !== "idle" ? "is-active" : ""}`}
              onClick={
                prescriptionMode === "idle" ? onOpenPrescription : onExitPrescription
              }
              disabled={prescriptionLoading}
            >
              {prescriptionMode === "idle" ? (
                <IconGridDots aria-hidden="true" />
              ) : (
                <IconX aria-hidden="true" />
              )}
              {prescriptionLoading
                ? "Procesando zonificacion..."
                : prescriptionMode === "prescription"
                  ? "Salir de la prescripcion"
                  : prescriptionMode === "zoning"
                    ? "Salir de la zonificacion"
                    : `Generar zonificacion ${analysis.name} para este ROI`}
            </button>
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
