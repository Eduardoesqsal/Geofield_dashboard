import { IconDatabase, IconEye, IconTrash, IconX } from "@tabler/icons-react";
import type { DetectionSetRecord } from "../services/api";

interface Props {
  open: boolean;
  items: DetectionSetRecord[];
  loading: boolean;
  busyId: string | null;
  error: string | null;
  activeOrthomosaicId: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onSelect: (record: DetectionSetRecord) => void;
  onDelete: (record: DetectionSetRecord) => void;
}

export function DetectionLibraryDialog({
  open,
  items,
  loading,
  busyId,
  error,
  activeOrthomosaicId,
  onClose,
  onRefresh,
  onSelect,
  onDelete,
}: Props) {
  if (!open) return null;
  return (
    <div className="import-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="import-dialog roi-library detection-library"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detection-library-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="import-dialog-heading">
          <div className="modal-title-group">
            <span className="modal-title-icon"><IconDatabase aria-hidden="true" /></span>
            <div>
              <span className="import-eyebrow">BIBLIOTECA ESPACIAL</span>
              <h2 id="detection-library-title">Detecciones guardadas</h2>
            </div>
          </div>
          <button className="dialog-close" type="button" onClick={onClose} aria-label="Cerrar">
            <IconX aria-hidden="true" />
          </button>
        </div>
        <div className="modal-intro-row">
          <p className="import-dialog-copy">Conjuntos guardados por ortomosaico en el ciclo activo.</p>
          <span className="modal-record-count">{items.length} conjuntos</span>
        </div>
        <button className="detection-library-refresh" type="button" onClick={onRefresh} disabled={loading}>
          {loading ? "Actualizando..." : "Actualizar lista"}
        </button>
        {error && <p className="detection-error" role="alert">{error}</p>}
        {!loading && !error && items.length === 0 && (
          <div className="modal-empty-state">
            <IconDatabase aria-hidden="true" />
            <strong>No hay detecciones guardadas</strong>
            <span>Importa un archivo desde el ortomosaico que quieras analizar.</span>
          </div>
        )}
        {items.length > 0 && (
          <div className="roi-table-wrap">
            <table className="roi-table">
              <thead>
                <tr><th>Ortomosaico</th><th>Detecciones</th><th>Guardado</th><th>Acciones</th></tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.orthomosaic_id} className={item.orthomosaic_id === activeOrthomosaicId ? "is-selected" : ""}>
                    <td><strong>{item.orthomosaics.name}</strong><small>{item.orthomosaics.capture_date}</small></td>
                    <td>{item.feature_count.toLocaleString()}</td>
                    <td>{new Date(item.updated_at).toLocaleString()}</td>
                    <td>
                      <div className="table-actions">
                        <button type="button" className="select-roi-button" disabled={busyId !== null} onClick={() => onSelect(item)}>
                          <IconEye aria-hidden="true" /> {busyId === item.orthomosaic_id ? "Cargando..." : "Mostrar"}
                        </button>
                        <button type="button" className="delete-orthomosaic button-with-icon" disabled={busyId !== null} onClick={() => onDelete(item)}>
                          <IconTrash aria-hidden="true" /> Eliminar
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
