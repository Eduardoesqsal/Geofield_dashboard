import { useRef } from "react";
import {
  IconDatabase,
  IconFileImport,
  IconPolygon,
  IconX,
} from "@tabler/icons-react";

interface Props {
  open: boolean;
  onClose: () => void;
  onDraw: () => void;
  onImport: (files: File[]) => void;
  onManage: () => void;
}

/** Punto de entrada para dibujar, importar o administrar regiones de interés. */
export function RoiDialog({
  open,
  onClose,
  onDraw,
  onImport,
  onManage,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  if (!open) return null;
  return (
    <div
      className="import-dialog-backdrop"
      role="presentation"
      onMouseDown={onClose}
    >
      <section
        className="import-dialog roi-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="roi-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="import-dialog-heading">
          <div className="modal-title-group">
            <span className="modal-title-icon">
              <IconPolygon aria-hidden="true" />
            </span>
            <div>
              <span className="import-eyebrow">ANÁLISIS ZONAL</span>
              <h2 id="roi-title">Región de interés</h2>
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
        <p className="import-dialog-copy">
          Delimita una o varias áreas para analizarlas juntas. El NDVI se
          calculará únicamente dentro de las zonas seleccionadas.
        </p>
        <div className="roi-options">
          <button
            type="button"
            onClick={() => {
              onDraw();
              onClose();
            }}
          >
            <span className="roi-option-icon">
              <IconPolygon aria-hidden="true" />
            </span>
            <span>
              <strong>Dibujar sobre el mapa</strong>
              <small>
                Crea un polígono manualmente sobre el área que deseas estudiar.
              </small>
              <i>Iniciar dibujo</i>
            </span>
          </button>
          <button type="button" onClick={() => inputRef.current?.click()}>
            <span className="roi-option-icon">
              <IconFileImport aria-hidden="true" />
            </span>
            <span>
              <strong>Importar geometrías</strong>
              <small>
                Utiliza archivos KML, KMZ, SHP, ZIP o GeoJSON existentes.
              </small>
              <i>Seleccionar archivos</i>
            </span>
          </button>
        </div>
        <button
          className="manage-rois button-with-icon"
          type="button"
          onClick={() => {
            onManage();
            onClose();
          }}
        >
          <IconDatabase aria-hidden="true" />
          Administrar ROI guardados
        </button>
        <input
          ref={inputRef}
          className="hidden-file-input"
          type="file"
          multiple
          accept=".kml,.kmz,.shp,.zip,.geojson,.json,application/zip,application/json"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            if (files.length) {
              onImport(files);
              onClose();
            }
            event.target.value = "";
          }}
        />
      </section>
    </div>
  );
}
