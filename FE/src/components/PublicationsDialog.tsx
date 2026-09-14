import {
  IconCloudUpload,
  IconLoader2,
  IconRefresh,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import type { PublishedAnalysisRecord } from "../services/api";

interface PublicationsDialogProps {
  open: boolean;
  loading: boolean;
  deletingKey: string | null;
  error: string | null;
  items: PublishedAnalysisRecord[];
  onClose: () => void;
  onRefresh: () => void;
  onDelete: (record: PublishedAnalysisRecord) => void;
}

function publicationKind(record: PublishedAnalysisRecord) {
  if (record.has_prescription) return "Prescripcion";
  if (record.has_zoning) return "Zonificacion";
  return "Indices ROI";
}

export function PublicationsDialog({
  open,
  loading,
  deletingKey,
  error,
  items,
  onClose,
  onRefresh,
  onDelete,
}: PublicationsDialogProps) {
  if (!open) return null;

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
        aria-labelledby="publications-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="import-dialog-heading">
          <div className="modal-title-group">
            <span className="modal-title-icon">
              <IconCloudUpload aria-hidden="true" />
            </span>
            <div>
              <span className="import-eyebrow">NEON DASHBOARD</span>
              <h2 id="publications-title">Resultados publicados</h2>
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

        <div className="roi-dashboard-toolbar">
          <button
            type="button"
            className="roi-dashboard-action is-secondary"
            onClick={onRefresh}
            disabled={loading}
          >
            {loading ? (
              <IconLoader2 className="spin" aria-hidden="true" />
            ) : (
              <IconRefresh aria-hidden="true" />
            )}
            {loading ? "Consultando..." : "Actualizar"}
          </button>
        </div>

        {error && (
          <p className="roi-comparison-status is-error" role="alert">
            {error}
          </p>
        )}

        {items.length === 0 && !loading ? (
          <div className="roi-dashboard-empty">
            <strong>No hay publicaciones para este ciclo.</strong>
            <span>Publica un resultado para verlo aqui antes de borrarlo.</span>
          </div>
        ) : (
          <div className="roi-comparison-table-wrap">
            <table className="roi-table roi-comparison-table">
              <thead>
                <tr>
                  <th>Publicado</th>
                  <th>Tipo</th>
                  <th>Contenido</th>
                  <th>Origen</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.source_publication_key}>
                    <td>
                      <strong>
                        {item.published_at
                          ? new Date(item.published_at).toLocaleString("es-MX")
                          : "Sin fecha"}
                      </strong>
                      <small>{item.project_name ?? item.cycle_name ?? "Geofield"}</small>
                    </td>
                    <td>{publicationKind(item)}</td>
                    <td>
                      <small>
                        {item.index_count} indices
                        {item.has_zoning ? " · zonificacion" : ""}
                        {item.has_prescription ? " · prescripcion" : ""}
                        {item.artifact_count ? ` · ${item.artifact_count} capas` : ""}
                      </small>
                    </td>
                    <td>
                      <small title={item.source_publication_key}>
                        ROI {item.source_roi_id?.slice(0, 8) ?? "N/D"} · Orto{" "}
                        {item.source_orthomosaic_id?.slice(0, 8) ?? "N/D"}
                      </small>
                    </td>
                    <td>{item.status}</td>
                    <td className="roi-comparison-actions">
                      <button
                        type="button"
                        className="roi-analysis-delete"
                        onClick={() => onDelete(item)}
                        disabled={deletingKey === item.source_publication_key}
                      >
                        {deletingKey === item.source_publication_key ? (
                          <IconLoader2 className="spin" aria-hidden="true" />
                        ) : (
                          <IconTrash aria-hidden="true" />
                        )}
                        {deletingKey === item.source_publication_key
                          ? "Eliminando..."
                          : "Eliminar"}
                      </button>
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
