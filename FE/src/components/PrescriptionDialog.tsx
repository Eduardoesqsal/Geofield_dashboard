import { useEffect, useState } from "react";
import {
  IconDownload,
  IconGridDots,
  IconLoader2,
  IconMap2,
  IconPolygon,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import type {
  NdviZoningResponse,
  PrescriptionMapResponse,
} from "../services/api";
import { fetchPrescriptionJson } from "../services/api";
import {
  INDEX_COLOR_RAMPS,
  indexColor,
  indexGradient,
  prescriptionHistogramGradient,
} from "../utils/ndvi";

type VegetationIndexName = "NDVI" | "NDWI" | "NDRE";
type ZoningResponse = NdviZoningResponse | PrescriptionMapResponse;

const zoneColors = (
  indexName: VegetationIndexName,
  zoneCount: number,
  response?: NdviZoningResponse | PrescriptionMapResponse | null,
) => {
  if (response) return response.legend.map((zone) => zone.color);
  const ramp = INDEX_COLOR_RAMPS[indexName].ramp;
  const positions = Array.from({ length: zoneCount }, (_, index) =>
    Math.floor((index * (ramp.length - 1)) / Math.max(zoneCount - 1, 1) + 0.5),
  );
  return positions.map((position) => ramp[position]);
};

const continuousGradient = (gradientStops: string) =>
  `linear-gradient(90deg, ${gradientStops})`;

interface PrescriptionDialogProps {
  open: boolean;
  indexName: VegetationIndexName;
  displayRange?: { minimum: number; maximum: number } | null;
  busy: boolean;
  error: string | null;
  zoning: NdviZoningResponse | null;
  prescription: PrescriptionMapResponse | null;
  prescriptionAreaReady: boolean;
  onDrawArea: () => void;
  onGenerateZoning: (
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
    classificationMethod: "quantiles" | "equal_intervals" | "manual",
    cellValueMode: "mean" | "min" | "max",
    detailLevel: number,
    manualBreaks?: number[],
  ) => Promise<NdviZoningResponse>;
  onPreviewZoning: (
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
    classificationMethod: "quantiles" | "equal_intervals" | "manual",
    cellValueMode: "mean" | "min" | "max",
    detailLevel: number,
    manualBreaks?: number[],
  ) => Promise<void>;
  onClearPreview: () => void;
  onGeneratePrescription: (
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
    classificationMethod: "quantiles" | "equal_intervals" | "manual",
    cellValueMode: "mean" | "min" | "max",
    detailLevel: number,
    manualBreaks?: number[],
    doses?: number[],
  ) => Promise<PrescriptionMapResponse>;
  onClear: () => void;
  onClose: () => void;
}

const resolvePrescriptionDownloadPath = (prescription: PrescriptionMapResponse) =>
  prescription.json_url ?? prescription.geojson_url;

async function downloadPrescriptionJson(prescription: PrescriptionMapResponse) {
  const downloadPath = resolvePrescriptionDownloadPath(prescription);
  if (!downloadPath) {
    throw new Error(
      "La prescripcion no incluye una ruta de descarga. Generala nuevamente.",
    );
  }
  const blob = await fetchPrescriptionJson(downloadPath);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `prescripcion_${prescription.prescription_id.slice(0, 8)}.json`;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

const valueToPercent = (value: number, minimum: number, maximum: number) =>
  Math.max(
    0,
    Math.min(
      100,
      ((value - minimum) / Math.max(maximum - minimum, Number.EPSILON)) * 100,
    ),
  );

const rgbChannels = (hex: string): [number, number, number] => [
  Number.parseInt(hex.slice(1, 3), 16),
  Number.parseInt(hex.slice(3, 5), 16),
  Number.parseInt(hex.slice(5, 7), 16),
];

const blendHex = (startHex: string, endHex: string, factor: number) => {
  const start = rgbChannels(startHex);
  const end = rgbChannels(endHex);
  return `rgb(${start
    .map((channel, index) =>
      Math.round(channel + (end[index] - channel) * factor),
    )
    .join(", ")})`;
};

const histogramThresholdStops = (
  minimum: number,
  maximum: number,
  breaks: number[],
  colors: readonly string[],
) => {
  if (breaks.length < 2 || !colors.length) {
    return "";
  }
  const segments: string[] = [];
  for (let index = 0; index < colors.length; index += 1) {
    const start = breaks[index] ?? minimum;
    const end = breaks[index + 1] ?? maximum;
    const startColor = colors[index] ?? colors[colors.length - 1];
    const endColor = colors[Math.min(index + 1, colors.length - 1)] ?? startColor;
    segments.push(
      `${startColor} ${valueToPercent(start, minimum, maximum)}%, ${endColor} ${valueToPercent(end, minimum, maximum)}%`,
    );
  }
  return segments.join(", ");
};

const buildHistogramGradientStops = (
  minimum: number,
  maximum: number,
  breaks: number[],
  colors: readonly string[],
) => {
  if (breaks.length < 2 || !colors.length) {
    return [];
  }

  return colors.flatMap((color, index) => {
    const start = breaks[index] ?? minimum;
    const end = breaks[index + 1] ?? maximum;
    const startOffset = valueToPercent(start, minimum, maximum);
    const endOffset = valueToPercent(end, minimum, maximum);
    return [
      { color, offset: startOffset },
      { color, offset: endOffset },
    ];
  });
};

function histogramBars(
  bins: number[],
  minimum: number,
  maximum: number,
  indexName: VegetationIndexName,
) {
  const peak = Math.max(...bins, 1);
  return bins.map((value, index) => {
    const start =
      minimum + ((maximum - minimum) * index) / Math.max(bins.length, 1);
    const end =
      minimum +
      ((maximum - minimum) * (index + 1)) / Math.max(bins.length, 1);
    const center = (start + end) / 2;
    return {
      key: `${index}-${start.toFixed(4)}`,
      height: `${(value / peak) * 100}%`,
      color: indexColor(indexName, center, minimum, maximum),
      active: value > 0,
    };
  });
}

function smoothHistogramBins(bins: number[]): number[] {
  if (bins.length <= 2) return bins;
  const kernel = [1, 2, 1];
  const smoothed = bins.map((_value, index) => {
    let total = 0;
    let weight = 0;
    kernel.forEach((factor, offset) => {
      const sourceIndex = Math.max(
        0,
        Math.min(bins.length - 1, index + offset - 1),
      );
      total += bins[sourceIndex] * factor;
      weight += factor;
    });
    return total / Math.max(weight, 1);
  });
  return smoothed.map((value, index) => Math.max(value, bins[index] * 0.92));
}

function histogramAreaPath(values: number[], peak: number): string {
  if (!values.length || peak <= 0) {
    return "M 0 100 L 100 100 Z";
  }
  const baseline = 100;
  const usableHeight = 86;
  const step = values.length > 1 ? 100 / (values.length - 1) : 100;
  const topPath = values
    .map((value, index) => {
      const x = index * step;
      const normalized = Math.max(0, Math.min(1, value / peak));
      const y = baseline - Math.pow(normalized, 0.9) * usableHeight;
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");

  return `${topPath} L 100 ${baseline} L 0 ${baseline} Z`;
}

const quantileLabel = (minimumPercentile: number, maximumPercentile: number) =>
  `P${minimumPercentile.toFixed(0)} - P${maximumPercentile.toFixed(0)}`;

const formatDoseValue = (value: number | null | undefined) =>
  value == null ? "" : value.toFixed(3).replace(/\.?0+$/, "");

export function PrescriptionDialog({
  open,
  indexName,
  displayRange = null,
  busy,
  error,
  zoning,
  prescription,
  prescriptionAreaReady,
  onDrawArea,
  onGenerateZoning,
  onPreviewZoning,
  onClearPreview,
  onGeneratePrescription,
  onClear,
  onClose,
}: PrescriptionDialogProps) {
  const [zoneCount, setZoneCount] = useState(5);
  const [cellSizeM, setCellSizeM] = useState(3);
  const [gridAngleDeg, setGridAngleDeg] = useState(0);
  const [classificationMethod, setClassificationMethod] = useState<
    "quantiles" | "equal_intervals" | "manual"
  >("quantiles");
  const [cellValueMode, setCellValueMode] = useState<"mean" | "min" | "max">(
    "mean",
  );
  const [detailLevel, setDetailLevel] = useState(1);
  const [manualBreaksText, setManualBreaksText] = useState("");
  const [doseValues, setDoseValues] = useState<string[]>([]);
  const [downloadingJson, setDownloadingJson] = useState(false);
  const [downloadJsonError, setDownloadJsonError] = useState<string | null>(null);

  useEffect(() => {
    const source = zoning ?? prescription;
    if (!source) {
      setGridAngleDeg(0);
      setClassificationMethod("quantiles");
      setCellValueMode("mean");
      setDetailLevel(1);
      setManualBreaksText("");
      setDoseValues(Array.from({ length: zoneCount }, () => ""));
      return;
    }
    setZoneCount(source.zone_count ?? 5);
    setGridAngleDeg(source.grid_angle_deg ?? 0);
    setClassificationMethod(source.classification_method ?? "quantiles");
    setCellValueMode(source.cell_value_mode ?? "mean");
    setDetailLevel(source.detail_level ?? 1);
    setDoseValues(
      prescription
        ? source.legend.map((zone) => formatDoseValue(zone.dosage))
        : Array.from({ length: source.zone_count ?? 5 }, () => ""),
    );
  }, [zoning, prescription]);

  useEffect(() => {
    setDoseValues((current) =>
      Array.from({ length: zoneCount }, (_, index) => current[index] ?? ""),
    );
  }, [zoneCount]);

  useEffect(() => {
    if (open) return;
    onClearPreview();
  }, [onClearPreview, open]);

  useEffect(() => {
    if (!open || !prescriptionAreaReady) return;
    if (cellSizeM < 1 || cellSizeM > 50) return;
    const timeout = window.setTimeout(() => {
      const manualBreaks = parseManualBreaks(manualBreaksText);
      if (zoning) {
        void onGenerateZoning(
          zoneCount,
          cellSizeM,
          gridAngleDeg,
          classificationMethod,
          cellValueMode,
          detailLevel,
          manualBreaks,
        );
        return;
      }
      void onPreviewZoning(
        zoneCount,
        cellSizeM,
        gridAngleDeg,
        classificationMethod,
        cellValueMode,
        detailLevel,
        manualBreaks,
      );
    }, 220);
    return () => window.clearTimeout(timeout);
  }, [
    cellSizeM,
    gridAngleDeg,
    classificationMethod,
    cellValueMode,
    detailLevel,
    manualBreaksText,
    onGeneratePrescription,
    onGenerateZoning,
    onPreviewZoning,
    open,
    prescription,
    prescriptionAreaReady,
    zoneCount,
    zoning,
  ]);

  if (!open) return null;

  const activeResponse: ZoningResponse | null = prescription ?? zoning;
  const stage = prescription ? "prescription" : zoning ? "zoning" : "idle";
  const activeIndexName = activeResponse?.index_name ?? indexName;
  const colors = zoneColors(activeIndexName, zoneCount, activeResponse);
  const displayTitle =
    stage === "prescription"
      ? `Mapa de prescripcion ${activeIndexName}`
      : `Zonificacion ${activeIndexName}`;
  const displayCopy =
    stage === "idle"
      ? `Clasifica el ${activeIndexName} del ROI activo por celdas y luego regulariza espacialmente las zonas. Esto no diagnostica estres agronomico; solo separa el lote en clases relativas.`
      : stage === "zoning"
        ? "La zonificacion ya esta calculada. Los umbrales estadisticos se mantienen y el detalle solo regulariza la distribucion espacial final."
        : "Mapa generado desde la clasificacion final por zonas, conservando los valores originales del indice por celda.";

  const parseManualBreaks = (value: string): number[] | undefined => {
    const tokens = value
      .split(/[,\s;]+/)
      .map((token) => token.trim())
      .filter(Boolean);
    if (!tokens.length) return undefined;
    return tokens.map((token) => Number(token));
  };

  const detailSliderValue = 1 - detailLevel;
  const parsedDoses = doseValues.map((value) => Number(value));
  const dosesAreValid =
    parsedDoses.length === zoneCount &&
    doseValues.every((value) => value.trim() !== "") &&
    parsedDoses.every((value) => Number.isFinite(value));
  const histogram = activeResponse?.histogram;
  const activeThresholds = activeResponse?.thresholds ?? [];
  const histogramMinimum =
    displayRange?.minimum ?? histogram?.minimum ?? activeThresholds[0] ?? 0;
  const histogramMaximum =
    displayRange?.maximum ??
    histogram?.maximum ??
    activeThresholds[activeThresholds.length - 1] ??
    1;
  const histogramBins = histogram?.bins ?? [];
  const histogramBreaks = histogram?.breaks ?? activeThresholds;
  const renderedHistogramBars = histogramBars(
    histogramBins,
    histogramMinimum,
    histogramMaximum,
    activeIndexName,
  );
  const smoothedHistogramBins = smoothHistogramBins(histogramBins);
  const smoothedHistogramPeak = Math.max(...smoothedHistogramBins, 1);
  const histogramSurfacePath = histogramAreaPath(
    smoothedHistogramBins,
    smoothedHistogramPeak,
  );
  const histogramSurfaceId = `prescription-histogram-${activeIndexName}-${stage}`;
  const histogramSurfaceStops = buildHistogramGradientStops(
    histogramMinimum,
    histogramMaximum,
    histogramBreaks,
    colors,
  );
  const histogramZoneRamp =
    histogramSurfaceStops.length > 0
      ? continuousGradient(
          histogramThresholdStops(
            histogramMinimum,
            histogramMaximum,
            histogramBreaks,
            colors,
          ),
        )
      : continuousGradient(prescriptionHistogramGradient(activeIndexName));
  const rampGradient = continuousGradient(
    prescriptionHistogramGradient(activeIndexName),
  );

  const handleGenerateZoning = async () => {
    await onGenerateZoning(
      zoneCount,
      cellSizeM,
      gridAngleDeg,
      classificationMethod,
      cellValueMode,
      detailLevel,
      parseManualBreaks(manualBreaksText),
    );
  };

  const handleGeneratePrescription = async () => {
    if (!zoning) return;
    await onGeneratePrescription(
      zoneCount,
      cellSizeM,
      gridAngleDeg,
      classificationMethod,
      cellValueMode,
      detailLevel,
      parseManualBreaks(manualBreaksText),
      parsedDoses,
    );
  };

  const handleDownloadJson = async () => {
    if (!prescription) return;
    setDownloadingJson(true);
    setDownloadJsonError(null);
    try {
      await downloadPrescriptionJson(prescription);
    } catch (error) {
      setDownloadJsonError(
        error instanceof Error
          ? error.message
          : "No se pudo descargar la prescripcion.",
      );
    } finally {
      setDownloadingJson(false);
    }
  };

  return (
    <div
      className="import-dialog-backdrop"
      role="presentation"
      onMouseDown={onClose}
    >
      <section
        className="import-dialog prescription-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="prescription-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="import-dialog-heading">
          <div className="modal-title-group">
            <span className="modal-title-icon">
              <IconGridDots aria-hidden="true" />
            </span>
            <div>
              <span className="import-eyebrow">
                {stage === "prescription"
                  ? "MAPA DE PRESCRIPCION"
                  : `ZONIFICACION ${activeIndexName}`}
              </span>
              <h2 id="prescription-title">{displayTitle}</h2>
            </div>
          </div>
          <button
            className="dialog-close"
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
          >
            <IconX aria-hidden="true" />
          </button>
        </div>

        <p className="import-dialog-copy">{displayCopy}</p>

        <div className="prescription-layout">
          <div className="prescription-sidebar">
            {!zoning && !prescription && (
              <button
                type="button"
                className={`prescription-area-button ${prescriptionAreaReady ? "is-ready" : ""}`}
                onClick={onDrawArea}
                disabled={busy}
              >
                <IconPolygon aria-hidden="true" />
                <span>
                  <strong>
                    {prescriptionAreaReady
                      ? "Zona de cultivo delimitada"
                      : "Dibujar zona de cultivo"}
                  </strong>
                  <small>
                    {prescriptionAreaReady
                      ? "Puedes redibujar el poligono antes de generar."
                      : "Traza el limite que se usara para calcular la prescripcion."}
                  </small>
                </span>
              </button>
            )}

            <section className="prescription-panel-card">
              <div className="prescription-panel-head">
                <strong>Configuracion base</strong>
                <span>{activeIndexName}</span>
              </div>
              <div className="prescription-config-grid">
                <label>
                  <span>Numero de zonas</span>
                  <select
                    value={zoneCount}
                    onChange={(event) => {
                      setZoneCount(Number(event.target.value));
                    }}
                    disabled={busy}
                  >
                    {Array.from({ length: 9 }, (_, index) => index + 2).map((count) => (
                      <option key={count} value={count}>
                        {count} zonas
                        {count === 4 ? " · cuartiles" : count === 5 ? " · quintiles" : ""}
                      </option>
                    ))}
                  </select>
                  <small>Cada zona representa una posicion relativa dentro del lote.</small>
                </label>
                <label>
                  <span>Tamano de la grilla</span>
                  <div className="prescription-size-input">
                    <input
                      type="number"
                      min="1"
                      max="50"
                      step="0.5"
                      value={cellSizeM}
                      onChange={(event) => setCellSizeM(Number(event.target.value))}
                      disabled={busy}
                    />
                    <strong>m x m</strong>
                  </div>
                  <small>La grilla define el tamano fisico de cada celda.</small>
                </label>
                <label>
                  <span>Metodo de clasificacion</span>
                  <select
                    value={classificationMethod}
                    onChange={(event) =>
                      setClassificationMethod(
                        event.target.value as "quantiles" | "equal_intervals" | "manual",
                      )
                    }
                    disabled={busy}
                  >
                    <option value="quantiles">Cuantiles</option>
                    <option value="equal_intervals">Intervalos iguales</option>
                    <option value="manual">Intervalos manuales</option>
                  </select>
                  <small>Define los umbrales numericos de las zonas.</small>
                </label>
                <label>
                  <span>Valor por celda</span>
                  <select
                    value={cellValueMode}
                    onChange={(event) =>
                      setCellValueMode(event.target.value as "mean" | "min" | "max")
                    }
                    disabled={busy}
                  >
                    <option value="mean">Media</option>
                    <option value="min">Minimo</option>
                    <option value="max">Maximo</option>
                  </select>
                  <small>Resume cada celda antes de clasificarla.</small>
                </label>
              </div>

              {classificationMethod === "manual" && (
                <label className="prescription-manual-breaks">
                  <span>Cortes manuales</span>
                  <input
                    type="text"
                    value={manualBreaksText}
                    onChange={(event) => setManualBreaksText(event.target.value)}
                    placeholder="0.35, 0.50, 0.65"
                    disabled={busy}
                  />
                  <small>
                    Escribe {Math.max(zoneCount - 1, 1)} cortes ordenados separados por coma.
                  </small>
                </label>
              )}
            </section>

            <section className="prescription-panel-card prescription-tuning-grid">
              <div className="prescription-rotation-card">
                <div className="prescription-rotation-header">
                  <span>Rotacion de la reticula</span>
                  <strong>{gridAngleDeg}°</strong>
                </div>
                <input
                  type="range"
                  min="-90"
                  max="90"
                  step="1"
                  value={gridAngleDeg}
                  onChange={(event) => setGridAngleDeg(Number(event.target.value))}
                  disabled={busy}
                  aria-label="Rotacion de la reticula"
                />
                <div className="prescription-rotation-scale" aria-hidden="true">
                  <span>-90°</span>
                  <span>0°</span>
                  <span>90°</span>
                </div>
                <small>
                  Ajusta la orientacion de las celdas para alinearlas con los surcos o
                  la direccion de trabajo del lote.
                </small>
              </div>

              <div className="prescription-rotation-card">
                <div className="prescription-rotation-header">
                  <span>Detalle de la zona</span>
                  <strong>{Math.round(detailLevel * 100)}%</strong>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={detailSliderValue}
                  onChange={(event) =>
                    setDetailLevel(1 - Number(event.target.value))
                  }
                  disabled={busy}
                  aria-label="Detalle espacial de la zonificacion"
                />
                <div className="prescription-rotation-scale" aria-hidden="true">
                  <span>Detallado</span>
                  <span>Balanceado</span>
                  <span>Simple</span>
                </div>
                <small>
                  A la izquierda conserva el mayor detalle de celdas. A la derecha simplifica y fusiona manchas para producir zonas mas continuas.
                </small>
              </div>
            </section>

            <section
              className="prescription-panel-card prescription-ramp-card"
              aria-label={`Rampa de color ${activeIndexName}`}
            >
              <div className="prescription-panel-head">
                <strong>Lectura del indice</strong>
                <span>{histogramMinimum.toFixed(3)} - {histogramMaximum.toFixed(3)}</span>
              </div>
              <div className="prescription-ramp-preview">
                <span>{activeIndexName} bajo</span>
                <i style={{ background: rampGradient }} />
                <span>{activeIndexName} alto</span>
              </div>
              <p className="prescription-grid-note">
                {`El histograma replica la distribucion de las celdas ${activeIndexName} que usa la prescripcion dentro del ROI activo.`}
              </p>
            </section>

            {zoning && (
              <section className="prescription-panel-card">
                <div className="prescription-panel-head">
                  <strong>Dosis por zona</strong>
                  <span>JSON</span>
                </div>
                <div className="prescription-dose-grid">
                  {Array.from({ length: zoneCount }, (_, index) => {
                    const zone = zoning.legend[index];
                    const color = zone?.color ?? colors[index] ?? "#ffffff";
                    return (
                      <label key={`dose-${index + 1}`} className="prescription-dose-row">
                        <span className="prescription-dose-label">
                          <i style={{ background: color }} />
                          <b>Zona {index + 1}</b>
                        </span>
                        <span className="prescription-dose-input">
                          <strong>L/ha</strong>
                          <input
                            type="number"
                            step="0.001"
                            value={doseValues[index] ?? ""}
                            onChange={(event) =>
                              setDoseValues((current) =>
                                current.map((value, valueIndex) =>
                                  valueIndex === index ? event.target.value : value,
                                ),
                              )
                            }
                            placeholder="0.000"
                            disabled={busy}
                          />
                        </span>
                      </label>
                    );
                  })}
                </div>
                <small className="prescription-grid-note">
                  Escribe la dosis exacta que debe exportarse para cada zona en el JSON.
                </small>
              </section>
            )}
          </div>

          <div className="prescription-main">
            {activeResponse && (
              <div className="prescription-analytics">
                <section className="prescription-histogram-card">
                  <div className="prescription-histogram-head">
                    <strong>Ajustes de zonificacion</strong>
                    <span>
                      {classificationMethod === "quantiles"
                        ? "Cuantiles"
                        : classificationMethod === "equal_intervals"
                          ? "Intervalos iguales"
                          : "Intervalos manuales"}
                    </span>
                  </div>
                  <div className="prescription-histogram-shell" aria-hidden="true">
                    <div className="prescription-histogram-grid">
                      {Array.from({ length: 5 }, (_, index) => (
                        <i key={index} />
                      ))}
                    </div>
                    <div className="prescription-histogram-bars">
                      {renderedHistogramBars.map((bar) => (
                        <i
                          key={bar.key}
                          className={bar.active ? "is-active" : ""}
                          style={{
                            height: bar.height,
                            background: bar.color,
                          }}
                        />
                      ))}
                    </div>
                    <svg
                      className="prescription-histogram-surface"
                      viewBox="0 0 100 100"
                      preserveAspectRatio="none"
                    >
                      <defs>
                        <linearGradient
                          id={histogramSurfaceId}
                          x1="0%"
                          y1="0%"
                          x2="100%"
                          y2="0%"
                        >
                          {histogramSurfaceStops.length > 0 ? (
                            histogramSurfaceStops.map((stop, index) => (
                              <stop
                                key={`${stop.offset}-${stop.color}-${index}`}
                                offset={`${stop.offset}%`}
                                stopColor={stop.color}
                              />
                            ))
                          ) : (
                            INDEX_COLOR_RAMPS[activeIndexName].ramp.map((color, index) => (
                              <stop
                                key={`${color}-${index}`}
                                offset={`${(index / Math.max(INDEX_COLOR_RAMPS[activeIndexName].ramp.length - 1, 1)) * 100}%`}
                                stopColor={color}
                              />
                            ))
                          )}
                        </linearGradient>
                      </defs>
                      <path
                        d={histogramSurfacePath}
                        fill={`url(#${histogramSurfaceId})`}
                        className="prescription-histogram-surface-fill"
                      />
                      <path
                        d={histogramSurfacePath}
                        className="prescription-histogram-surface-outline"
                      />
                    </svg>
                    <div
                      className="prescription-histogram-ramp"
                      style={{ background: histogramZoneRamp }}
                    />
                    {histogramBreaks.map((threshold, index) => (
                      <div
                        key={`${threshold}-${index}`}
                        className={`prescription-histogram-break ${
                          index === 0 || index === histogramBreaks.length - 1
                            ? "is-edge"
                            : "is-threshold"
                        }`}
                        style={{
                          left: `${valueToPercent(
                            threshold,
                            histogramMinimum,
                            histogramMaximum,
                          )}%`,
                        }}
                      >
                        <span>{threshold.toFixed(3)}</span>
                      </div>
                    ))}
                  </div>
                  <div className="prescription-histogram-scale">
                    <span>{histogramMinimum.toFixed(3)}</span>
                    <span>{activeIndexName}</span>
                    <span>{histogramMaximum.toFixed(3)}</span>
                  </div>
                </section>

                <section className="prescription-stats-card">
                  <div className="prescription-stats-summary">
                    <span>
                      <small>Indice medio</small>
                      <strong>{activeResponse.field_mean?.toFixed(3) ?? "N/D"}</strong>
                    </span>
                    <span>
                      <small>Area</small>
                      <strong>{activeResponse.area_hectares.toFixed(2)} ha</strong>
                    </span>
                    <span>
                      <small>Celdas</small>
                      <strong>
                        {activeResponse.valid_cell_count.toLocaleString("es-MX")}
                      </strong>
                    </span>
                  </div>
                  <div className="prescription-zones-table" role="table" aria-label="Tabla de zonas">
                    <div className="prescription-zones-table-head" role="row">
                      <span role="columnheader">Zona</span>
                      <span role="columnheader">Indice medio</span>
                      <span role="columnheader">Desviacion</span>
                      <span role="columnheader">Cobertura</span>
                      <span role="columnheader">Area</span>
                      <span role="columnheader">Dosis</span>
                      <span role="columnheader">Cuantil</span>
                    </div>
                    {activeResponse.legend.map((zone) => (
                      <div
                        key={zone.class_id}
                        className="prescription-zones-table-row"
                        role="row"
                      >
                        <span role="cell" className="prescription-zone-label">
                          <i style={{ background: zone.color }} />
                          <b>{zone.class_id}</b>
                        </span>
                        <span role="cell">{zone.mean.toFixed(3)}</span>
                        <span role="cell">
                          {(zone.deviation_percent ?? 0) >= 0 ? "+" : ""}
                          {(zone.deviation_percent ?? 0).toFixed(2)}%
                        </span>
                        <span role="cell">
                          {(zone.coverage_percent ?? 0).toFixed(2)}%
                        </span>
                        <span role="cell">{zone.area_hectares.toFixed(2)} ha</span>
                        <span role="cell">
                          {formatDoseValue(zone.dosage)}
                        </span>
                        <span role="cell" className="prescription-zone-quantile">
                          <strong>
                            {quantileLabel(zone.percentile_min, zone.percentile_max)}
                          </strong>
                          <small>
                            {zone.ndvi_min.toFixed(3)} - {zone.ndvi_max.toFixed(3)}
                          </small>
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            )}
          </div>
        </div>

        {error && (
          <p className="library-error" role="alert">
            {error}
          </p>
        )}
        {downloadJsonError && (
          <p className="library-error" role="alert">
            {downloadJsonError}
          </p>
        )}

        <div className="prescription-dialog-actions">
          {(zoning || prescription) && (
            <button
              type="button"
              className="prescription-clear"
              onClick={onClear}
              disabled={busy}
            >
              <IconTrash aria-hidden="true" />
              Quitar mapa actual
            </button>
          )}
          {!zoning ? (
            <button
              type="button"
              className="prescription-generate"
              disabled={busy || cellSizeM < 1 || cellSizeM > 50}
              onClick={() => void handleGenerateZoning()}
            >
              {busy ? (
                <IconLoader2 className="spin" aria-hidden="true" />
              ) : (
                <IconMap2 aria-hidden="true" />
              )}
              {busy
                ? "Generando zonificacion..."
                : `Generar zonificacion ${activeIndexName}`}
            </button>
          ) : (
            <button
              type="button"
              className="prescription-generate"
              disabled={busy || !dosesAreValid}
              onClick={() => void handleGeneratePrescription()}
            >
              {busy ? (
                <IconLoader2 className="spin" aria-hidden="true" />
              ) : (
                <IconMap2 aria-hidden="true" />
              )}
              {busy
                ? "Generando prescripcion..."
                : "Generar salida por zonas"}
            </button>
          )}
          {prescription && (
            <button
              type="button"
              className="prescription-generate"
              disabled={downloadingJson}
              onClick={() => void handleDownloadJson()}
            >
              {downloadingJson ? (
                <IconLoader2 className="spin" aria-hidden="true" />
              ) : (
                <IconDownload aria-hidden="true" />
              )}
              {downloadingJson
                ? "Descargando JSON..."
                : "Descargar prescripcion JSON"}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}

export function PrescriptionLegend({
  response,
  onClose,
}: {
  response: ZoningResponse;
  onClose: () => void;
}) {
  const isPrescription = response.stage === "prescription";
  const activeIndexName = response.index_name ?? "NDVI";
  const legendThresholds = response.thresholds ?? [];
  const legendMinimum = legendThresholds[0] ?? response.legend[0]?.ndvi_min ?? 0;
  const legendMaximum =
    legendThresholds[legendThresholds.length - 1] ??
    response.legend[response.legend.length - 1]?.ndvi_max ??
    1;
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const handleDownload = async (prescription: PrescriptionMapResponse) => {
    setDownloading(true);
    setDownloadError(null);
    try {
      await downloadPrescriptionJson(prescription);
    } catch (error) {
      setDownloadError(
        error instanceof Error
          ? error.message
          : "No se pudo descargar la prescripcion.",
      );
    } finally {
      setDownloading(false);
    }
  };

  return (
    <aside
      className="prescription-legend"
      aria-label={
        isPrescription
          ? "Leyenda del mapa de prescripcion"
          : `Leyenda de zonificacion ${activeIndexName}`
      }
    >
      <header>
        <div>
          <span>
            {isPrescription
              ? "MAPA DE PRESCRIPCION"
              : `ZONIFICACION ${activeIndexName}`}
          </span>
          <strong>{response.title}</strong>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={isPrescription ? "Salir de la prescripcion" : "Salir de la zonificacion"}
        >
          <IconX aria-hidden="true" />
          <span>{isPrescription ? "Salir de prescripcion" : "Salir de zonificacion"}</span>
        </button>
      </header>
      <p>
        {response.zone_count} zonas · celdas de {response.cell_size_m} x {response.cell_size_m} m · rotacion {response.grid_angle_deg}° · detalle {Math.round((response.detail_level ?? 1) * 100)}%
      </p>
      <div className="prescription-legend-ramp" aria-hidden="true">
        <span>{isPrescription ? "Zona baja" : `${activeIndexName} bajo`}</span>
        <i
          style={{
            background: continuousGradient(
              isPrescription
                ? indexGradient(activeIndexName, legendMinimum, legendMaximum)
                : indexGradient(activeIndexName, 0, 1),
            ),
          }}
        />
        <span>{isPrescription ? "Zona alta" : `${activeIndexName} alto`}</span>
      </div>
      <div className="prescription-legend-zones">
        {response.legend.map((zone) => (
          <div key={zone.class_id}>
            <i style={{ background: zone.color }} />
            <span title={`Clase ${zone.class_id}`}>
              <strong>{zone.label}</strong>
              <small>Clase {zone.class_id}</small>
            </span>
            <span>
              <strong>
                {activeIndexName} {zone.ndvi_min.toFixed(3)} - {zone.ndvi_max.toFixed(3)}
              </strong>
              <small>
                P{zone.percentile_min.toFixed(0)} - P{zone.percentile_max.toFixed(0)} · Promedio {zone.mean.toFixed(3)}
              </small>
            </span>
            <small>
              {zone.area_hectares.toFixed(2)} ha · {(zone.coverage_percent ?? 0).toFixed(2)}% · {(zone.deviation_percent ?? 0) >= 0 ? "+" : ""}{(zone.deviation_percent ?? 0).toFixed(2)}%
            </small>
          </div>
        ))}
      </div>
      <footer>
        <span>
          {response.valid_cell_count.toLocaleString("es-MX")} celdas · {response.area_hectares.toFixed(2)} ha · media de campo {response.field_mean?.toFixed(3) ?? "N/D"}
        </span>
        {isPrescription && (
          <button
            type="button"
            className="prescription-download-button"
            title="Descargar el mapa de prescripcion como JSON"
            disabled={downloading}
            onClick={() => void handleDownload(response)}
          >
            {downloading ? (
              <IconLoader2 className="spin" aria-hidden="true" />
            ) : (
              <IconDownload aria-hidden="true" />
            )}
            {downloading ? "Descargando..." : "Descargar prescripcion (JSON)"}
          </button>
        )}
        {downloadError && (
          <small className="prescription-download-error" role="alert">
            {downloadError}
          </small>
        )}
      </footer>
    </aside>
  );
}
