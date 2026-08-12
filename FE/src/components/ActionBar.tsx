/**
 * Barra superior de acciones rápidas del dashboard geoespacial.
 * Centraliza accesos a capas, herramientas y diálogos sin mezclar esa UI
 * con la lógica imperativa del mapa.
 */
import {
  IconLeaf,
  IconMap2,
  IconPolygon,
  IconTags,
  IconTrees,
  IconUpload,
} from "@tabler/icons-react";

interface Props {
  state: { rgb: boolean; ndvi: boolean; trees: boolean; labels: boolean };
  onOrthoLibrary: () => void;
  onOpenIndices: () => void;
  onOpenRoi: () => void;
  onOpenDetections: () => void;
  onLabels: () => void;
  onImport: () => void;
}

/** Barra flotante que concentra los accesos principales sin administrar capas. */
export function ActionBar({
  state,
  onOrthoLibrary,
  onOpenIndices,
  onOpenRoi,
  onOpenDetections,
  onLabels,
  onImport,
}: Props) {
  return (
    <div className="action-bar">
      <button
        className={`action-pill ${state.rgb ? "is-active" : ""}`}
        onClick={onOrthoLibrary}
        title="Ortomosaicos guardados"
        aria-label="Ortomosaicos guardados"
        aria-pressed={state.rgb}
      >
        <IconMap2 aria-hidden="true" />
      </button>
      <button
        className={`action-pill ${state.ndvi ? "is-active" : ""}`}
        onClick={onOpenIndices}
        title="Activar índices"
        aria-label="Activar índices"
      >
        <IconLeaf aria-hidden="true" />
      </button>
      <button
        className="action-pill"
        onClick={onOpenRoi}
        title="Región de interés"
        aria-label="Región de interés"
      >
        <IconPolygon aria-hidden="true" />
      </button>
      <button
        className={`action-pill ${state.trees ? "is-active" : ""}`}
        onClick={onOpenDetections}
        title="Importar y administrar detecciones"
        aria-label="Importar y administrar detecciones"
      >
        <IconTrees aria-hidden="true" />
      </button>
      <button
        className={`action-pill ${state.labels ? "is-active" : ""}`}
        onClick={onLabels}
        title="Activar etiquetas"
        aria-label="Activar etiquetas"
      >
        <IconTags aria-hidden="true" />
      </button>
      <button
        className="action-pill"
        onClick={onImport}
        title="Importar GeoJSON"
        aria-label="Importar GeoJSON"
      >
        <IconUpload aria-hidden="true" />
      </button>
    </div>
  );
}
