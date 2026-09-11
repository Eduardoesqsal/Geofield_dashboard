// @ts-nocheck
import { useCallback } from "react";
import L from "leaflet";
import {
  backendUrl,
  dashboardApi,
  type OrthomosaicRecord,
  type OrthoSensor,
} from "../services/api";
import {
  createEmptyNdviAnalysis,
  createInitialMapState,
  modeFromSensor,
} from "./useDashboardMap.helpers";
import { mountStoredOrthomosaic, resetOrthomosaicArtifacts } from "./useDashboardMap.orthomosaic";
import { clearSpectralLayers } from "./useDashboardMap.spectral";

export function useDashboardMapWorkspace(ctx: any) {
  const {
    activeCropIdRef,
    boundsRef,
    cancelDetectionEdit,
    clearClassificationFill,
    clearClassificationGrid,
    clearPrescription,
    clearRoiSelection,
    clearTileClip,
    cropControlRef,
    cropTileRef,
    indexRefs,
    labelsEnabledRef,
    labelsRef,
    mapRef,
    ndviRef,
    ndviResponseRef,
    ndviTileRef,
    orthoRef,
    ratioRef,
    restoreRoiSelection,
    roiIndexResponsesRef,
    roiLayersRef,
    selectedRoiRef,
    selectedRoisRef,
    setCropExporting,
    setFilteredTreeData,
    setIndexAnalyses,
    setNdviAnalysis,
    setState,
    setTreeData,
    state,
    swipeEnabledRef,
    syncSpectralClip,
    treeDataRef,
    treeRef,
    uploadedRgbRef,
  } = ctx;

  /** Alterna la visibilidad del ortomosaico base y recupera su extensiÃ³n. */
  const fitRgb = useCallback(() => {
    const map = mapRef.current;
    if (!map || !orthoRef.current) return;
    if (state.rgb) {
      uploadedRgbRef.current?.remove();
      orthoRef.current.remove();
      setState((current) => ({ ...current, rgb: false }));
      return;
    }
    clearTileClip();
    roiIndexResponsesRef.current = null;
    uploadedRgbRef.current?.addTo(map);
    orthoRef.current.addTo(map);
    setState((current) => ({ ...current, rgb: true }));
    if (boundsRef.current) map.fitBounds(boundsRef.current);
  }, [clearTileClip, state.rgb]);

  /** Activa un vuelo persistido y elimina cualquier anÃ¡lisis del vuelo anterior. */
  const activateStoredOrtho = useCallback(
    async (record: OrthomosaicRecord) => {
      const persistentRoiSelections = Array.from(
        selectedRoisRef.current.entries(),
      );
      try {
        await dashboardApi.activateOrthomosaic(record.id);
        const result = await dashboardApi.bounds(record.id);
        clearPrescription();
        boundsRef.current = L.latLngBounds(result.bounds);
        clearRoiSelection();
        setIndexAnalyses([]);
        setNdviAnalysis(createEmptyNdviAnalysis());
        if (
          !mountStoredOrthomosaic({
            backendUrl,
            bounds: result.bounds,
            mapRef,
            orthomosaicId: record.id,
            orthoRef,
            tileVersion: result.tile_version,
          })
        )
          return;
        setState((current) => ({
          ...current,
          orthomosaicId: record.id,
          sensor: record.sensor_type as OrthoSensor,
          orthoMode: modeFromSensor(record.sensor_type),
          rgb: true,
          ndvi: false,
          vari: false,
          exg: false,
          roiSelected: false,
          selectedRoiId: null,
          selectedRoiIds: [],
          error: null,
        }));
        restoreRoiSelection(persistentRoiSelections);
      } catch (error) {
        setState((current) => ({
          ...current,
          error:
            error instanceof Error
              ? error.message
              : "No se pudo activar el ortomosaico.",
        }));
      }
    },
    [clearPrescription, clearRoiSelection, restoreRoiSelection],
  );

  /** Limita y aplica el divisor comparativo a todas las capas espectrales. */
  const setSwipePosition = useCallback((position: number) => {
    const next = Math.max(2, Math.min(98, position));
    ratioRef.current = next / 100;
    setState((current) => ({ ...current, swipePosition: next }));
    syncSpectralClip();
  }, [syncSpectralClip]);

  /** Activa o elimina el recorte visual del divisor sin destruir las capas. */
  const toggleSwipe = useCallback(() => {
    setState((current) => {
      const enabled = !current.swipe;
      swipeEnabledRef.current = enabled;
      swipeEnabledRef.current = enabled;
      return { ...current, swipe: enabled };
    });
    syncSpectralClip();
  }, [syncSpectralClip]);

  const exportCrop = useCallback(async (variant: "visual" | "analytical") => {
    const cropId = activeCropIdRef.current;
    if (!cropId) {
      setState((current) => ({
        ...current,
        error: "Primero genera un recorte del ortomosaico.",
      }));
      return;
    }
    setCropExporting(true);
    try {
      const { blob, filename } = await dashboardApi.downloadCrop(cropId, variant);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
      setState((current) => ({ ...current, error: null }));
    } catch (error) {
      setState((current) => ({
        ...current,
        error:
          error instanceof Error
            ? error.message
            : "No se pudo descargar el recorte.",
      }));
    } finally {
      setCropExporting(false);
    }
  }, []);

  /** Limpia por completo el contexto visible del mapa al salir de un ciclo. */
  const resetWorkspace = useCallback(() => {
    cancelDetectionEdit();
    mapRef.current?.pm?.disableDraw();
    clearRoiSelection();
    clearSpectralLayers({ indexRefs, ndviRef, ndviTileRef });
    clearPrescription();
    roiLayersRef.current.forEach((layer) => layer.remove());
    roiLayersRef.current.clear();
    cropTileRef.current?.remove();
    cropTileRef.current = undefined;
    uploadedRgbRef.current?.remove();
    uploadedRgbRef.current = undefined;
    orthoRef.current?.remove();
    orthoRef.current = undefined;
    clearClassificationFill();
    clearClassificationGrid();
    boundsRef.current = undefined;
    labelsEnabledRef.current = false;
    swipeEnabledRef.current = false;
    ratioRef.current = 0.5;
    resetOrthomosaicArtifacts({
      cropControlRef,
      indexRefs,
      labelsRef,
      ndviRef,
      ndviResponseRef,
      ndviTileRef,
      roiIndexResponsesRef,
      selectedRoiRef,
      selectedRoisRef,
      treeDataRef,
      treeRef,
    });
    setTreeData(null);
    setFilteredTreeData(null);
    setNdviAnalysis(createEmptyNdviAnalysis());
    setIndexAnalyses([]);
    setState(createInitialMapState());
    mapRef.current?.setView([23.6345, -102.5528], 5);
  }, [
    cancelDetectionEdit,
    clearClassificationFill,
    clearClassificationGrid,
    clearPrescription,
    clearRoiSelection,
  ]);
  return {
    activateStoredOrtho,
    exportCrop,
    fitRgb,
    resetWorkspace,
    setSwipePosition,
    toggleSwipe,
  };
}


