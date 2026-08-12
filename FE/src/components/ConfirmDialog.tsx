/**
 * Diálogo reutilizable de confirmación para operaciones sensibles.
 * Se usa como capa de seguridad antes de eliminar registros o ejecutar
 * acciones que alteran el estado persistido de la app.
 */
import {
  IconAlertTriangle,
  IconLoader2,
  IconTrash,
  IconX,
} from "@tabler/icons-react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  subject: string;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Confirmación reutilizable para operaciones irreversibles. Mientras `busy`
 * está activo bloquea el cierre y el doble envío de la solicitud.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  subject,
  busy,
  error,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div
      className="import-dialog-backdrop"
      role="presentation"
      onMouseDown={() => {
        if (!busy) onCancel();
      }}
    >
      <section
        className="import-dialog confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-description"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="confirm-dialog-heading">
          <span className="confirm-dialog-icon">
            <IconAlertTriangle aria-hidden="true" />
          </span>
          <button
            className="dialog-close"
            type="button"
            onClick={onCancel}
            disabled={busy}
            aria-label="Cerrar"
          >
            <IconX aria-hidden="true" />
          </button>
        </div>
        <span className="import-eyebrow">CONFIRMAR ELIMINACIÓN</span>
        <h2 id="confirm-dialog-title">{title}</h2>
        <p id="confirm-dialog-description" className="import-dialog-copy">
          {description}
        </p>
        <div className="confirm-dialog-subject">
          <IconTrash aria-hidden="true" />
          <span>{subject}</span>
        </div>
        {error && <p className="library-error">{error}</p>}
        <div className="confirm-dialog-actions">
          <button
            type="button"
            className="confirm-cancel"
            onClick={onCancel}
            disabled={busy}
          >
            Conservar
          </button>
          <button
            type="button"
            className="confirm-delete"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? (
              <IconLoader2 className="spin" aria-hidden="true" />
            ) : (
              <IconTrash aria-hidden="true" />
            )}
            {busy ? "Eliminando…" : "Eliminar definitivamente"}
          </button>
        </div>
      </section>
    </div>
  );
}
