import { useRef, useState } from "react";
import {
  IconActivity,
  IconArrowsHorizontal,
  IconChartHistogram,
  IconDatabase,
  IconDroplet,
  IconEyeOff,
  IconLeaf,
  IconMapPin,
  IconPhoto,
  IconTrash,
  IconX,
} from "@tabler/icons-react";
import { useDashboardMap } from "../hooks/useDashboardMap";
import { ActionBar } from "./ActionBar";
import { ControlPanel } from "./ControlPanel";
import { ConfirmDialog } from "./ConfirmDialog";
import { DetectionDialog } from "./DetectionDialog";
import { ImportDialog } from "./ImportDialog";
import { RoiDialog } from "./RoiDialog";
import { RoiComparisonDialog } from "./RoiComparisonDialog";
import {
  dashboardApi,
  type OrthomosaicRecord,
  type OrthoSensor,
  type RoiAnalysisRecord,
  type RoiAnalysisStats,
  type SaveRoiAnalysisPayload,
  type RoiRecord,
} from "../services/api";

type DeleteTarget =
  | { kind: "orthomosaic"; record: OrthomosaicRecord }
  | { kind: "roi"; record: RoiRecord }
  | { kind: "analysis"; record: RoiAnalysisRecord };
type ComparisonIndex = "NDVI" | "NDWI" | "NDRE";

const sameMetric = (
  left: number | null | undefined,
  right: number | null | undefined,
) => {
  if (left == null && right == null) return true;
  if (left == null || right == null) return false;
  return Math.abs(left - right) < 1e-6;
};

const statsForIndex = (
  analysis: RoiAnalysisRecord,
  index: ComparisonIndex,
): RoiAnalysisStats | null =>
  index === "NDVI"
    ? analysis.ndvi
    : index === "NDWI"
      ? analysis.ndwi
      : analysis.ndre;

const chronologicalKey = (analysis: RoiAnalysisRecord) =>
  `${analysis.orthomosaics?.capture_date ?? analysis.created_at}|${analysis.created_at}`;

const sameStats = (
  current: RoiAnalysisStats | null,
  expected: RoiAnalysisStats,
) =>
  current != null &&
  current.count === expected.count &&
  sameMetric(current.min, expected.min) &&
  sameMetric(current.max, expected.max) &&
  sameMetric(current.mean, expected.mean) &&
  sameMetric(current.median, expected.median) &&
  sameMetric(current.standard_deviation, expected.standard_deviation) &&
  sameMetric(current.p10, expected.p10) &&
  sameMetric(current.p25, expected.p25) &&
  sameMetric(current.p75, expected.p75) &&
  sameMetric(current.p90, expected.p90) &&
  sameMetric(current.range_min, expected.range_min) &&
  sameMetric(current.range_max, expected.range_max);

function IndexIcon({ name }: { name: "NDVI" | "NDWI" | "NDRE" }) {
  if (name === "NDVI")
    return <IconLeaf className="index-option-icon" aria-hidden="true" />;
  if (name === "NDWI")
    return <IconDroplet className="index-option-icon" aria-hidden="true" />;
  return <IconActivity className="index-option-icon" aria-hidden="true" />;
}

/**
 * Contenedor principal de la aplicación. Compone el mapa, los modales y el
 * panel, mientras `useDashboardMap` conserva la lógica imperativa de Leaflet.
 */
export function MapView() {
  const mapElement = useRef<HTMLDivElement>(null);
  const divider = useRef<HTMLDivElement>(null);
  const map = useDashboardMap(mapElement);
  // Estado puramente visual de modales, carga y confirmaciones.
  const [dragging, setDragging] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [detectionsOpen, setDetectionsOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [indicesOpen, setIndicesOpen] = useState(false);
  const [roiOpen, setRoiOpen] = useState(false);
  const [roiLibraryOpen, setRoiLibraryOpen] = useState(false);
  const [rois, setRois] = useState<RoiRecord[]>([]);
  const [orthomosaics, setOrthomosaics] = useState<OrthomosaicRecord[]>([]);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  // El ROI de comparación se fija al abrir el dashboard para evitar que un
  // cambio posterior de selección afecte exportaciones o eliminaciones.
  const [roiAnalysisHistory, setRoiAnalysisHistory] = useState<
    RoiAnalysisRecord[]
  >([]);
  const [comparisonRoiId, setComparisonRoiId] = useState<string | null>(null);
  const [comparisonIndex, setComparisonIndex] =
    useState<ComparisonIndex>("NDVI");
  const [roiAnalysisSyncedAt, setRoiAnalysisSyncedAt] = useState<string | null>(
    null,
  );
  const [roiComparisonOpen, setRoiComparisonOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<ComparisonIndex | null>(
    null,
  );
  const [roiAnalysisLoading, setRoiAnalysisLoading] = useState(false);
  const [roiAnalysisSaving, setRoiAnalysisSaving] = useState(false);
  const [roiAnalysisExporting, setRoiAnalysisExporting] = useState(false);
  const [roiAnalysisDeletingId, setRoiAnalysisDeletingId] = useState<
    string | null
  >(null);
  const [roiAnalysisError, setRoiAnalysisError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Bibliotecas persistidas de vuelos y regiones.
  const openLibrary = async () => {
    try {
      const response = await dashboardApi.orthomosaics();
      setOrthomosaics(response.items);
      setLibraryError(null);
      setLibraryOpen(true);
    } catch (error) {
      setLibraryError(
        error instanceof Error
          ? error.message
          : "No se pudo consultar la biblioteca.",
      );
      setLibraryOpen(true);
    }
  };
  const toggleIndex = (name: "NDVI" | "NDWI" | "NDRE") => {
    if (name === "NDVI") {
      if (map.ndviAnalysis.response) {
        setSelectedIndex((current) => (current === "NDVI" ? null : "NDVI"));
        void map.toggleNdvi();
      } else {
        setSelectedIndex("NDVI");
        void map.selectIndex(name);
      }
      return;
    }
    const analysis = map.indexAnalyses.find((item) => item.name === name);
    if (analysis) {
      setSelectedIndex((current) => (current === name ? null : name));
      map.toggleIndexLayer(name);
    } else {
      setSelectedIndex(name);
      void map.selectIndex(name);
    }
  };
  const openRoiLibrary = async () => {
    try {
      const response = await dashboardApi.rois();
      setRois(response.items);
      setRoiLibraryOpen(true);
    } catch (error) {
      window.alert(
        error instanceof Error
          ? error.message
          : "No se pudieron cargar los ROI.",
      );
    }
  };
  /** Sustituye el historial local únicamente con la respuesta fresca del API. */
  const requestRoiAnalysisHistory = async (
    roiId: string,
    index: ComparisonIndex,
  ) => {
    const response = await dashboardApi.roiAnalyses(roiId, index);
    setRoiAnalysisHistory(response.items);
    setRoiAnalysisSyncedAt(new Date().toISOString());
    return response.items;
  };
  const refreshRoiAnalysisHistory = async (
    roiId: string,
    index: ComparisonIndex,
  ) => {
    setRoiAnalysisLoading(true);
    setRoiAnalysisError(null);
    try {
      return await requestRoiAnalysisHistory(roiId, index);
    } catch (error) {
      setRoiAnalysisError(
        error instanceof Error
          ? error.message
          : "No se pudo cargar el historial del ROI.",
      );
      throw error;
    } finally {
      setRoiAnalysisLoading(false);
    }
  };
  const historyContainsSavedStats = (
    analysis: RoiAnalysisRecord,
    roiId: string,
    orthomosaicId: string,
    payload: SaveRoiAnalysisPayload,
  ) => {
    if (analysis.roi_id !== roiId || analysis.orthomosaic_id !== orthomosaicId)
      return false;
    return sameStats(statsForIndex(analysis, payload.index), payload.stats);
  };
  const loadRoiAnalysisHistory = async (index: ComparisonIndex) => {
    const roiId = map.state.selectedRoiId;
    if (roiId) {
      setComparisonIndex(index);
      setComparisonRoiId(roiId);
      setRoiComparisonOpen(true);
      try {
        await refreshRoiAnalysisHistory(roiId, index);
      } catch {
        /* El error ya se muestra dentro del modal. */
      }
      return;
    }
    if (!roiId) {
      window.alert(
        "Activa un análisis global o selecciona y recorta un ROI guardado antes de comparar vuelos.",
      );
      return;
    }
  };
  const activeRoiIndexReady =
    selectedIndex === "NDVI"
      ? Boolean(map.ndviAnalysis.roiResponse)
      : selectedIndex != null
        ? map.indexAnalyses.some((analysis) => analysis.name === selectedIndex)
        : false;
  const saveRoiAnalysis = async (payload: SaveRoiAnalysisPayload) => {
    const roiId = map.state.selectedRoiId;
    const orthomosaicId = map.state.orthomosaicId;
    if (!selectedIndex || !roiId || !orthomosaicId || !activeRoiIndexReady) {
      window.alert(
        "Selecciona un ROI, recórtalo y activa su NDVI antes de guardar estadísticas.",
      );
      return;
    }
    setRoiAnalysisSaving(true);
    try {
      const response = await dashboardApi.saveRoiAnalysis(
        roiId,
        orthomosaicId,
        payload,
      );
      setComparisonIndex(payload.index);
      setComparisonRoiId(roiId);
      if (
        !historyContainsSavedStats(
          response.analysis,
          roiId,
          orthomosaicId,
          payload,
        )
      ) {
        const persisted = statsForIndex(response.analysis, payload.index);
        throw new Error(
          `La base de datos devolvio un registro distinto a la tabla dinamica del histograma. Esperado: prom=${payload.stats.mean}, min=${payload.stats.min}, max=${payload.stats.max}, pixeles=${payload.stats.count}. Persistido: prom=${persisted?.mean ?? "null"}, min=${persisted?.min ?? "null"}, max=${persisted?.max ?? "null"}, pixeles=${persisted?.count ?? "null"}. No se actualizo el dashboard para evitar mezclar valores.`,
        );
      }
      setRoiAnalysisHistory((current) => {
        const next = current.filter((item) => item.id !== response.analysis.id);
        next.push(response.analysis);
        return next;
      });
      setRoiAnalysisSyncedAt(new Date().toISOString());
      setRoiComparisonOpen(true);
      try {
        await refreshRoiAnalysisHistory(roiId, payload.index);
      } catch (error) {
        setRoiAnalysisError(
          error instanceof Error
            ? `Las estadisticas se guardaron en la base de datos, pero no se pudo refrescar el dashboard: ${error.message}`
            : "Las estadisticas se guardaron en la base de datos, pero no se pudo refrescar el dashboard.",
        );
      }
    } catch (error) {
      setRoiAnalysisError(
        error instanceof Error
          ? error.message
          : "No se pudieron guardar las estadisticas del ROI.",
      );
      window.alert(
        error instanceof Error
          ? error.message
          : "No se pudieron guardar las estadísticas del ROI.",
      );
    } finally {
      setRoiAnalysisSaving(false);
    }
  };
  /**
   * Vuelve a consultar el servidor antes de construir el CSV. Los valores
   * numéricos se exportan con su precisión original, no con la de la interfaz.
   */
  const exportRoiAnalysisHistory = async () => {
    const roiId = comparisonRoiId;
    if (!roiId) {
      setRoiAnalysisError(
        "No hay un ROI asociado a esta comparación. Cierra el modal y selecciona nuevamente la zona.",
      );
      return;
    }
    setRoiAnalysisExporting(true);
    setRoiAnalysisError(null);
    try {
      const items = await requestRoiAnalysisHistory(roiId, comparisonIndex);
      if (!items.length)
        throw new Error("No hay estadísticas vigentes para exportar.");
      const chronological = [...items].sort((left, right) =>
        chronologicalKey(left).localeCompare(chronologicalKey(right)),
      );
      // Escapa texto para CSV y neutraliza fórmulas inyectadas desde nombres.
      const csvCell = (value: string | number | null | undefined) => {
        if (value == null) return "";
        if (typeof value === "number")
          return Number.isFinite(value) ? String(value) : "";
        const protectedValue = /^[=+\-@]/.test(value) ? `'${value}` : value;
        return `"${protectedValue.replace(/"/g, '""')}"`;
      };
      const rows: Array<Array<string | number | null | undefined>> = [
        [
          "registro_id",
          "roi_id",
          "orthomosaico_id",
          "ortomosaico",
          "fecha_captura",
          "fecha_guardado",
          "pixeles_ndvi",
          "ndvi_minimo",
          "ndvi_maximo",
          "ndvi_promedio",
          "ndvi_mediana",
          "ndvi_desviacion_estandar",
          "ndvi_p10",
          "ndvi_p25",
          "ndvi_p75",
          "ndvi_p90",
          "pixeles_ndwi",
          "ndwi_minimo",
          "ndwi_maximo",
          "ndwi_promedio",
          "ndwi_mediana",
          "ndwi_desviacion_estandar",
          "ndwi_p10",
          "ndwi_p25",
          "ndwi_p75",
          "ndwi_p90",
          "pixeles_ndre",
          "ndre_minimo",
          "ndre_maximo",
          "ndre_promedio",
          "ndre_mediana",
          "ndre_desviacion_estandar",
          "ndre_p10",
          "ndre_p25",
          "ndre_p75",
          "ndre_p90",
        ],
        ...chronological.map((analysis) => [
          analysis.id,
          analysis.roi_id,
          analysis.orthomosaic_id,
          analysis.orthomosaics?.name ?? "Ortomosaico eliminado",
          analysis.orthomosaics?.capture_date ?? "",
          analysis.created_at,
          analysis.ndvi.count,
          analysis.ndvi.min,
          analysis.ndvi.max,
          analysis.ndvi.mean,
          analysis.ndvi.median ?? null,
          analysis.ndvi.standard_deviation,
          analysis.ndvi.p10 ?? null,
          analysis.ndvi.p25 ?? null,
          analysis.ndvi.p75 ?? null,
          analysis.ndvi.p90 ?? null,
          analysis.ndwi?.count ?? null,
          analysis.ndwi?.min ?? null,
          analysis.ndwi?.max ?? null,
          analysis.ndwi?.mean ?? null,
          analysis.ndwi?.median ?? null,
          analysis.ndwi?.standard_deviation ?? null,
          analysis.ndwi?.p10 ?? null,
          analysis.ndwi?.p25 ?? null,
          analysis.ndwi?.p75 ?? null,
          analysis.ndwi?.p90 ?? null,
          analysis.ndre?.count ?? null,
          analysis.ndre?.min ?? null,
          analysis.ndre?.max ?? null,
          analysis.ndre?.mean ?? null,
          analysis.ndre?.median ?? null,
          analysis.ndre?.standard_deviation ?? null,
          analysis.ndre?.p10 ?? null,
          analysis.ndre?.p25 ?? null,
          analysis.ndre?.p75 ?? null,
          analysis.ndre?.p90 ?? null,
        ]),
      ];
      const contents = `\uFEFF${rows.map((row) => row.map(csvCell).join(";")).join("\r\n")}`;
      const blobUrl = URL.createObjectURL(
        new Blob([contents], { type: "text/csv;charset=utf-8" }),
      );
      const link = document.createElement("a");
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      link.href = blobUrl;
      link.download = `comparacion_indices_${roiId.slice(0, 8)}_${timestamp}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
    } catch (error) {
      setRoiAnalysisError(
        error instanceof Error
          ? error.message
          : "No se pudieron exportar las estadísticas actualizadas.",
      );
    } finally {
      setRoiAnalysisExporting(false);
    }
  };
  /** Ejecuta la eliminación confirmada y sincroniza la colección afectada. */
  const confirmDeletion = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      if (target.kind === "orthomosaic") {
        await dashboardApi.deleteOrthomosaic(target.record.id);
        setOrthomosaics((items) =>
          items.filter((item) => item.id !== target.record.id),
        );
        if (map.state.orthomosaicId === target.record.id) {
          map.clearRoiSelection();
          map.fitRgb();
        }
      } else if (target.kind === "roi") {
        await dashboardApi.deleteRoi(target.record.id);
        setRois((items) =>
          items.filter((item) => item.id !== target.record.id),
        );
        map.removeRoiPolygon(target.record.id);
      } else {
        const roiId = comparisonRoiId;
        if (!roiId)
          throw new Error(
            "El ROI ya no está seleccionado. Vuelve a abrir la comparación.",
          );
        setRoiAnalysisDeletingId(target.record.id);
        setRoiAnalysisError(null);
        await dashboardApi.deleteRoiAnalysis(roiId, target.record.id);
        setRoiAnalysisHistory((items) =>
          items.filter((item) => item.id !== target.record.id),
        );
        try {
          await requestRoiAnalysisHistory(roiId, comparisonIndex);
        } catch (error) {
          setRoiAnalysisError(
            error instanceof Error
              ? `La estadística fue eliminada, pero no se pudo verificar el historial: ${error.message}`
              : "La estadística fue eliminada, pero no se pudo verificar el historial actualizado.",
          );
        }
      }
      setDeleteTarget(null);
    } catch (error) {
      setDeleteError(
        error instanceof Error
          ? error.message
          : "No se pudo completar la eliminación.",
      );
    } finally {
      setRoiAnalysisDeletingId(null);
      setDeleteBusy(false);
    }
  };

  // Un único diálogo de confirmación adapta su mensaje al tipo de registro.
  const deleteDialogContent =
    deleteTarget?.kind === "orthomosaic"
      ? {
          title: "¿Eliminar este ortomosaico?",
          description:
            "Se eliminarán el registro y su archivo almacenado. Esta acción no se puede deshacer.",
          subject: deleteTarget.record.name,
        }
      : deleteTarget?.kind === "roi"
        ? {
            title: "¿Eliminar esta región?",
            description:
              "El ROI y su historial asociado dejarán de estar disponibles. Esta acción no se puede deshacer.",
            subject: deleteTarget.record.name,
          }
        : deleteTarget?.kind === "analysis"
          ? {
              title: "¿Eliminar estas estadísticas?",
              description:
                "Se quitará este registro del historial comparativo del ROI. Esta acción no se puede deshacer.",
              subject:
                deleteTarget.record.orthomosaics?.name ??
                "Ortomosaico eliminado",
            }
          : { title: "", description: "", subject: "" };

  /** Convierte la posición horizontal del puntero al porcentaje del swipe. */
  const moveDivider = (event: React.PointerEvent) => {
    const rect = divider.current?.parentElement?.getBoundingClientRect();

    if (rect) {
      map.setSwipePosition(((event.clientX - rect.left) / rect.width) * 100);
    }
  };

  return (
    <main className="map-shell">
      <div ref={mapElement} className="map" />
      <ActionBar
        state={map.state}
        onOrthoLibrary={() => void openLibrary()}
        onOpenIndices={() => setIndicesOpen(true)}
        onOpenRoi={() => setRoiOpen(true)}
        onOpenDetections={() => setDetectionsOpen(true)}
        onLabels={map.toggleLabels}
        onImport={() => setImportDialogOpen(true)}
      />
      {map.state.detectionEditMode && (
        <div className="detection-edit-banner" role="status">
          <IconMapPin aria-hidden="true" />
          <span>
            <strong>Edición de detecciones</strong>
            <small>
              {map.state.detectionEditMode === "add"
                ? "Haz clic en el mapa para colocar la detección."
                : map.state.detectionEditMode === "delete-one"
                  ? "Pulsa la detección que deseas eliminar."
                  : "Dibuja un rectángulo sobre las detecciones que deseas eliminar."}
            </small>
          </span>
          <button
            type="button"
            onClick={map.cancelDetectionEdit}
            aria-label="Cancelar edición"
          >
            <IconX aria-hidden="true" />
          </button>
        </div>
      )}
      <ImportDialog
        open={importDialogOpen}
        onClose={() => setImportDialogOpen(false)}
        onFile={(file, sensor) => void map.importOrtho(file, sensor)}
      />
      <DetectionDialog
        open={detectionsOpen}
        data={map.treeData}
        visible={map.state.trees}
        displayMode={map.state.treeDisplayMode}
        editMode={map.state.detectionEditMode}
        visibleSizes={map.state.visibleTreeSizes}
        onImport={map.importDetections}
        onToggleLayer={map.toggleTrees}
        onDisplayModeChange={map.setTreeDisplayMode}
        onDiameterFieldChange={map.setTreeDiameterField}
        onAddDetection={map.startAddDetection}
        onDeleteDetection={map.startDeleteDetection}
        onDeleteArea={map.startDeleteDetectionsArea}
        onToggleSize={map.toggleTreeSize}
        onClose={() => setDetectionsOpen(false)}
      />
      <RoiDialog
        open={roiOpen}
        onClose={() => setRoiOpen(false)}
        onDraw={map.drawRoi}
        onImport={(files) => void map.importRoi(files)}
        onManage={() => void openRoiLibrary()}
      />
      {roiLibraryOpen && (
        <div
          className="import-dialog-backdrop"
          role="presentation"
          onMouseDown={() => setRoiLibraryOpen(false)}
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
                onClick={() => setRoiLibraryOpen(false)}
                aria-label="Cerrar"
              >
                <IconX aria-hidden="true" />
              </button>
            </div>
            <div className="modal-intro-row">
              <p className="import-dialog-copy">
                Agrega dos, tres o tantas regiones como necesites. La tijera
                procesará todas juntas.
              </p>
              <span className="modal-record-count">
                {map.state.selectedRoiIds.length} de {rois.length} seleccionadas
              </span>
            </div>
            {rois.length > 0 && (
              <div className="roi-table-wrap">
                <table className="roi-table">
                  <thead>
                    <tr>
                      <th>Nombre</th>
                      <th>Fecha de creación</th>
                      <th aria-label="Acciones" />
                    </tr>
                  </thead>
                  <tbody>
                    {rois.map((roi) => {
                      const selected = map.state.selectedRoiIds.includes(
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
                                  map.selectRoi(roi.geojson, roi.id)
                                }
                              >
                                {selected ? "Quitar" : "Agregar"}
                              </button>
                              <button
                                className="delete-orthomosaic button-with-icon"
                                type="button"
                                onClick={() => {
                                  setDeleteError(null);
                                  setDeleteTarget({ kind: "roi", record: roi });
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
                  Dibuja o importa una región para verla en esta biblioteca.
                </span>
              </div>
            )}
          </section>
        </div>
      )}
      {indicesOpen && (
        <div
          className="import-dialog-backdrop"
          role="presentation"
          onMouseDown={() => setIndicesOpen(false)}
        >
          <section
            className="import-dialog indices-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="indices-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="import-dialog-heading">
              <div className="modal-title-group">
                <span className="modal-title-icon">
                  <IconChartHistogram aria-hidden="true" />
                </span>
                <div>
                  <span className="import-eyebrow">ANÁLISIS ESPECTRAL</span>
                  <h2 id="indices-title">Índices de vegetación</h2>
                </div>
              </div>
              <button
                className="dialog-close"
                type="button"
                onClick={() => setIndicesOpen(false)}
                aria-label="Cerrar"
              >
                <IconX aria-hidden="true" />
              </button>
            </div>
            <p className="import-dialog-copy">
              Activa las capas que deseas analizar. Puedes mantener varios
              índices visibles al mismo tiempo.
            </p>
            <div className="index-selector">
              {(["NDVI", "NDWI", "NDRE"] as const).map((name) => {
                const active =
                  name === "NDVI"
                    ? map.state.ndvi
                    : map.indexAnalyses.some(
                        (analysis) =>
                          analysis.name === name && analysis.visible,
                      );
                return (
                  <button
                    key={name}
                    type="button"
                    className={active ? "is-active" : ""}
                    onClick={() => toggleIndex(name)}
                  >
                    <IndexIcon name={name} />
                    <span>
                      <strong>{name}</strong>
                      <small>
                        {active ? "Índice visible" : "Índice oculto"}
                      </small>
                    </span>
                    <i
                      className={`layer-toggle ${active ? "is-on" : ""}`}
                      aria-label={active ? "Encendido" : "Apagado"}
                    >
                      <b />
                    </i>
                  </button>
                );
              })}
            </div>
            <button
              className="hide-all-indices button-with-icon"
              type="button"
              onClick={map.hideIndices}
            >
              <IconEyeOff aria-hidden="true" />
              Ocultar todos los índices
            </button>
          </section>
        </div>
      )}
      {libraryOpen && (
        <div
          className="import-dialog-backdrop"
          role="presentation"
          onMouseDown={() => setLibraryOpen(false)}
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
                onClick={() => setLibraryOpen(false)}
                aria-label="Cerrar"
              >
                <IconX aria-hidden="true" />
              </button>
            </div>
            <div className="modal-intro-row">
              <p className="import-dialog-copy">
                Consulta, activa o administra los ortomosaicos disponibles.
              </p>
              <span className="modal-record-count">
                {orthomosaics.length}{" "}
                {orthomosaics.length === 1 ? "archivo" : "archivos"}
              </span>
            </div>
            {libraryError && <p className="library-error">{libraryError}</p>}
            {!libraryError && (
              <div className="orthomosaic-table-wrap">
                <table className="orthomosaic-table">
                  <thead>
                    <tr>
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
                        map.state.orthomosaicId === record.id && map.state.rgb;
                      return (
                        <tr key={record.id}>
                          <td>
                            <strong>{record.name}</strong>
                            <small>{record.original_filename}</small>
                          </td>
                          <td>{record.capture_date}</td>
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
                                if (active) map.fitRgb();
                                else void map.activateStoredOrtho(record);
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
                                setDeleteError(null);
                                setDeleteTarget({
                                  kind: "orthomosaic",
                                  record,
                                });
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
                    <strong>No hay ortomosaicos guardados</strong>
                    <span>Importa un vuelo para comenzar tu biblioteca.</span>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
      <ControlPanel
        data={map.treeData}
        filteredData={map.filteredTreeData}
        selectedIndex={selectedIndex}
        visibleTreeSizes={map.state.visibleTreeSizes}
        onToggleTreeSize={map.toggleTreeSize}
        ndvi={
          map.state.orthoMode === "multispectral"
            ? map.ndviAnalysis
            : { ...map.ndviAnalysis, response: null }
        }
        indices={map.indexAnalyses}
        onDiameterRangeChange={map.setDiameterRange}
        onNdviRangeChange={map.setNdviRange}
        onIndexRangeChange={map.setIndexRange}
        ndviVisible={map.state.ndvi}
        onToggleNdvi={() => void map.toggleNdvi()}
        onToggleIndex={map.toggleIndexLayer}
        onHideNdvi={map.hideNdvi}
        onHideIndex={map.hideIndex}
        canSaveRoiAnalysis={Boolean(
          selectedIndex &&
          map.state.selectedRoiId &&
            map.state.orthomosaicId &&
            activeRoiIndexReady,
        )}
        roiAnalysisSaving={roiAnalysisSaving}
        onSaveRoiAnalysis={(payload) => void saveRoiAnalysis(payload)}
        onOpenRoiComparison={(index) => void loadRoiAnalysisHistory(index)}
      />
      <RoiComparisonDialog
        open={roiComparisonOpen}
        activeIndex={comparisonIndex}
        items={roiAnalysisHistory}
        loading={roiAnalysisLoading}
        exporting={roiAnalysisExporting}
        deletingId={roiAnalysisDeletingId}
        error={roiAnalysisError}
        syncedAt={roiAnalysisSyncedAt}
        onRefresh={() =>
          comparisonRoiId
            ? refreshRoiAnalysisHistory(comparisonRoiId, comparisonIndex)
                .then(() => undefined)
                .catch(() => undefined)
            : Promise.resolve()
        }
        onExport={() => void exportRoiAnalysisHistory()}
        onDelete={(analysis) => {
          setDeleteError(null);
          setDeleteTarget({ kind: "analysis", record: analysis });
        }}
        onClose={() => setRoiComparisonOpen(false)}
      />
      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteDialogContent.title}
        description={deleteDialogContent.description}
        subject={deleteDialogContent.subject}
        busy={deleteBusy}
        error={deleteError}
        onCancel={() => {
          if (!deleteBusy) {
            setDeleteTarget(null);
            setDeleteError(null);
          }
        }}
        onConfirm={() => void confirmDeletion()}
      />
      <button
        className={`swipe-toggle ${map.state.swipe ? "" : "is-off"}`}
        onClick={map.toggleSwipe}
        aria-pressed={map.state.swipe}
        title={map.state.swipe ? "Desactivar swipe" : "Activar swipe"}
      >
        <IconArrowsHorizontal aria-hidden="true" />
      </button>
      {map.state.swipe && (
        <div
          ref={divider}
          className="swipe-divider"
          style={{ left: `${map.state.swipePosition}%` }}
          onPointerDown={(event) => {
            setDragging(true);
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (dragging) {
              moveDivider(event);
            }
          }}
          onPointerUp={() => setDragging(false)}
        />
      )}
      {map.state.error && (
        <div className="error-toast" role="alert">
          {map.state.error}
        </div>
      )}
      {map.state.uploading && (
        <div className="uploading-overlay" role="status" aria-live="polite">
          <div className="uploading-card">
            <span className="uploading-spinner" aria-hidden="true" />
            <strong>Estamos cargando tu ortomosaico</strong>
            <small>
              Guardando el archivo y preparando el mapa. Esto puede tardar unos
              minutos.
            </small>
          </div>
        </div>
      )}
    </main>
  );
}


