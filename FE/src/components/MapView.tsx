/**
 * Contenedor principal de la aplicaciÃ³n.
 * Ensambla el hook geoespacial, el mapa Leaflet y todos los paneles de UI
 * visibles para el usuario final.
 */
import { useEffect, useRef, useState } from "react";
import {
  IconActivity,
  IconArrowsHorizontal,
  IconChartHistogram,
  IconCheck,
  IconDroplet,
  IconEyeOff,
  IconLeaf,
  IconMapPin,
  IconX,
} from "@tabler/icons-react";
import { useDashboardMap } from "../hooks/useDashboardMap";
import {
  ACTIVE_CYCLE_STORAGE_KEY,
  loadStoredActiveCycle,
  statsForIndex,
  type ComparisonIndex,
} from "./MapView.helpers";
import {
  buildRoiComparisonCsv,
  analysisMatchesSavedStats,
  getActivePrescriptionDisplayRange,
  getDeleteDialogContent,
} from "./MapView.logic";
import {
  MapViewOrthomosaicLibraryDialog,
  MapViewRoiLibraryDialog,
} from "./MapViewLibraries";
import { ActionBar } from "./ActionBar";
import { AgriculturalCycleDialog } from "./AgriculturalCycleDialog";
import { ControlPanel } from "./ControlPanel";
import { ConfirmDialog } from "./ConfirmDialog";
import { DetectionDialog } from "./DetectionDialog";
import { ImportDialog } from "./ImportDialog";
import { RoiDialog } from "./RoiDialog";
import { RoiComparisonDialog } from "./RoiComparisonDialog";
import {
  PrescriptionDialog,
  PrescriptionLegend,
} from "./PrescriptionDialog";
import {
  dashboardApi,
  type AgriculturalCycleRecord,
  type OrthomosaicRecord,
  type OrthoSensor,
  type RoiAnalysisRecord,
  type SaveRoiAnalysisPayload,
  type RoiRecord,
} from "../services/api";

type DeleteTarget =
  | { kind: "cycle"; record: AgriculturalCycleRecord }
  | { kind: "orthomosaic"; record: OrthomosaicRecord }
  | { kind: "roi"; record: RoiRecord }
  | { kind: "analysis"; record: RoiAnalysisRecord };
type CycleDialogMode = "entry" | "import" | "library";

function IndexIcon({ name }: { name: "NDVI" | "NDWI" | "NDRE" }) {
  if (name === "NDVI")
    return <IconLeaf className="index-option-icon" aria-hidden="true" />;
  if (name === "NDWI")
    return <IconDroplet className="index-option-icon" aria-hidden="true" />;
  return <IconActivity className="index-option-icon" aria-hidden="true" />;
}

/**
 * Contenedor principal de la aplicaciÃ³n. Compone el mapa, los modales y el
 * panel, mientras `useDashboardMap` conserva la lÃ³gica imperativa de Leaflet.
 */
export function MapView() {
  const mapElement = useRef<HTMLDivElement>(null);
  const divider = useRef<HTMLDivElement>(null);
  // Estado puramente visual de modales, carga y confirmaciones.
  const [dragging, setDragging] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [cycleDialogOpen, setCycleDialogOpen] = useState(false);
  const [cycleDialogMode, setCycleDialogMode] =
    useState<CycleDialogMode>("import");
  const [agriculturalCycles, setAgriculturalCycles] = useState<
    AgriculturalCycleRecord[]
  >([]);
  const [activeCycle, setActiveCycle] =
    useState<AgriculturalCycleRecord | null>(loadStoredActiveCycle);
  const [cycleLoading, setCycleLoading] = useState(false);
  const [cycleSaving, setCycleSaving] = useState(false);
  const [cycleRenamingId, setCycleRenamingId] = useState<string | null>(null);
  const [cycleError, setCycleError] = useState<string | null>(null);
  const [cycleExitNotice, setCycleExitNotice] = useState<string | null>(null);
  const [detectionsOpen, setDetectionsOpen] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [indicesOpen, setIndicesOpen] = useState(false);
  const [roiOpen, setRoiOpen] = useState(false);
  const [roiLibraryOpen, setRoiLibraryOpen] = useState(false);
  const [prescriptionOpen, setPrescriptionOpen] = useState(false);
  const [prescriptionConfigurationRequest, setPrescriptionConfigurationRequest] =
    useState(0);
  const [prescriptionError, setPrescriptionError] = useState<string | null>(null);
  const [rois, setRois] = useState<RoiRecord[]>([]);
  const [orthomosaics, setOrthomosaics] = useState<OrthomosaicRecord[]>([]);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [editingOrthomosaicId, setEditingOrthomosaicId] = useState<
    string | null
  >(null);
  const [editingCaptureDate, setEditingCaptureDate] = useState("");
  const [updatingOrthomosaicId, setUpdatingOrthomosaicId] = useState<
    string | null
  >(null);
  const [draggedOrthomosaicId, setDraggedOrthomosaicId] = useState<
    string | null
  >(null);
  const [dragOverOrthomosaicId, setDragOverOrthomosaicId] = useState<
    string | null
  >(null);
  const [reorderingOrthomosaics, setReorderingOrthomosaics] = useState(false);
  // El ROI de comparaciÃ³n se fija al abrir el dashboard para evitar que un
  // cambio posterior de selecciÃ³n afecte exportaciones o eliminaciones.
  const [roiAnalysisHistory, setRoiAnalysisHistory] = useState<
    RoiAnalysisRecord[]
  >([]);
  const [comparisonRoiId, setComparisonRoiId] = useState<string | null>(null);
  const map = useDashboardMap(mapElement, activeCycle?.id ?? null);
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

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!activeCycle) {
      window.localStorage.removeItem(ACTIVE_CYCLE_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(
      ACTIVE_CYCLE_STORAGE_KEY,
      JSON.stringify(activeCycle),
    );
  }, [activeCycle]);

  useEffect(() => {
    if (activeCycle) return;
    void openCycleDialog("entry");
  }, [activeCycle]);

  useEffect(() => {
    if (!cycleExitNotice) return;
    const timeout = window.setTimeout(() => setCycleExitNotice(null), 3600);
    return () => window.clearTimeout(timeout);
  }, [cycleExitNotice]);

  const loadAgriculturalCycles = async () => {
    setCycleLoading(true);
    try {
      const response = await dashboardApi.agriculturalCycles();
      setAgriculturalCycles(response.items);
      setCycleError(null);
    } catch (error) {
      setCycleError(
        error instanceof Error
          ? error.message
          : "No se pudieron consultar los ciclos agricolas.",
      );
    } finally {
      setCycleLoading(false);
    }
  };

  const openCycleDialog = async (mode: CycleDialogMode) => {
    setCycleDialogMode(mode);
    setCycleDialogOpen(true);
    await loadAgriculturalCycles();
  };

  const closeCycleDialog = () => {
    setCycleDialogOpen(false);
    setCycleExitNotice(null);
    setCycleError(null);
  };

  const openLibraryForCycle = async (cycle: AgriculturalCycleRecord) => {
    try {
      const response = await dashboardApi.orthomosaics(cycle.id);
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

  const requireActiveCycle = async (
    callback: () => void | Promise<void>,
    mode: CycleDialogMode = "entry",
  ) => {
    if (!activeCycle) {
      await openCycleDialog(mode);
      return;
    }
    await callback();
  };

  // Bibliotecas persistidas de vuelos y regiones.
  const openLibrary = async () => {
    if (!activeCycle) {
      await openCycleDialog("library");
      return;
    }
    await openLibraryForCycle(activeCycle);
  };
  const leaveActiveCycle = () => {
    const cycleName = activeCycle?.name ?? "ciclo agrÃ­cola";
    map.resetWorkspace();
    setLibraryOpen(false);
    setImportDialogOpen(false);
    setIndicesOpen(false);
    setRoiOpen(false);
    setRoiLibraryOpen(false);
    setDetectionsOpen(false);
    setPrescriptionOpen(false);
    setPrescriptionError(null);
    setSelectedIndex(null);
    setRois([]);
    setOrthomosaics([]);
    setRoiAnalysisHistory([]);
    setComparisonRoiId(null);
    setRoiComparisonOpen(false);
    setRoiAnalysisError(null);
    setCycleError(null);
    setActiveCycle(null);
    setCycleExitNotice(
      `Saliste de ${cycleName}. El mapa volviÃ³ a la vista inicial.`,
    );
  };
  const handleCycleSelected = async (cycle: AgriculturalCycleRecord) => {
    setCycleExitNotice(null);
    setActiveCycle(cycle);
    setCycleDialogOpen(false);
    setCycleError(null);
    if (cycleDialogMode === "import") {
      window.setTimeout(() => setImportDialogOpen(true), 0);
      return;
    }
    if (cycleDialogMode === "entry") {
      return;
    }
    await openLibraryForCycle(cycle);
  };
  const handleCycleCreated = async (payload: {
    name: string;
    crop_name?: string;
    start_date: string;
    end_date?: string;
    notes?: string;
  }) => {
    setCycleSaving(true);
    try {
      const response = await dashboardApi.createAgriculturalCycle(payload);
      setAgriculturalCycles((items) => [response.cycle, ...items]);
      setCycleExitNotice(null);
      setActiveCycle(response.cycle);
      setCycleDialogOpen(false);
      setCycleError(null);
      if (cycleDialogMode === "import") {
        window.setTimeout(() => setImportDialogOpen(true), 0);
      } else if (cycleDialogMode === "entry") {
        return;
      } else {
        await openLibraryForCycle(response.cycle);
      }
    } catch (error) {
      setCycleError(
        error instanceof Error
          ? error.message
          : "No se pudo crear el ciclo agricola.",
      );
    } finally {
      setCycleSaving(false);
    }
  };
  const handleCycleRename = async (
    cycle: AgriculturalCycleRecord,
    name: string,
  ) => {
    const nextName = name.trim();
    if (!nextName) {
      setCycleError("Captura un nombre valido para el ciclo agricola.");
      return;
    }
    setCycleRenamingId(cycle.id);
    try {
      const response = await dashboardApi.updateAgriculturalCycle(cycle.id, {
        name: nextName,
      });
      setAgriculturalCycles((items) =>
        items.map((item) => (item.id === cycle.id ? response.cycle : item)),
      );
      setActiveCycle((current) =>
        current?.id === cycle.id ? response.cycle : current,
      );
      setCycleError(null);
    } catch (error) {
      setCycleError(
        error instanceof Error
          ? error.message
          : "No se pudo renombrar el ciclo agricola.",
      );
    } finally {
      setCycleRenamingId(null);
    }
  };
  const beginOrthomosaicDateEdit = (record: OrthomosaicRecord) => {
    setEditingOrthomosaicId(record.id);
    setEditingCaptureDate(record.capture_date);
    setLibraryError(null);
  };
  const cancelOrthomosaicDateEdit = () => {
    setEditingOrthomosaicId(null);
    setEditingCaptureDate("");
  };
  const saveOrthomosaicDate = async (record: OrthomosaicRecord) => {
    if (!editingCaptureDate) {
      setLibraryError("Selecciona una fecha valida para el vuelo.");
      return;
    }
    setUpdatingOrthomosaicId(record.id);
    try {
      const response = await dashboardApi.updateOrthomosaic(record.id, {
        capture_date: editingCaptureDate,
      });
      setOrthomosaics((items) =>
        items.map((item) =>
          item.id === record.id ? response.orthomosaic : item,
        ),
      );
      cancelOrthomosaicDateEdit();
      setLibraryError(null);
    } catch (error) {
      setLibraryError(
        error instanceof Error
          ? error.message
          : "No se pudo actualizar la fecha del vuelo.",
      );
    } finally {
      setUpdatingOrthomosaicId(null);
    }
  };
  const moveOrthomosaic = async (sourceId: string, targetId: string) => {
    if (!activeCycle || sourceId === targetId || reorderingOrthomosaics) return;
    const previous = orthomosaics;
    const sourceIndex = previous.findIndex((item) => item.id === sourceId);
    const originalTargetIndex = previous.findIndex((item) => item.id === targetId);
    if (sourceIndex < 0 || originalTargetIndex < 0) return;

    const next = [...previous];
    const [moved] = next.splice(sourceIndex, 1);
    const targetIndex = next.findIndex((item) => item.id === targetId);
    next.splice(sourceIndex < originalTargetIndex ? targetIndex + 1 : targetIndex, 0, moved);

    setOrthomosaics(next);
    setReorderingOrthomosaics(true);
    setLibraryError(null);
    try {
      const response = await dashboardApi.reorderOrthomosaics(
        activeCycle.id,
        next.map((item) => item.id),
      );
      setOrthomosaics(response.items);
    } catch (error) {
      setOrthomosaics(previous);
      setLibraryError(
        error instanceof Error
          ? error.message
          : "No se pudo guardar el nuevo orden de los vuelos.",
      );
    } finally {
      setReorderingOrthomosaics(false);
      setDraggedOrthomosaicId(null);
      setDragOverOrthomosaicId(null);
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
      const response = await dashboardApi.rois(activeCycle?.id ?? null);
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
  /** Sustituye el historial local Ãºnicamente con la respuesta fresca del API. */
  const requestRoiAnalysisHistory = async (
    roiId: string,
    index: ComparisonIndex,
  ) => {
    const response = await dashboardApi.roiAnalyses(
      roiId,
      index,
      activeCycle?.id ?? null,
    );
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
        "Activa un anÃ¡lisis global o selecciona y recorta un ROI guardado antes de comparar vuelos.",
      );
      return;
    }
  };
  const editComparisonFlight = async (orthomosaicId: string) => {
    try {
      let record = orthomosaics.find((item) => item.id === orthomosaicId);
      if (!record && activeCycle) {
        const response = await dashboardApi.orthomosaics(activeCycle.id);
        setOrthomosaics(response.items);
        record = response.items.find((item) => item.id === orthomosaicId);
      }
      if (!record)
        throw new Error(
          "No se encontrÃ³ el ortomosaico seleccionado dentro del ciclo activo.",
        );
      await map.activateStoredOrtho(record);
      setSelectedIndex(null);
      setRoiComparisonOpen(false);
      setLibraryOpen(false);
      setRoiAnalysisError(null);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "No se pudo preparar el vuelo seleccionado para editarlo.";
      setRoiAnalysisError(message);
      throw error;
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
        "Selecciona un ROI, recÃ³rtalo y activa su NDVI antes de guardar estadÃ­sticas.",
      );
      return;
    }
    setRoiAnalysisSaving(true);
    try {
      const response = await dashboardApi.saveRoiAnalysis(
        roiId,
        orthomosaicId,
        activeCycle?.id ?? null,
        payload,
      );
      setComparisonIndex(payload.index);
      setComparisonRoiId(roiId);
      if (
        !analysisMatchesSavedStats(
          response.analysis,
          roiId,
          orthomosaicId,
          payload.index,
          payload.stats,
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
          : "No se pudieron guardar las estadÃ­sticas del ROI.",
      );
    } finally {
      setRoiAnalysisSaving(false);
    }
  };
  /**
   * Vuelve a consultar el servidor antes de construir el CSV. Los valores
   * numÃ©ricos se exportan con su precisiÃ³n original, no con la de la interfaz.
   */
  const exportRoiAnalysisHistory = async () => {
    const roiId = comparisonRoiId;
    if (!roiId) {
      setRoiAnalysisError(
        "No hay un ROI asociado a esta comparaciÃ³n. Cierra el modal y selecciona nuevamente la zona.",
      );
      return;
    }
    setRoiAnalysisExporting(true);
    setRoiAnalysisError(null);
    try {
      const items = await requestRoiAnalysisHistory(roiId, comparisonIndex);
      if (!items.length)
        throw new Error("No hay estadÃ­sticas vigentes para exportar.");
      const contents = buildRoiComparisonCsv(items);
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
          : "No se pudieron exportar las estadÃ­sticas actualizadas.",
      );
    } finally {
      setRoiAnalysisExporting(false);
    }
  };
  /** Ejecuta la eliminaciÃ³n confirmada y sincroniza la colecciÃ³n afectada. */
  const confirmDeletion = async () => {
    if (!deleteTarget) return;
    const target = deleteTarget;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      if (target.kind === "cycle") {
        await dashboardApi.deleteAgriculturalCycle(target.record.id);
        setAgriculturalCycles((items) =>
          items.filter((item) => item.id !== target.record.id),
        );
        if (activeCycle?.id === target.record.id) {
          leaveActiveCycle();
          setCycleDialogOpen(true);
          setCycleExitNotice(
            `Se eliminÃ³ ${target.record.name} y todo su contenido asociado.`,
          );
        }
      } else if (target.kind === "orthomosaic") {
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
            "El ROI ya no estÃ¡ seleccionado. Vuelve a abrir la comparaciÃ³n.",
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
              ? `La estadÃ­stica fue eliminada, pero no se pudo verificar el historial: ${error.message}`
              : "La estadÃ­stica fue eliminada, pero no se pudo verificar el historial actualizado.",
          );
        }
      }
      setDeleteTarget(null);
    } catch (error) {
      setDeleteError(
        error instanceof Error
          ? error.message
          : "No se pudo completar la eliminaciÃ³n.",
      );
    } finally {
      setRoiAnalysisDeletingId(null);
      setDeleteBusy(false);
    }
  };

  const deleteDialogContent = getDeleteDialogContent(deleteTarget);

  /** Convierte la posiciÃ³n horizontal del puntero al porcentaje del swipe. */
  const moveDivider = (event: React.PointerEvent) => {
    const rect = divider.current?.parentElement?.getBoundingClientRect();

    if (rect) {
      map.setSwipePosition(((event.clientX - rect.left) / rect.width) * 100);
    }
  };

  const openPrescription = () => {
    const indexName = selectedIndex ?? "NDVI";
    const ready =
      indexName === "NDVI"
        ? Boolean(map.ndviAnalysis.roiResponse)
        : map.indexAnalyses.some((analysis) => analysis.name === indexName);
    setPrescriptionError(
      map.state.orthomosaicId && ready
        ? null
        : "Selecciona un ROI, recÃ³rtalo y abre su histograma NDVI antes de generar la prescripciÃ³n.",
    );
    setPrescriptionOpen(true);
  };

  const activePrescriptionDisplayRange = getActivePrescriptionDisplayRange(
    selectedIndex,
    map.ndviAnalysis,
    map.indexAnalyses,
  );

  const generatePrescription = async (
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
  ) => {
    const indexName = selectedIndex ?? "NDVI";
    setPrescriptionError(null);
    try {
      return await map.generateZoning(
        indexName,
        zoneCount,
        cellSizeM,
        gridAngleDeg,
      );
    } catch (error) {
      setPrescriptionError(
        error instanceof Error
          ? error.message
          : "No se pudo generar el mapa de prescripciÃ³n.",
        );
    }
  };

  const generateZoning = async (
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
    classificationMethod: "quantiles" | "equal_intervals" | "manual",
    cellValueMode: "mean" | "min" | "max",
    detailLevel: number,
    manualBreaks?: number[],
  ) => {
    const indexName = selectedIndex ?? "NDVI";
    setPrescriptionError(null);
    try {
      return await map.generateZoning(
        indexName,
        zoneCount,
        cellSizeM,
        gridAngleDeg,
        classificationMethod,
        cellValueMode,
        detailLevel,
        manualBreaks,
      );
    } catch (error) {
      setPrescriptionError(
        error instanceof Error
          ? error.message
          : "No se pudo generar la zonificaciÃ³n NDVI.",
      );
      throw error;
    }
  };

  const previewZoning = async (
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
    classificationMethod: "quantiles" | "equal_intervals" | "manual",
    cellValueMode: "mean" | "min" | "max",
    detailLevel: number,
    manualBreaks?: number[],
    allowExisting = false,
  ) => {
    const indexName = selectedIndex ?? "NDVI";
    try {
      await map.previewZoning(
        indexName,
        zoneCount,
        cellSizeM,
        gridAngleDeg,
        classificationMethod,
        cellValueMode,
        detailLevel,
        manualBreaks,
        allowExisting,
      );
      setPrescriptionError(null);
    } catch (error) {
      setPrescriptionError(
        error instanceof Error
          ? error.message
          : "No se pudo previsualizar la reticula.",
      );
    }
  };

  const generatePrescriptionV2 = async (
    zoneCount: number,
    cellSizeM: number,
    gridAngleDeg: number,
    classificationMethod: "quantiles" | "equal_intervals" | "manual",
    cellValueMode: "mean" | "min" | "max",
    detailLevel: number,
    manualBreaks?: number[],
    doses?: number[],
  ) => {
    const indexName = selectedIndex ?? "NDVI";
    setPrescriptionError(null);
    try {
      const result = await map.generatePrescription(
        indexName,
        zoneCount,
        cellSizeM,
        gridAngleDeg,
        classificationMethod,
        cellValueMode,
        detailLevel,
        manualBreaks,
        doses,
      );
      return result;
    } catch (error) {
      setPrescriptionError(
        error instanceof Error
          ? error.message
          : "No se pudo generar el mapa de prescripciÃ³n.",
      );
      throw error;
    }
  };

  return (
    <main className="map-shell">
      <div ref={mapElement} className="map" />
      <ActionBar
        state={map.state}
        cropAvailable={map.cropAvailable}
        cropExporting={map.cropExporting}
        onExportCrop={(variant) => void map.exportCrop(variant)}
        onOrthoLibrary={() => void requireActiveCycle(openLibrary, "library")}
        onOpenIndices={() =>
          void requireActiveCycle(
            async () => setIndicesOpen(true),
            "entry",
          )
        }
        onOpenRoi={() =>
          void requireActiveCycle(
            async () => setRoiOpen(true),
            "entry",
          )
        }
        onOpenDetections={() =>
          void requireActiveCycle(
            async () => setDetectionsOpen(true),
            "entry",
          )
        }
        onLabels={() =>
          void requireActiveCycle(async () => map.toggleLabels(), "entry")
        }
        onImport={() =>
          void requireActiveCycle(
            async () => setImportDialogOpen(true),
            "import",
          )
        }
      />
      <AgriculturalCycleDialog
        open={cycleDialogOpen}
        loading={cycleLoading}
        busy={cycleSaving}
        error={cycleError}
        cycles={agriculturalCycles}
        activeCycleId={activeCycle?.id ?? null}
        mode={cycleDialogMode}
        renamingCycleId={cycleRenamingId}
        onClose={closeCycleDialog}
        onSelect={(cycle) => void handleCycleSelected(cycle)}
        onCreate={(payload) => void handleCycleCreated(payload)}
        onRename={(cycle, name) => void handleCycleRename(cycle, name)}
        onDelete={(cycle) => {
          setDeleteError(null);
          setDeleteTarget({ kind: "cycle", record: cycle });
        }}
      />
      <PrescriptionDialog
        open={prescriptionOpen}
        configurationRequestId={prescriptionConfigurationRequest}
        indexName={selectedIndex ?? "NDVI"}
        displayRange={activePrescriptionDisplayRange}
        busy={map.zoningLoading || map.prescriptionLoading}
        error={prescriptionError}
        zoning={map.zoning}
        prescription={map.prescription}
        prescriptionAreaReady={map.prescriptionAreaReady}
        onDrawArea={() => {
          setPrescriptionOpen(false);
          setPrescriptionError(null);
          map.drawPrescriptionArea(() => setPrescriptionOpen(true));
        }}
        onGenerateZoning={generateZoning}
        onPreviewZoning={previewZoning}
        onLiveRotationChange={map.setLivePrescriptionRotation}
        onClearPreview={map.clearZoningPreview}
        onGeneratePrescription={generatePrescriptionV2}
        onClear={() => {
          map.clearPrescription();
          setPrescriptionOpen(false);
          setPrescriptionError(null);
        }}
        onClose={() => {
          if (!(map.zoningLoading || map.prescriptionLoading)) setPrescriptionOpen(false);
        }}
      />
      {map.state.detectionEditMode && (
        <div className="detection-edit-banner" role="status">
          <IconMapPin aria-hidden="true" />
          <span>
            <strong>EdiciÃ³n de detecciones</strong>
            <small>
              {map.state.detectionEditMode === "add"
                ? "Haz clic en el mapa para colocar la detecciÃ³n."
                : map.state.detectionEditMode === "delete-one"
                  ? "Pulsa la detecciÃ³n que deseas eliminar."
                  : "Dibuja un rectÃ¡ngulo sobre las detecciones que deseas eliminar."}
            </small>
          </span>
          <button
            type="button"
            onClick={map.cancelDetectionEdit}
            aria-label="Cancelar ediciÃ³n"
          >
            <IconX aria-hidden="true" />
          </button>
        </div>
      )}
      <ImportDialog
        open={importDialogOpen}
        onClose={() => setImportDialogOpen(false)}
        onFile={(file, sensor) => {
          if (!activeCycle) {
            setImportDialogOpen(false);
            void openCycleDialog("import");
            return;
          }
          void map.importOrtho(file, sensor, activeCycle.id);
        }}
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
        onManage={() =>
          void requireActiveCycle(openRoiLibrary, "entry")
        }
      />
      <MapViewRoiLibraryDialog
        open={roiLibraryOpen}
        rois={rois}
        selectedRoiIds={map.state.selectedRoiIds}
        onClose={() => setRoiLibraryOpen(false)}
        onSelectRoi={map.selectRoi}
        onDeleteRoi={(roi) => {
          setDeleteError(null);
          setDeleteTarget({ kind: "roi", record: roi });
        }}
      />
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
                  <span className="import-eyebrow">ANÃLISIS ESPECTRAL</span>
                  <h2 id="indices-title">Ãndices de vegetaciÃ³n</h2>
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
              Ã­ndices visibles al mismo tiempo.
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
                        {active ? "Ãndice visible" : "Ãndice oculto"}
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
              Ocultar todos los Ã­ndices
            </button>
          </section>
        </div>
      )}
      <MapViewOrthomosaicLibraryDialog
        open={libraryOpen}
        activeCycle={activeCycle}
        orthomosaics={orthomosaics}
        libraryError={libraryError}
        reorderingOrthomosaics={reorderingOrthomosaics}
        draggedOrthomosaicId={draggedOrthomosaicId}
        dragOverOrthomosaicId={dragOverOrthomosaicId}
        editingOrthomosaicId={editingOrthomosaicId}
        editingCaptureDate={editingCaptureDate}
        updatingOrthomosaicId={updatingOrthomosaicId}
        activeOrthomosaicId={map.state.orthomosaicId}
        rgbVisible={map.state.rgb}
        onClose={() => setLibraryOpen(false)}
        onLeaveActiveCycle={leaveActiveCycle}
        onMoveOrthomosaic={moveOrthomosaic}
        onDragOverOrthomosaicIdChange={setDragOverOrthomosaicId}
        onDraggedOrthomosaicIdChange={setDraggedOrthomosaicId}
        onClearLibraryError={() => setLibraryError(null)}
        onEditingCaptureDateChange={setEditingCaptureDate}
        onSaveOrthomosaicDate={saveOrthomosaicDate}
        onCancelOrthomosaicDateEdit={cancelOrthomosaicDateEdit}
        onBeginOrthomosaicDateEdit={beginOrthomosaicDateEdit}
        onFitRgb={map.fitRgb}
        onActivateStoredOrtho={map.activateStoredOrtho}
        onDeleteOrthomosaic={(record) => {
          setDeleteError(null);
          setDeleteTarget({ kind: "orthomosaic", record });
        }}
      />
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
        onNdviEqualizationChange={map.setNdviEqualization}
        onNdviFillModeChange={map.setNdviFillMode}
        onIndexRangeChange={map.setIndexRange}
        onIndexEqualizationChange={map.setIndexEqualization}
        onIndexFillModeChange={map.setIndexFillMode}
        ndviVisible={map.state.ndvi}
        onToggleNdvi={() => void map.toggleNdvi()}
        onToggleIndex={map.toggleIndexLayer}
        onHideNdvi={() => {
          map.hideNdvi();
          setSelectedIndex(null);
        }}
        onHideIndex={(name) => {
          map.hideIndex(name);
          setSelectedIndex((current) => (current === name ? null : current));
        }}
        canSaveRoiAnalysis={Boolean(
          selectedIndex &&
          map.state.selectedRoiId &&
            map.state.orthomosaicId &&
            activeRoiIndexReady,
        )}
        roiAnalysisSaving={roiAnalysisSaving}
        onSaveRoiAnalysis={(payload) => void saveRoiAnalysis(payload)}
        onOpenRoiComparison={(index) => void loadRoiAnalysisHistory(index)}
        prescriptionMode={map.prescription ? "prescription" : map.zoning ? "zoning" : "idle"}
        prescriptionLoading={map.zoningLoading || map.prescriptionLoading}
        onOpenPrescription={openPrescription}
        onExitPrescription={() => {
          map.clearPrescription();
          setPrescriptionOpen(false);
          setPrescriptionError(null);
        }}
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
        activeOrthomosaicId={map.state.orthomosaicId}
        onRefresh={() =>
          comparisonRoiId
            ? refreshRoiAnalysisHistory(comparisonRoiId, comparisonIndex)
                .then(() => undefined)
                .catch(() => undefined)
            : Promise.resolve()
        }
        onExport={() => void exportRoiAnalysisHistory()}
        onEditFlight={editComparisonFlight}
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
      {cycleExitNotice && (
        <div className="cycle-exit-toast" role="status" aria-live="polite">
          <IconCheck aria-hidden="true" />
          <span>{cycleExitNotice}</span>
        </div>
      )}
      {(map.prescription || map.zoning) && (
        <PrescriptionLegend
          response={map.prescription ?? map.zoning!}
          onClose={map.clearPrescription}
          onConfigure={() => {
            setPrescriptionConfigurationRequest((current) => current + 1);
            setPrescriptionOpen(true);
          }}
        />
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



