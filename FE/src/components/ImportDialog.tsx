import { useRef, useState } from "react";
import {
  IconAperture,
  IconCamera,
  IconCheck,
  IconDrone,
  IconPhoto,
  IconSparkles,
  IconUpload,
  IconX,
} from "@tabler/icons-react";
import type { OrthoSensor } from "../services/api";

interface SensorOption {
  kind: OrthoSensor;
  title: string;
  description: string;
  category: "RGB" | "MULTIESPECTRAL";
  formats: string;
  accept: string;
}

/** Sensores admitidos y formatos presentados por el selector de archivos. */
const sensors: SensorOption[] = [
  {
    kind: "mavic3m",
    title: "Mavic 3M",
    description: "Plataforma DJI con cámara multiespectral",
    category: "MULTIESPECTRAL",
    formats: "TIFF · JP2 · IMG · ZIP",
    accept: ".tif,.tiff,.jp2,.img,.zip",
  },
  {
    kind: "mavic3rgb",
    title: "Mavic RGB",
    description: "Plataforma DJI con cámara RGB integrada",
    category: "RGB",
    formats: "TIFF · JP2 · PNG · JPG",
    accept: ".tif,.tiff,.jp2,.png,.jpg,.jpeg",
  },
  {
    kind: "rgb",
    title: "RGB genérico",
    description: "Ortomosaico RGB de cualquier plataforma",
    category: "RGB",
    formats: "TIFF · JP2 · PNG · JPG",
    accept: ".tif,.tiff,.jp2,.png,.jpg,.jpeg",
  },
  {
    kind: "micasense",
    title: "MicaSense",
    description: "Cámara multiespectral profesional",
    category: "MULTIESPECTRAL",
    formats: "TIFF · JP2 · IMG · ZIP",
    accept: ".tif,.tiff,.jp2,.img,.zip",
  },
];

interface Props {
  open: boolean;
  onClose: () => void;
  onFile: (file: File, sensor: OrthoSensor) => void;
}

function SensorIcon({ kind }: { kind: OrthoSensor }) {
  if (kind === "mavic3m" || kind === "mavic3rgb")
    return <IconDrone aria-hidden="true" />;
  if (kind === "micasense") return <IconAperture aria-hidden="true" />;
  return <IconCamera aria-hidden="true" />;
}

/** Modal de carga que asocia cada archivo con su procesamiento espectral. */
export function ImportDialog({ open, onClose, onFile }: Props) {
  const [sensor, setSensor] = useState<SensorOption>(sensors[0]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  if (!open) return null;
  // Centraliza clic y arrastre para entregar siempre el sensor seleccionado.
  const submit = (file: File | undefined) => {
    if (file) {
      onFile(file, sensor.kind);
      onClose();
    }
  };

  return (
    <div
      className="import-dialog-backdrop"
      role="presentation"
      onMouseDown={onClose}
    >
      <section
        className="import-dialog upload-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="upload-dialog-hero">
          <div className="upload-hero-icon">
            <IconDrone aria-hidden="true" />
          </div>
          <div className="upload-hero-copy">
            <span className="import-eyebrow">NUEVA MISIÓN</span>
            <h2 id="import-title">Importar ortomosaico</h2>
            <p>
              Configura el origen de la captura y carga el archivo para comenzar
              el análisis.
            </p>
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

        <div className="upload-steps" aria-label="Proceso de importación">
          <span className="is-active">
            <b>1</b>Seleccionar sensor
          </span>
          <i aria-hidden="true" />
          <span>
            <b>2</b>Cargar archivo
          </span>
        </div>

        <div className="sensor-section-heading">
          <div>
            <span className="sensor-step-icon">
              <IconPhoto aria-hidden="true" />
            </span>
            <span>
              <strong>¿Cómo se capturó?</strong>
              <small>Esto permite aplicar el procesamiento correcto.</small>
            </span>
          </div>
          <span className="sensor-selection-count">1 seleccionado</span>
        </div>

        <div
          className="sensor-options"
          role="radiogroup"
          aria-label="Sensor del ortomosaico"
        >
          {sensors.map((item) => {
            const selected = sensor.kind === item.kind;
            return (
              <button
                key={item.kind}
                type="button"
                role="radio"
                aria-checked={selected}
                className={selected ? "is-selected" : ""}
                onClick={() => setSensor(item)}
              >
                <span className="sensor-card-icon">
                  <SensorIcon kind={item.kind} />
                </span>
                <span className="sensor-card-copy">
                  <strong>{item.title}</strong>
                  <small>{item.description}</small>
                </span>
                <span className="sensor-card-check" aria-hidden="true">
                  <IconCheck />
                </span>
                <span
                  className={`sensor-category sensor-category-${item.category.toLowerCase()}`}
                >
                  {item.category}
                </span>
                <span className="sensor-formats">{item.formats}</span>
              </button>
            );
          })}
        </div>

        <input
          ref={inputRef}
          className="hidden-file-input"
          type="file"
          accept={sensor.accept}
          onChange={(event) => {
            submit(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <button
          className={`upload-dropzone ${dragging ? "is-dragging" : ""}`}
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            submit(event.dataTransfer.files?.[0]);
          }}
        >
          <span className="upload-dropzone-icon">
            <IconUpload aria-hidden="true" />
          </span>
          <strong>
            {dragging
              ? "Suelta el archivo para cargarlo"
              : "Arrastra aquí tu ortomosaico"}
          </strong>
          <small>o haz clic para buscarlo en tu equipo</small>
          <span className="upload-selected-sensor">
            <IconCheck aria-hidden="true" />
            {sensor.title}
            <i />
            {sensor.formats}
          </span>
        </button>

        <p className="import-dialog-note upload-note">
          <IconSparkles aria-hidden="true" />
          <span>
            <strong>Listo para analizar</strong> El archivo se guardará de forma
            segura en la base de datos.
          </span>
        </p>
      </section>
    </div>
  );
}
