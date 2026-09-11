import {
  IconCalendarEvent,
  IconDatabase,
  IconGripVertical,
  IconMapPin,
  IconPhoto,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import type {
  AgriculturalCycleRecord,
  OrthomosaicRecord,
  RoiRecord,
} from "../services/api";

interface MapViewRoiLibraryDialogProps {
  open: boolean;
  rois: RoiRecord[];
  selectedRoiIds: string[];
  onClose: () => void;
  onSelectRoi: (geojson: RoiRecord["geojson"], id: string) => void;
  onDeleteRoi: (roi: RoiRecord) => void;
}

export function MapViewRoiLibraryDialog({
  open,
  rois,
  selectedRoiIds,
  onClose,
  onSelectRoi,
  onDeleteRoi,
}: MapViewRoiLibraryDialogProps) {
  if (!open) return null;

  return (
<div
          className="import-dialog-backdrop"
          role="presentation"
          onMouseDown={() => onClose()}
        >
          <section
            className="import-dialog roi-library"
            role="dialog"
            aria-modal="true"
            aria-labelledby="roi-library-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="import-dialog-heading">
              <div className="modal-title-group">
                <span className="modal-title-icon">
                  <IconMapPin aria-hidden="true" />
                </span>
                <div>
                  <span className="import-eyebrow">BIBLIOTECA ESPACIAL</span>
                  <h2 id="roi-library-title">ROI guardados</h2>
                </div>
              </div>
              <button
                className="dialog-close"
                type="button"
                onClick={() => onClose()}
                aria-label="Cerrar"
              >
                <IconX aria-hidden="true" />
              </button>
            </div>
            <div className="modal-intro-row">
              <p className="import-dialog-copy">
                Agrega dos, tres o tantas regiones como necesites. La tijera
                procesarÃ¡ todas juntas.
              </p>
              <span className="modal-record-count">
                {selectedRoiIds.length} de {rois.length} seleccionadas
              </span>
            </div>
            {rois.length > 0 && (
              <div className="roi-table-wrap">
                <table className="roi-table">
                  <thead>
                    <tr>
                      <th>Nombre</th>
                      <th>Fecha de creaciÃ³n</th>
                      <th aria-label="Acciones" />
                    </tr>
                  </thead>
                  <tbody>
                    {rois.map((roi) => {
                      const selected = selectedRoiIds.includes(
                        roi.id,
                      );
                      return (
                        <tr
                          key={roi.id}
                          className={selected ? "is-selected" : ""}
                        >
                          <td>
                            <strong>{roi.name}</strong>
                          </td>
                          <td>
                            {new Date(roi.created_at).toLocaleDateString()}
                          </td>
                          <td>
                            <div className="table-actions">
                              <button
                                className={`select-roi-button ${selected ? "is-selected" : ""}`}
                                type="button"
                                onClick={() =>
                                  onSelectRoi(roi.geojson, roi.id)
                                }
                              >
                                {selected ? "Quitar" : "Agregar"}
                              </button>
                              <button
                                className="delete-orthomosaic button-with-icon"
                                type="button"
                                onClick={() => {
                                  onDeleteRoi(roi);
                                }}
                              >
                                <IconTrash aria-hidden="true" />
                                Eliminar
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {!rois.length && (
              <div className="modal-empty-state">
                <IconMapPin aria-hidden="true" />
                <strong>No hay ROI guardados</strong>
                <span>
                  Dibuja o importa una regiÃ³n para verla en esta biblioteca.
                </span>
              </div>
            )}
          </section>
        </div>
  );
}

interface MapViewOrthomosaicLibraryDialogProps {
  open: boolean;
  activeCycle: AgriculturalCycleRecord | null;
  orthomosaics: OrthomosaicRecord[];
  libraryError: string | null;
  reorderingOrthomosaics: boolean;
  draggedOrthomosaicId: string | null;
  dragOverOrthomosaicId: string | null;
  editingOrthomosaicId: string | null;
  editingCaptureDate: string;
  updatingOrthomosaicId: string | null;
  activeOrthomosaicId: string | null;
  rgbVisible: boolean;
  onClose: () => void;
  onLeaveActiveCycle: () => void;
  onMoveOrthomosaic: (sourceId: string, targetId: string) => Promise<void>;
  onDragOverOrthomosaicIdChange: (id: string | null) => void;
  onDraggedOrthomosaicIdChange: (id: string | null) => void;
  onClearLibraryError: () => void;
  onEditingCaptureDateChange: (value: string) => void;
  onSaveOrthomosaicDate: (record: OrthomosaicRecord) => Promise<void>;
  onCancelOrthomosaicDateEdit: () => void;
  onBeginOrthomosaicDateEdit: (record: OrthomosaicRecord) => void;
  onFitRgb: () => void;
  onActivateStoredOrtho: (record: OrthomosaicRecord) => Promise<void>;
  onDeleteOrthomosaic: (record: OrthomosaicRecord) => void;
}

export function MapViewOrthomosaicLibraryDialog({
  open,
  activeCycle,
  orthomosaics,
  libraryError,
  reorderingOrthomosaics,
  draggedOrthomosaicId,
  dragOverOrthomosaicId,
  editingOrthomosaicId,
  editingCaptureDate,
  updatingOrthomosaicId,
  activeOrthomosaicId,
  rgbVisible,
  onClose,
  onLeaveActiveCycle,
  onMoveOrthomosaic,
  onDragOverOrthomosaicIdChange,
  onDraggedOrthomosaicIdChange,
  onClearLibraryError,
  onEditingCaptureDateChange,
  onSaveOrthomosaicDate,
  onCancelOrthomosaicDateEdit,
  onBeginOrthomosaicDateEdit,
  onFitRgb,
  onActivateStoredOrtho,
  onDeleteOrthomosaic,
}: MapViewOrthomosaicLibraryDialogProps) {
  if (!open) return null;

  return (
<div
          className="import-dialog-backdrop"
          role="presentation"
          onMouseDown={() => onClose()}
        >
          <section
            className="import-dialog orthomosaic-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="orthomosaic-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="import-dialog-heading">
              <div className="modal-title-group">
                <span className="modal-title-icon">
                  <IconDatabase aria-hidden="true" />
                </span>
                <div>
                  <span className="import-eyebrow">BIBLIOTECA DE VUELOS</span>
                  <h2 id="orthomosaic-title">Ortomosaicos guardados</h2>
                </div>
              </div>
              <button
                className="dialog-close"
                type="button"
                onClick={() => onClose()}
                aria-label="Cerrar"
              >
                <IconX aria-hidden="true" />
              </button>
            </div>
            <div className="modal-intro-row">
              <div className="library-cycle-summary">
                <p className="import-dialog-copy">
                  Consulta, activa o administra los ortomosaicos disponibles.
                </p>
                {activeCycle && (
                  <span className="library-cycle-badge">
                    <IconCalendarEvent aria-hidden="true" />
                    {activeCycle.name}
                  </span>
                )}
              </div>
              <span className="modal-record-count">
                {reorderingOrthomosaics
                  ? "Guardando orden..."
                  : `${orthomosaics.length} ${orthomosaics.length === 1 ? "archivo" : "archivos"}`}
              </span>
            </div>
            <div className="library-cycle-actions">
              <button
                type="button"
                className="orthomosaic-date-trigger"
                onClick={onLeaveActiveCycle}
              >
                Salir del ciclo
              </button>
            </div>
            {!!orthomosaics.length && (
              <p className="orthomosaic-reorder-help">
                Arrastra cada vuelo desde el control de la izquierda para cambiar su posiciÃ³n.
              </p>
            )}
            {libraryError && <p className="library-error">{libraryError}</p>}
            {(
              <div className="orthomosaic-table-wrap">
                <table className="orthomosaic-table">
                  <thead>
                    <tr>
                      <th className="orthomosaic-drag-cell" aria-label="Reordenar" />
                      <th>Ortomosaico</th>
                      <th>Fecha</th>
                      <th>Sensor</th>
                      <th>Visible</th>
                      <th aria-label="Acciones" />
                    </tr>
                  </thead>
                  <tbody>
                    {orthomosaics.map((record) => {
                      const active =
                        activeOrthomosaicId === record.id && rgbVisible;
                      return (
                        <tr
                          key={record.id}
                          className={`${draggedOrthomosaicId === record.id ? "is-dragging" : ""} ${dragOverOrthomosaicId === record.id ? "is-drag-over" : ""}`}
                          onDragOver={(event) => {
                            if (!draggedOrthomosaicId || draggedOrthomosaicId === record.id) return;
                            event.preventDefault();
                            event.dataTransfer.dropEffect = "move";
                            onDragOverOrthomosaicIdChange(record.id);
                          }}
                          onDrop={(event) => {
                            event.preventDefault();
                            if (draggedOrthomosaicId) {
                              void onMoveOrthomosaic(draggedOrthomosaicId, record.id);
                            }
                          }}
                        >
                          <td className="orthomosaic-drag-cell">
                            <button
                              type="button"
                              className="orthomosaic-drag-handle"
                              draggable={!reorderingOrthomosaics}
                              disabled={reorderingOrthomosaics}
                              title="Arrastra para reordenar"
                              aria-label={`Reordenar ${record.name}`}
                              onDragStart={(event) => {
                                event.dataTransfer.effectAllowed = "move";
                                event.dataTransfer.setData("text/plain", record.id);
                                onDraggedOrthomosaicIdChange(record.id);
                                onClearLibraryError();
                              }}
                              onDragEnd={() => {
                                onDraggedOrthomosaicIdChange(null);
                                onDragOverOrthomosaicIdChange(null);
                              }}
                            >
                              <IconGripVertical aria-hidden="true" />
                            </button>
                          </td>
                          <td>
                            <strong>{record.name}</strong>
                            <small>{record.original_filename}</small>
                          </td>
                          <td>
                            {editingOrthomosaicId === record.id ? (
                              <div className="orthomosaic-date-editor">
                                <input
                                  type="date"
                                  value={editingCaptureDate}
                                  onChange={(event) =>
                                    onEditingCaptureDateChange(event.target.value)
                                  }
                                  max="2026-08-19"
                                />
                                <div className="orthomosaic-date-actions">
                                  <button
                                    type="button"
                                    className="orthomosaic-date-save"
                                    onClick={() => void onSaveOrthomosaicDate(record)}
                                    disabled={updatingOrthomosaicId === record.id}
                                  >
                                    {updatingOrthomosaicId === record.id
                                      ? "Guardando..."
                                      : "Guardar"}
                                  </button>
                                  <button
                                    type="button"
                                    className="orthomosaic-date-cancel"
                                    onClick={onCancelOrthomosaicDateEdit}
                                    disabled={updatingOrthomosaicId === record.id}
                                  >
                                    Cancelar
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <div className="orthomosaic-date-cell">
                                <span>{record.capture_date}</span>
                                <button
                                  type="button"
                                  className="orthomosaic-date-trigger"
                                  onClick={() => onBeginOrthomosaicDateEdit(record)}
                                >
                                  Editar fecha
                                </button>
                              </div>
                            )}
                          </td>
                          <td>
                            <span className="sensor-table-badge">
                              {record.sensor_type}
                            </span>
                          </td>
                          <td>
                            <button
                              type="button"
                              className={`ortho-toggle ${active ? "is-on" : ""}`}
                              onClick={() => {
                                if (active) onFitRgb();
                                else void onActivateStoredOrtho(record);
                              }}
                              aria-label={
                                active
                                  ? "Desactivar ortomosaico"
                                  : "Activar ortomosaico"
                              }
                            >
                              <span />
                            </button>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="delete-orthomosaic button-with-icon"
                              onClick={() => {
                                onDeleteOrthomosaic(record);
                              }}
                            >
                              <IconTrash aria-hidden="true" />
                              Eliminar
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {!orthomosaics.length && (
                  <div className="modal-empty-state">
                    <IconPhoto aria-hidden="true" />
                    <strong>Este ciclo aun no tiene ortomosaicos</strong>
                    <span>
                      {activeCycle
                        ? `Importa un vuelo para comenzar la biblioteca de ${activeCycle.name}.`
                        : "Importa un vuelo para comenzar tu biblioteca."}
                    </span>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
  );
}
