/**
 * Modal para seleccionar o crear el ciclo agricola activo.
 * La importacion y la biblioteca de ortomosaicos quedan ligadas al ciclo
 * seleccionado para evitar mezclar vuelos de temporadas distintas.
 */
import { useMemo, useState } from "react";
import {
  IconCalendarEvent,
  IconChevronRight,
  IconPencil,
  IconPlus,
  IconSeedling,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import type {
  AgriculturalCycleRecord,
  CreateAgriculturalCyclePayload,
} from "../services/api";

interface Props {
  open: boolean;
  loading: boolean;
  busy: boolean;
  error: string | null;
  cycles: AgriculturalCycleRecord[];
  activeCycleId: string | null;
  mode: "entry" | "import" | "library";
  renamingCycleId: string | null;
  onClose: () => void;
  onSelect: (cycle: AgriculturalCycleRecord) => void;
  onCreate: (payload: CreateAgriculturalCyclePayload) => void;
  onRename: (cycle: AgriculturalCycleRecord, name: string) => void;
  onDelete: (cycle: AgriculturalCycleRecord) => void;
}

const today = new Date().toISOString().slice(0, 10);

export function AgriculturalCycleDialog({
  open,
  loading,
  busy,
  error,
  cycles,
  activeCycleId,
  mode,
  renamingCycleId,
  onClose,
  onSelect,
  onCreate,
  onRename,
  onDelete,
}: Props) {
  const [name, setName] = useState("");
  const [cropName, setCropName] = useState("");
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");
  const [editingCycleId, setEditingCycleId] = useState<string | null>(null);
  const [editingCycleName, setEditingCycleName] = useState("");

  const actionLabel =
    mode === "import"
      ? "Continuar a importacion"
      : mode === "library"
        ? "Abrir biblioteca"
        : "Entrar al ciclo";
  const subtitle = useMemo(
    () =>
      mode === "import"
        ? "Primero define el ciclo agricola donde quedara almacenado el ortomosaico."
        : mode === "library"
          ? "Selecciona el ciclo activo para consultar solo los ortomosaicos correspondientes."
          : "Antes de trabajar con ortomosaicos, ROI e indices, entra a un ciclo agricola existente o crea uno nuevo.",
    [mode],
  );

  if (!open) return null;

  return (
    <div
      className="import-dialog-backdrop"
      role="presentation"
      onMouseDown={onClose}
    >
      <section
        className="import-dialog cycle-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cycle-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="import-dialog-heading">
          <div className="modal-title-group">
            <span className="modal-title-icon">
              <IconCalendarEvent aria-hidden="true" />
            </span>
            <div>
              <span className="import-eyebrow">CICLO AGRICOLA</span>
              <h2 id="cycle-dialog-title">Selecciona o crea un ciclo</h2>
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
        <p className="import-dialog-copy">{subtitle}</p>
        {error && <p className="library-error">{error}</p>}
        <div className="cycle-dialog-layout">
          <section className="cycle-dialog-panel">
            <div className="cycle-dialog-panel-head">
              <strong>Ciclos disponibles</strong>
            </div>
            {loading ? (
              <div className="modal-empty-state">
                <IconCalendarEvent aria-hidden="true" />
                <strong>Cargando ciclos...</strong>
                <span>Consultando la configuracion guardada en la base de datos.</span>
              </div>
            ) : cycles.length ? (
              <div className="cycle-list">
                {cycles.map((cycle) => {
                  const selected = cycle.id === activeCycleId;
                  const editing = editingCycleId === cycle.id;
                  return (
                    <div
                      key={cycle.id}
                      className={`cycle-card ${selected ? "is-selected" : ""}`}
                    >
                      <button
                        type="button"
                        className="cycle-card-main"
                        onClick={() => onSelect(cycle)}
                      >
                        <span className="cycle-card-top">
                          {editing ? (
                            <input
                              type="text"
                              value={editingCycleName}
                              onChange={(event) =>
                                setEditingCycleName(event.target.value)
                              }
                              onClick={(event) => event.stopPropagation()}
                            />
                          ) : (
                            <strong>{cycle.name}</strong>
                          )}
                          <i>{selected ? "Activo" : actionLabel}</i>
                        </span>
                        <span className="cycle-card-meta">
                          <IconSeedling aria-hidden="true" />
                          {cycle.crop_name || "Cultivo no especificado"}
                        </span>
                        <span className="cycle-card-dates">
                          {cycle.start_date}
                          {" - "}
                          {cycle.end_date || "En curso"}
                        </span>
                        <span className="cycle-card-action">
                          {actionLabel}
                          <IconChevronRight aria-hidden="true" />
                        </span>
                      </button>
                      <div className="cycle-card-tools">
                        {editing ? (
                          <>
                            <button
                              type="button"
                              className="cycle-tool-button is-save"
                              disabled={renamingCycleId === cycle.id}
                              onClick={() => onRename(cycle, editingCycleName)}
                            >
                              {renamingCycleId === cycle.id ? "Guardando..." : "Guardar"}
                            </button>
                            <button
                              type="button"
                              className="cycle-tool-button"
                              disabled={renamingCycleId === cycle.id}
                              onClick={() => {
                                setEditingCycleId(null);
                                setEditingCycleName("");
                              }}
                            >
                              Cancelar
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="cycle-tool-button is-icon"
                              aria-label={`Renombrar ${cycle.name}`}
                              onClick={() => {
                                setEditingCycleId(cycle.id);
                                setEditingCycleName(cycle.name);
                              }}
                            >
                              <IconPencil aria-hidden="true" />
                            </button>
                            <button
                              type="button"
                              className="cycle-tool-button is-icon is-delete"
                              aria-label={`Eliminar ${cycle.name}`}
                              onClick={() => onDelete(cycle)}
                            >
                              <IconTrash aria-hidden="true" />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="modal-empty-state">
                <IconCalendarEvent aria-hidden="true" />
                <strong>No hay ciclos registrados</strong>
                <span>Crea el primer ciclo agricola para comenzar a importar vuelos.</span>
              </div>
            )}
          </section>

          <section className="cycle-dialog-panel cycle-form-panel">
            <div className="cycle-dialog-panel-head">
              <strong>Nuevo ciclo agricola</strong>
            </div>
            <div className="cycle-form-grid">
              <label>
                <span>Nombre del ciclo</span>
                <input
                  type="text"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Ej. Primavera 2026"
                />
              </label>
              <label>
                <span>Cultivo</span>
                <input
                  type="text"
                  value={cropName}
                  onChange={(event) => setCropName(event.target.value)}
                  placeholder="Ej. Tomate Saladette"
                />
              </label>
              <label>
                <span>Fecha inicial</span>
                <input
                  type="date"
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                  max="2026-08-19"
                />
              </label>
              <label>
                <span>Fecha final</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(event) => setEndDate(event.target.value)}
                  max="2026-08-19"
                />
              </label>
              <label className="cycle-form-notes">
                <span>Notas</span>
                <textarea
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="Variedad, lote o cualquier referencia del ciclo."
                  rows={4}
                />
              </label>
            </div>
            <button
              type="button"
              className="cycle-save-button"
              disabled={busy}
              onClick={() =>
                onCreate({
                  name,
                  crop_name: cropName || undefined,
                  start_date: startDate,
                  end_date: endDate || undefined,
                  notes: notes || undefined,
                })
              }
            >
              <IconPlus aria-hidden="true" />
              {busy ? "Guardando ciclo..." : "Guardar ciclo y continuar"}
            </button>
          </section>
        </div>
      </section>
    </div>
  );
}
