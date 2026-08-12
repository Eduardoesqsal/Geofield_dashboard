/**
 * Diálogo de importación para detecciones arbóreas y archivos auxiliares.
 * Resuelve la experiencia de selección, arrastre y validación previa antes
 * de enviar la información al flujo principal del mapa.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, DragEvent } from "react";
import {
  IconAdjustmentsHorizontal,
  IconBoxMultiple,
  IconChartDonut,
  IconCheck,
  IconCircleDot,
  IconEye,
  IconEyeOff,
  IconFileZip,
  IconLoader2,
  IconMapPin,
  IconMapPinPlus,
  IconRulerMeasure,
  IconTrees,
  IconTrash,
  IconUpload,
  IconX,
} from "@tabler/icons-react";
import type {
  DetectionEditMode,
  TreeDisplayMode,
} from "../hooks/useDashboardMap";
import type { TreeCollection } from "../types/geo";
import {
  numericTreeFields,
  treeSizeColors,
  treeStats,
  type VisibleTreeSize,
} from "../utils/tree";

interface Props {
  open: boolean;
  data: TreeCollection | null;
  visible: boolean;
  displayMode: TreeDisplayMode;
  editMode: DetectionEditMode;
  visibleSizes: Record<VisibleTreeSize, boolean>;
  onImport: (
    files: File[],
    reportProgress: (progress: number, message: string) => void,
  ) => Promise<TreeCollection>;
  onToggleLayer: () => void;
  onDisplayModeChange: (mode: TreeDisplayMode) => void;
  onDiameterFieldChange: (field: string | null) => void;
  onAddDetection: (diameter: number) => void;
  onDeleteDetection: () => void;
  onDeleteArea: () => void;
  onToggleSize: (size: VisibleTreeSize) => void;
  onClose: () => void;
}

const sizeMeta: Record<VisibleTreeSize, { label: string; range: string }> = {
  small: { label: "Chicos", range: "≤ 2.5 m" },
  medium: { label: "Medianos", range: "2.5–3.5 m" },
  large: { label: "Grandes", range: "> 3.5 m" },
};

/** Obtiene el nombre común que relaciona SHP, DBF, SHX y PRJ. */
function shapefileStem(file: File): string {
  return file.name.toLowerCase().replace(/\.[^.]+$/, "");
}

/**
 * Flujo especializado para cargar detecciones y controlar su representación.
 * El histograma funciona también como filtro directo de la capa Leaflet.
 */
export function DetectionDialog({
  open,
  data,
  visible,
  displayMode,
  editMode,
  visibleSizes,
  onImport,
  onToggleLayer,
  onDisplayModeChange,
  onDiameterFieldChange,
  onAddDetection,
  onDeleteDetection,
  onDeleteArea,
  onToggleSize,
  onClose,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fileLabel, setFileLabel] = useState<string | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [selectedDiameterField, setSelectedDiameterField] = useState("");
  const [manualDiameter, setManualDiameter] = useState(2.5);
  const validManualDiameter =
    Number.isFinite(manualDiameter) && manualDiameter > 0;
  const stats = useMemo(() => treeStats(data), [data]);
  const numericFields = useMemo(() => numericTreeFields(data), [data]);
  const classifiedTotal = stats.small + stats.medium + stats.large;
  const smallEnd = classifiedTotal ? (stats.small / classifiedTotal) * 100 : 0;
  const mediumEnd = classifiedTotal
    ? smallEnd + (stats.medium / classifiedTotal) * 100
    : 0;
  const pieStyle = {
    background: classifiedTotal
      ? `conic-gradient(${treeSizeColors.small} 0 ${smallEnd}%, ${treeSizeColors.medium} ${smallEnd}% ${mediumEnd}%, ${treeSizeColors.large} ${mediumEnd}% 100%)`
      : `conic-gradient(${treeSizeColors.unknown} 0 100%)`,
  } as CSSProperties;

  useEffect(() => {
    if (!open) return;
    setDragging(false);
    setLoading(false);
    setProgress(0);
    setProgressMessage("");
    setError(null);
    setPendingFiles([]);
  }, [open]);

  useEffect(() => {
    if (selectedDiameterField && !numericFields.includes(selectedDiameterField))
      setSelectedDiameterField("");
  }, [numericFields, selectedDiameterField]);

  if (!open) return null;

  const importFiles = async (files: File[]) => {
    if (!files.length || loading) return;
    setLoading(true);
    setError(null);
    setProgress(2);
    setProgressMessage("Preparando importación...");
    setSelectedDiameterField("");
    setFileLabel(
      files.length === 1
        ? files[0].name
        : `${files.length} archivos seleccionados`,
    );
    try {
      await onImport(files, (nextProgress, message) => {
        setProgress(nextProgress);
        setProgressMessage(message);
      });
      setPendingFiles([]);
    } catch (importError) {
      setError(
        importError instanceof Error
          ? importError.message
          : "No se pudieron cargar las detecciones.",
      );
    } finally {
      setLoading(false);
    }
  };

  /**
   * Permite seleccionar primero el SHP y después el DBF. El navegador no puede
   * recuperar automáticamente archivos vecinos sin autorización del usuario.
   */
  const stageFiles = (nextFiles: File[]) => {
    if (!nextFiles.length || loading) return;
    const merged = new Map(
      [...pendingFiles, ...nextFiles].map((file) => [
        file.name.toLowerCase(),
        file,
      ]),
    );
    const staged = [...merged.values()];
    const portable = staged.find((file) =>
      /\.(geojson|json|zip)$/i.test(file.name),
    );
    if (portable) {
      void importFiles([portable]);
      return;
    }

    const shp = staged.find((file) => /\.shp$/i.test(file.name));
    const dbf = shp
      ? staged.find(
          (file) =>
            /\.dbf$/i.test(file.name) &&
            shapefileStem(file) === shapefileStem(shp),
        )
      : undefined;
    if (shp && dbf) {
      const related = staged.filter(
        (file) => shapefileStem(file) === shapefileStem(shp),
      );
      void importFiles(related);
      return;
    }

    setPendingFiles(staged);
    setError(null);
    setProgress(0);
    setProgressMessage("");
    setFileLabel(
      shp
        ? `${shp.name} · falta ${shapefileStem(shp)}.dbf`
        : `${staged.length} archivo${staged.length === 1 ? "" : "s"} en espera`,
    );
  };

  const receiveDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    stageFiles(Array.from(event.dataTransfer.files));
  };

  const pendingShp = pendingFiles.find((file) => /\.shp$/i.test(file.name));
  const waitingForDbf = Boolean(pendingShp);

  return (
    <div
      className="import-dialog-backdrop"
      role="presentation"
      onMouseDown={() => !loading && onClose()}
    >
      <section
        className="import-dialog detection-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detection-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="import-dialog-heading">
          <div className="modal-title-group">
            <span className="modal-title-icon">
              <IconTrees aria-hidden="true" />
            </span>
            <div>
              <span className="import-eyebrow">ANÁLISIS DE OBJETOS</span>
              <h2 id="detection-dialog-title">Detecciones</h2>
            </div>
          </div>
          <button
            className="dialog-close"
            type="button"
            onClick={onClose}
            disabled={loading}
            aria-label="Cerrar"
          >
            <IconX aria-hidden="true" />
          </button>
        </div>

        <div className="detection-intro">
          <div>
            <strong>Importa y explora tus detecciones</strong>
            <p>
              Carga puntos GeoJSON o un Shapefile. Si utilizas SHP suelta
              también el DBF, o comprime ambos dentro de un ZIP para conservar
              diámetros.
            </p>
          </div>
          <span className="detection-format-badge">
            <IconFileZip aria-hidden="true" /> SHP · ZIP · GEOJSON
          </span>
        </div>

        <div
          className={`detection-dropzone ${dragging ? "is-dragging" : ""} ${loading ? "is-loading" : ""}`}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node))
              setDragging(false);
          }}
          onDrop={receiveDrop}
        >
          <span className="detection-upload-icon">
            {loading ? (
              <IconLoader2 className="is-spinning" aria-hidden="true" />
            ) : progress === 100 ? (
              <IconCheck aria-hidden="true" />
            ) : (
              <IconUpload aria-hidden="true" />
            )}
          </span>
          <div>
            <strong>
              {loading
                ? progressMessage
                : (fileLabel ?? "Arrastra aquí tus archivos de detecciones")}
            </strong>
            <span>
              {progress === 100 && !loading
                ? `${stats.count.toLocaleString()} detecciones disponibles`
                : "También puedes elegirlos desde tu equipo"}
            </span>
          </div>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={loading}
          >
            {waitingForDbf
              ? "Agregar archivo DBF"
              : data
                ? "Reemplazar archivo"
                : "Seleccionar archivos"}
          </button>
          <input
            ref={inputRef}
            className="hidden-file-input"
            type="file"
            multiple
            accept=".geojson,.json,.shp,.dbf,.shx,.prj,.zip,application/json,application/zip"
            onChange={(event) => {
              stageFiles(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
        </div>

        {pendingFiles.length > 0 && (
          <div className="detection-sidecar-note">
            <IconFileZip aria-hidden="true" />
            <span>
              <strong>
                {waitingForDbf
                  ? "El SHP contiene los puntos; falta la tabla de atributos"
                  : "Shapefile incompleto"}
              </strong>
              <small>
                {waitingForDbf
                  ? "Selecciona el DBF con el mismo nombre o utiliza un ZIP que incluya SHP + DBF."
                  : "Selecciona el SHP con el mismo nombre para completar el conjunto."}{" "}
                Puedes agregarlos en selecciones separadas.
              </small>
            </span>
          </div>
        )}

        {(loading || progress > 0) && (
          <div
            className={`detection-progress ${progress === 100 ? "is-complete" : ""}`}
            role="progressbar"
            aria-label="Progreso de importación"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
          >
            <div className="detection-progress-copy">
              <span>{progressMessage || "Archivo preparado"}</span>
              <strong>{progress}%</strong>
            </div>
            <div className="detection-progress-track">
              <span style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}

        {error && <p className="detection-error">{error}</p>}

        <div className="detection-workspace">
          <div className="detection-dashboard-grid">
            <section className="detection-dataset-card">
              <div className="detection-summary">
                <span className="detection-summary-icon">
                  <IconMapPin aria-hidden="true" />
                </span>
                <span>
                  <small>DETECCIONES</small>
                  <strong>{stats.count.toLocaleString()}</strong>
                </span>
                <button
                  className={visible ? "is-visible" : ""}
                  type="button"
                  onClick={onToggleLayer}
                  disabled={!data?.features.length}
                  aria-pressed={visible}
                  aria-label={
                    visible ? "Ocultar detecciones" : "Activar detecciones"
                  }
                  title={
                    visible ? "Ocultar detecciones" : "Activar detecciones"
                  }
                >
                  {visible ? (
                    <IconEye aria-hidden="true" />
                  ) : (
                    <IconEyeOff aria-hidden="true" />
                  )}
                </button>
              </div>
              <label
                className={`detection-diameter-field ${stats.unknown > 0 ? "has-unknown" : ""}`}
              >
                <span>
                  <strong>Campo de diámetro</strong>
                  <small>
                    {stats.unknown > 0
                      ? `${stats.unknown.toLocaleString()} sin medida`
                      : `${classifiedTotal.toLocaleString()} reconocidos`}
                  </small>
                </span>
                <select
                  value={selectedDiameterField}
                  onChange={(event) => {
                    const field = event.target.value;
                    setSelectedDiameterField(field);
                    onDiameterFieldChange(field || null);
                  }}
                >
                  <option value="">Detección automática</option>
                  {numericFields.map((field) => (
                    <option key={field} value={field}>
                      {field}
                    </option>
                  ))}
                </select>
              </label>
            </section>

            <section className="detection-representation-card">
              <div className="detection-section-heading">
                <span>
                  <small>REPRESENTACIÓN</small>
                  <strong>¿Cómo quieres verlas?</strong>
                </span>
                <IconAdjustmentsHorizontal aria-hidden="true" />
              </div>
              <div className="detection-view-modes">
                <button
                  className={displayMode === "points" ? "is-selected" : ""}
                  type="button"
                  onClick={() => onDisplayModeChange("points")}
                  aria-pressed={displayMode === "points"}
                >
                  <IconCircleDot aria-hidden="true" />
                  <span>
                    <strong>Puntos</strong>
                    <small>Símbolos compactos de tamaño fijo</small>
                  </span>
                  <i>
                    {displayMode === "points" && (
                      <IconCheck aria-hidden="true" />
                    )}
                  </i>
                </button>
                <button
                  className={displayMode === "diameters" ? "is-selected" : ""}
                  type="button"
                  onClick={() => onDisplayModeChange("diameters")}
                  aria-pressed={displayMode === "diameters"}
                >
                  <IconRulerMeasure aria-hidden="true" />
                  <span>
                    <strong>Diámetros</strong>
                    <small>Círculos proporcionales a la medida real</small>
                  </span>
                  <i>
                    {displayMode === "diameters" && (
                      <IconCheck aria-hidden="true" />
                    )}
                  </i>
                </button>
              </div>
              <div className="detection-editor">
                <div className="detection-editor-heading">
                  <span>
                    <small>EDICIÓN MANUAL</small>
                    <strong>Modificar sobre el mapa</strong>
                  </span>
                  <IconAdjustmentsHorizontal aria-hidden="true" />
                </div>
                <label className="detection-manual-diameter">
                  <span>Diámetro del punto nuevo</span>
                  <span>
                    <input
                      type="number"
                      min="0.01"
                      step="0.01"
                      value={manualDiameter}
                      onChange={(event) =>
                        setManualDiameter(Number(event.target.value))
                      }
                    />
                    <small>m</small>
                  </span>
                </label>
                <div className="detection-edit-actions">
                  <button
                    className={editMode === "add" ? "is-active" : ""}
                    type="button"
                    disabled={!validManualDiameter}
                    onClick={() => {
                      onAddDetection(manualDiameter);
                      onClose();
                    }}
                  >
                    <IconMapPinPlus aria-hidden="true" />
                    <span>
                      <strong>Agregar</strong>
                      <small>Marca un punto</small>
                    </span>
                  </button>
                  <button
                    className={editMode === "delete-one" ? "is-active" : ""}
                    type="button"
                    disabled={!data?.features.length}
                    onClick={() => {
                      onDeleteDetection();
                      onClose();
                    }}
                  >
                    <IconTrash aria-hidden="true" />
                    <span>
                      <strong>Eliminar una</strong>
                      <small>Pulsa la detección</small>
                    </span>
                  </button>
                  <button
                    className={editMode === "delete-area" ? "is-active" : ""}
                    type="button"
                    disabled={!data?.features.length}
                    onClick={() => {
                      onDeleteArea();
                      onClose();
                    }}
                  >
                    <IconBoxMultiple aria-hidden="true" />
                    <span>
                      <strong>Eliminar por área</strong>
                      <small>Dibuja una selección</small>
                    </span>
                  </button>
                </div>
              </div>
            </section>

            <section className="detection-histogram-card detection-analytics-card">
              <div className="detection-section-heading">
                <span>
                  <small>FILTRO INTERACTIVO</small>
                  <strong>Distribución por tamaño</strong>
                </span>
                <IconChartDonut aria-hidden="true" />
              </div>
              <p>
                La dona resume la proporción de diámetros. Selecciona una
                categoría para mostrarla u ocultarla en el mapa.
              </p>

              <div className="detection-pie-overview">
                <div className="detection-pie" style={pieStyle}>
                  <span>
                    <strong>{classifiedTotal.toLocaleString()}</strong>
                    <small>con diámetro</small>
                  </span>
                </div>
                <div className="detection-pie-copy">
                  <span className="detection-pie-title">
                    <IconChartDonut aria-hidden="true" />
                    <span>
                      <small>COMPOSICIÓN</small>
                      <strong>Proporción por tamaño</strong>
                    </span>
                  </span>
                  {(["small", "medium", "large"] as const).map((size) => (
                    <span className="detection-pie-row" key={size}>
                      <i style={{ backgroundColor: treeSizeColors[size] }} />
                      <span>{sizeMeta[size].label}</span>
                      <strong>
                        {classifiedTotal
                          ? Math.round((stats[size] / classifiedTotal) * 100)
                          : 0}
                        %
                      </strong>
                    </span>
                  ))}
                </div>
              </div>

              {classifiedTotal === 0 && (
                <div className="detection-histogram-empty">
                  <IconRulerMeasure aria-hidden="true" />
                  <span>
                    <strong>No se reconoció ningún diámetro</strong>
                    <small>
                      Selecciona arriba el campo numérico que contiene la
                      medida en metros.
                    </small>
                  </span>
                </div>
              )}

              <div className="detection-size-summary">
                {(["small", "medium", "large"] as const).map((size) => {
                  const count = stats[size];
                  const active = visibleSizes[size];
                  const style = {
                    "--size-color": treeSizeColors[size],
                  } as CSSProperties;
                  return (
                    <button
                      key={size}
                      className={active ? "is-active" : ""}
                      type="button"
                      style={style}
                      onClick={() => onToggleSize(size)}
                      aria-pressed={active}
                    >
                      <i aria-hidden="true" />
                      <span className="detection-histogram-value">
                        {count.toLocaleString()}
                      </span>
                      <span>
                        <strong>{sizeMeta[size].label}</strong>
                        <small>{sizeMeta[size].range}</small>
                      </span>
                    </button>
                  );
                })}
              </div>
              {stats.unknown > 0 && (
                <div className="detection-unknown-note">
                  {stats.unknown.toLocaleString()} detecciones no incluyen un
                  diámetro reconocible y se mantienen visibles en color gris.
                </div>
              )}
            </section>
          </div>
        </div>
      </section>
    </div>
  );
}
