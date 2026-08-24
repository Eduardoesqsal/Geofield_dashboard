import { useEffect, useState } from "react";
import {
  IconGridDots,
  IconLoader2,
  IconMap2,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import type {
  NdviZoningResponse,
  PrescriptionMapResponse,
} from "../services/api";
import { INDEX_COLOR_RAMPS } from "../utils/ndvi";

const ZONE_PALETTE = ["#FF7A00", "#FFC400", "#ACF404", "#00B824"] as const;

const zoneColors = (zoneCount: number, response?: NdviZoningResponse | PrescriptionMapResponse | null) => {
  if (response) return response.legend.map((zone) => zone.dose_color ?? zone.color);
  const ramp = INDEX_COLOR_RAMPS.NDVI.ramp;
  if (zoneCount === ZONE_PALETTE.length) return [...ZONE_PALETTE];
  const positions = Array.from({ length: zoneCount }, (_, index) =>
    Math.floor((index * (ramp.length - 1)) / Math.max(zoneCount - 1, 1) + 0.5),
  );
  return positions.map((position) => ramp[position]);
};

const steppedGradient = (colors: readonly string[]) =>
  `linear-gradient(90deg, ${colors
    .map(
      (color, index) =>
        `${color} ${(index / colors.length) * 100}% ${((index + 1) / colors.length) * 100}%`,
    )
    .join(", ")})`;

const formatRange = (minimum: number, maximum: number) =>
  `${minimum.toFixed(3)} - ${maximum.toFixed(3)}`;

type ZoningResponse = NdviZoningResponse | PrescriptionMapResponse;

interface PrescriptionDialogProps {
  open: boolean;
  busy: boolean;
  error: string | null;
  zoning: NdviZoningResponse | null;
  prescription: PrescriptionMapResponse | null;
  onGenerateZoning: (zoneCount: number, cellSizeM: number) => Promise<NdviZoningResponse>;
  onGeneratePrescription: (
    zoneCount: number,
    cellSizeM: number,
    doses: Array<{ class_id: number; dose: number }>,
  ) => Promise<PrescriptionMapResponse>;
  onClear: () => void;
  onClose: () => void;
}

export function PrescriptionDialog({
  open,
  busy,
  error,
  zoning,
  prescription,
  onGenerateZoning,
  onGeneratePrescription,
  onClear,
  onClose,
}: PrescriptionDialogProps) {
  const [zoneCount, setZoneCount] = useState(4);
  const [cellSizeM, setCellSizeM] = useState(3);
  const [doseDrafts, setDoseDrafts] = useState<Record<number, string>>({});

  useEffect(() => {
    const source = zoning ?? prescription;
    if (!source) {
      setDoseDrafts({});
      return;
    }
    setDoseDrafts(
      Object.fromEntries(source.legend.map((zone) => [zone.class_id, ""])),
    );
  }, [zoning, prescription]);

  if (!open) return null;

  const activeResponse: ZoningResponse | null = prescription ?? zoning;
  const stage = prescription ? "prescription" : zoning ? "zoning" : "idle";
  const colors = zoneColors(zoneCount, activeResponse);

  const zoningTitle = stage === "prescription" ? "Mapa de prescripción" : "Zonificación NDVI";
  const zoningCopy =
    stage === "idle"
      ? "Clasifica el NDVI del ROI activo por cuantiles relativos. Esto no diagnostica estrés agronomico; solo separa el lote en clases estadísticas."
      : stage === "zoning"
        ? "La zonificación ya está calculada. Ahora asigna manualmente una dosis a cada clase antes de crear el mapa de prescripción."
        : "Mapa de prescripción generado a partir de las dosis asignadas manualmente.";

  const canGeneratePrescription =
    Boolean(zoning) &&
    zoning.legend.every((zone) => {
      const value = doseDrafts[zone.class_id];
      return value !== "" && Number.isFinite(Number(value)) && Number(value) >= 0;
    });

  const handleGenerateZoning = async () => {
    await onGenerateZoning(zoneCount, cellSizeM);
  };

  const handleGeneratePrescription = async () => {
    if (!zoning) return;
    const doses = zoning.legend.map((zone) => ({
      class_id: zone.class_id,
      dose: Number(doseDrafts[zone.class_id]),
    }));
    await onGeneratePrescription(zoneCount, cellSizeM, doses);
  };

  return (
    <div className="import-dialog-backdrop" role="presentation" onMouseDown={onClose}>
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
              <span className="import-eyebrow">{stage === "prescription" ? "MAPA DE PRESCRIPCION" : "ZONIFICACION NDVI"}</span>
              <h2 id="prescription-title">{zoningTitle}</h2>
            </div>
          </div>
          <button className="dialog-close" type="button" onClick={onClose} aria-label="Cerrar">
            <IconX aria-hidden="true" />
          </button>
        </div>

        <p className="import-dialog-copy">{zoningCopy}</p>

        <div className="prescription-config-grid">
          <label>
            <span>Número de zonas</span>
            <select
              value={zoneCount}
              onChange={(event) => {
                setZoneCount(Number(event.target.value));
                setDoseDrafts({});
              }}
              disabled={busy || Boolean(zoning) || Boolean(prescription)}
            >
              {Array.from({ length: 9 }, (_, index) => index + 2).map((count) => (
                <option key={count} value={count}>
                  {count} zonas{count === 4 ? " · cuartiles" : count === 5 ? " · quintiles" : ""}
                </option>
              ))}
            </select>
            <small>Cada zona representa una posición relativa dentro del lote.</small>
          </label>
          <label>
            <span>Tamaño de la grilla</span>
            <div className="prescription-size-input">
              <input
                type="number"
                min="1"
                max="50"
              step="0.5"
              value={cellSizeM}
              onChange={(event) => setCellSizeM(Number(event.target.value))}
                disabled={busy || Boolean(zoning) || Boolean(prescription)}
              />
              <strong>m × m</strong>
            </div>
            <small>La grilla define el tamaño físico de cada celda.</small>
          </label>
        </div>

        <div className="prescription-ramp-preview" aria-label="Rampa de color NDVI">
          <span>NDVI bajo</span>
          <i style={{ background: steppedGradient(colors) }} />
          <span>NDVI alto</span>
        </div>

        <p className="prescription-grid-note">
          El ajuste visual del histograma no cambia la zonificación por defecto. Las clases se calculan con todos los píxeles NDVI válidos dentro del ROI.
        </p>

        {zoning && (
          <div className="prescription-dose-table" aria-label="Asignación de dosis">
            {zoning.legend.map((zone) => (
              <label key={zone.class_id} className="prescription-dose-row">
                <span>
                  <strong>{zone.label}</strong>
                  <small>
                    NDVI {formatRange(zone.ndvi_min, zone.ndvi_max)} · P{zone.percentile_min.toFixed(0)}-{zone.percentile_max.toFixed(0)}
                  </small>
                </span>
                <div className="prescription-size-input">
                  <input
                    type="number"
                    min="0"
                    step="0.1"
                    value={doseDrafts[zone.class_id] ?? ""}
                    onChange={(event) =>
                      setDoseDrafts((current) => ({
                        ...current,
                        [zone.class_id]: event.target.value,
                      }))
                    }
                    disabled={busy}
                    placeholder="0"
                    inputMode="decimal"
                  />
                  <strong>L/ha</strong>
                </div>
              </label>
            ))}
          </div>
        )}

        {error && <p className="library-error" role="alert">{error}</p>}

        <div className="prescription-dialog-actions">
          {(zoning || prescription) && (
            <button type="button" className="prescription-clear" onClick={onClear} disabled={busy}>
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
              {busy ? <IconLoader2 className="spin" aria-hidden="true" /> : <IconMap2 aria-hidden="true" />}
              {busy ? "Generando zonificación..." : "Generar zonificación NDVI"}
            </button>
          ) : (
            <button
              type="button"
              className="prescription-generate"
              disabled={busy || !canGeneratePrescription}
              onClick={() => void handleGeneratePrescription()}
            >
              {busy ? <IconLoader2 className="spin" aria-hidden="true" /> : <IconMap2 aria-hidden="true" />}
              {busy ? "Generando prescripción..." : "Generar mapa de prescripción"}
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
  return (
    <aside className="prescription-legend" aria-label={isPrescription ? "Leyenda del mapa de prescripcion" : "Leyenda de zonificacion NDVI"}>
      <header>
        <div>
          <span>{isPrescription ? "MAPA DE PRESCRIPCION" : "ZONIFICACION NDVI"}</span>
          <strong>{response.title}</strong>
        </div>
        <button type="button" onClick={onClose} aria-label={isPrescription ? "Salir de la prescripcion" : "Salir de la zonificacion"}>
          <IconX aria-hidden="true" />
          <span>{isPrescription ? "Salir de prescripción" : "Salir de zonificación"}</span>
        </button>
      </header>
      <p>
        {response.zone_count} zonas · celdas de {response.cell_size_m} × {response.cell_size_m} m
      </p>
      <div className="prescription-legend-ramp" aria-hidden="true">
        <span>{isPrescription ? "Dosis baja" : "NDVI bajo"}</span>
        <i style={{ background: steppedGradient(response.legend.map((zone) => zone.dose_color ?? zone.color)) }} />
        <span>{isPrescription ? "Dosis alta" : "NDVI alto"}</span>
      </div>
      <div className="prescription-legend-zones">
        {response.legend.map((zone) => (
          <div key={zone.class_id}>
            <i style={{ background: zone.dose_color ?? zone.color }} />
            <span title={`Clase ${zone.class_id}`}>
              <strong>{zone.label}</strong>
              <small>Clase {zone.class_id}</small>
            </span>
            <span>
              <strong>NDVI {zone.ndvi_min.toFixed(3)} - {zone.ndvi_max.toFixed(3)}</strong>
              <small>P{zone.percentile_min.toFixed(0)} - P{zone.percentile_max.toFixed(0)} · Promedio {zone.mean.toFixed(3)}</small>
            </span>
            <small>
              {zone.dose != null ? `${zone.dose.toFixed(2)} L/ha` : `${zone.area_hectares.toFixed(2)} ha`}
            </small>
          </div>
        ))}
      </div>
      <footer>
        {response.valid_cell_count.toLocaleString("es-MX")} celdas · {response.area_hectares.toFixed(2)} ha
      </footer>
    </aside>
  );
}
