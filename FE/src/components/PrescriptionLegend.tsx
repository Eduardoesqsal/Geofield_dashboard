import { useState } from "react";
import { IconDownload, IconGridDots, IconLoader2, IconX } from "@tabler/icons-react";
import type { NdviZoningResponse, PrescriptionMapResponse } from "../services/api";
import { fetchPrescriptionJson } from "../services/api";
import { indexGradient } from "../utils/ndvi";

type ZoningResponse = NdviZoningResponse | PrescriptionMapResponse;

const continuousGradient = (gradientStops: string) =>
  `linear-gradient(90deg, ${gradientStops})`;

const resolvePrescriptionDownloadPath = (prescription: PrescriptionMapResponse) =>
  prescription.json_url ?? `/prescriptions/${prescription.prescription_id}/download.json`;

const downloadPrescriptionJson = async (prescription: PrescriptionMapResponse) => {
  const downloadPath = resolvePrescriptionDownloadPath(prescription);
  const blob = await fetchPrescriptionJson(downloadPath);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `prescripcion_${prescription.prescription_id.slice(0, 8)}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};

export function PrescriptionLegend({
  response,
  onClose,
  onConfigure,
}: {
  response: ZoningResponse;
  onClose: () => void;
  onConfigure: () => void;
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
        <button
          type="button"
          className="prescription-download-button"
          onClick={onConfigure}
        >
          <IconGridDots aria-hidden="true" />
          Volver a la configuracion
        </button>
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
