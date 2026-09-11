// @ts-nocheck
import { useCallback } from "react";
import L from "leaflet";
import type { Feature } from "geojson";
import { backendUrl, dashboardApi } from "../services/api";
import { ndviStats } from "../utils/ndvi";
import { buildRoiSelection, createEmptyNdviAnalysis } from "./useDashboardMap.helpers";
import { applyRoiCropLayer, clearRoiArtifacts, restoreBaseOrthoLayer } from "./useDashboardMap.roi";

export function useDashboardMapRoi(ctx: any) {
  const {
    activeCropGeometryRef,
    activeCropIdRef,
    activeCropRing,
    clearPrescription,
    clearPrescriptionArea,
    cropControlRef,
    cropTileRef,
    indexRefs,
    mapRef,
    ndviRangeRef,
    ndviRef,
    ndviResponseRef,
    ndviTileRef,
    orthoRef,
    roiIndexResponsesRef,
    roiLayersRef,
    selectedRoiRef,
    selectedRoisRef,
    setCropAvailable,
    setIndexAnalyses,
    setNdviAnalysis,
    setState,
    syncSpectralClip,
    uploadedRgbRef,
  } = ctx;

  /** Recalcula el recorte CSS cuando el mapa cambia de zoom o posiciÃ³n. */
  const updateTileClip = useCallback(() => {
    const map = mapRef.current;
    const layer = orthoRef.current;
    const container = layer?.getContainer();
    const ring = activeCropRing();
    if (!map || !container || !ring?.length) {
      syncSpectralClip();
      return;
    }
    const points = ring.map(([longitude, latitude]) =>
      map.latLngToLayerPoint([latitude, longitude]),
    );
    container.style.clipPath = `polygon(${points.map((point) => `${point.x}px ${point.y}px`).join(", ")})`;
    syncSpectralClip();
  }, [activeCropRing, syncSpectralClip]);

  /** Elimina tiles de recorte y cualquier clip aplicado a la capa base. */
  const clearTileClip = useCallback(() => {
    activeCropGeometryRef.current = null;
    activeCropIdRef.current = null;
    cropTileRef.current?.remove();
    cropTileRef.current = undefined;
    const container = orthoRef.current?.getContainer();
    if (container) container.style.clipPath = "";
    syncSpectralClip();
    setCropAvailable(false);
  }, [syncSpectralClip]);

  /** Diferencia visualmente polÃ­gonos seleccionados y disponibles. */
  const styleRoiLayer = useCallback((roiId: string, selected: boolean) => {
    const layer = roiLayersRef.current.get(roiId);
    if (!layer) return;
    const style = selected
      ? { color: "#ffffff", weight: 3, fillColor: "#6d9276", fillOpacity: 0.16 }
      : {
          color: "#ffffff",
          weight: 2,
          fillColor: "#ff3b30",
          fillOpacity: 0.08,
        };
    if (layer instanceof L.GeoJSON) layer.setStyle(style);
    else
      (
        layer as L.Path & { setStyle?: (options: L.PathOptions) => void }
      ).setStyle?.(style);
  }, []);

  /**
   * Restablece selecciÃ³n, recorte e Ã­ndices ROI para que el mapa vuelva al
   * comportamiento global sin conservar resultados de una geometrÃ­a anterior.
   */
  const clearRoiSelection = useCallback(() => {
    clearPrescriptionArea();
    selectedRoisRef.current.forEach((_geojson, roiId) =>
      styleRoiLayer(roiId, false),
    );
    clearRoiArtifacts({
      clearTileClip,
      cropControlRef,
      indexRefs,
      ndviRangeRef,
      ndviRef,
      ndviResponseRef,
      ndviTileRef,
      orthoRef,
      roiIndexResponsesRef,
      selectedRoiRef,
      selectedRoisRef,
    });
    restoreBaseOrthoLayer({ mapRef, orthoRef });

    setNdviAnalysis(createEmptyNdviAnalysis());
    setIndexAnalyses([]);
    setState((current) => ({
      ...current,
      rgb: Boolean(orthoRef.current),
      ndvi: false,
      vari: false,
      exg: false,
      roiSelected: false,
      selectedRoiId: null,
      selectedRoiIds: [],
      error: null,
    }));
  }, [clearPrescriptionArea, clearTileClip, styleRoiLayer]);

  /** Solicita el recorte ROI y deja NDWI/NDRE para cÃ¡lculo explÃ­cito. */
  const analyzeRoi = useCallback(async (geojson: unknown) => {
    clearPrescriptionArea();
    const [ndviResponse, crop] = await Promise.all([
      dashboardApi.roi(geojson),
      dashboardApi.cropTiles(geojson),
    ]);
    const ndviZoneStats = ndviStats(ndviResponse);
    ndviResponseRef.current = ndviResponse;
    roiIndexResponsesRef.current = { NDVI: ndviResponse };
    activeCropGeometryRef.current = geojson;
    ndviRangeRef.current = {
      min: ndviZoneStats.min,
      max: ndviZoneStats.max,
      equalized: false,
      fillMode: "transparent",
      values: ndviZoneStats.values,
    };
    setNdviAnalysis((current) => ({
      ...current,
      response: null,
      stats: current.stats,
      roiResponse: null,
      roiStats: current.roiStats,
      minimum: ndviZoneStats.min,
      maximum: ndviZoneStats.max,
      equalized: false,
      fillMode: "transparent",
    }));
    setIndexAnalyses([]);
    ndviRef.current?.remove();
    ndviTileRef.current?.remove();
    ndviTileRef.current = undefined;
    indexRefs.current.forEach((layer) => layer.remove());
    indexRefs.current.clear();
    applyRoiCropLayer({
      activeCropIdRef,
      backendUrl,
      bounds: crop.bounds,
      cropId: crop.crop_id,
      tileVersion: crop.tile_version,
      cropTileRef,
      mapRef,
      orthoRef,
      uploadedRgbRef,
    });
    setCropAvailable(true);
    setState((current) => ({
      ...current,
      rgb: false,
      ndvi: false,
      error: null,
    }));
  }, [clearPrescriptionArea]);

  /** Ejecuta el anÃ¡lisis para la colecciÃ³n ROI construida actualmente. */
  const cropSelectedRoi = useCallback(async () => {
    if (!selectedRoiRef.current) {
      setState((current) => ({
        ...current,
        error: "Selecciona una regiÃ³n de interÃ©s antes de recortar.",
      }));
      return;
    }
    try {
      await analyzeRoi(selectedRoiRef.current);
      cropControlRef.current?.remove();
      cropControlRef.current = undefined;
    } catch (error) {
      setState((current) => ({
        ...current,
        error:
          error instanceof Error
            ? error.message
            : "No se pudo recortar el ortomosaico.",
      }));
    }
  }, [analyzeRoi]);

  /**
   * Combina todos los ROI seleccionados en un FeatureCollection y coloca una
   * Ãºnica tijera sobre los lÃ­mites conjuntos.
   */
  const refreshRoiSelection = useCallback(() => {
    clearPrescription();
    const selections = Array.from(selectedRoisRef.current.entries());
    const { collection, roiIds } = buildRoiSelection(selections);
    const { features } = collection;
    selectedRoiRef.current = features.length ? collection : null;
    const map = mapRef.current;
    cropControlRef.current?.remove();
    cropControlRef.current = undefined;
    if (map && features.length) {
      const bounds = L.geoJSON(collection).getBounds();
      if (bounds.isValid()) {
        cropControlRef.current = L.marker(bounds.getCenter(), {
          interactive: true,
          keyboard: true,
          title: `Recortar ${features.length} ${features.length === 1 ? "zona" : "zonas"}`,
          icon: L.divIcon({
            className: "roi-crop-control",
            html: '<span aria-hidden="true">âœ‚</span>',
            iconSize: [38, 38],
            iconAnchor: [19, 19],
          }),
        }).addTo(map);
        cropControlRef.current.on("click", () => {
          void cropSelectedRoi();
        });
      }
    }
    setState((current) => ({
      ...current,
      roiSelected: features.length > 0,
      selectedRoiId: roiIds.length === 1 ? roiIds[0] : null,
      selectedRoiIds: roiIds,
      error: features.length
        ? `${features.length} ${features.length === 1 ? "zona seleccionada" : "zonas seleccionadas"}. Haz clic en la tijera para recortar.`
        : null,
    }));
  }, [clearPrescription, cropSelectedRoi]);

  /** Restaura geometrÃ­as persistentes despuÃ©s de cambiar el vuelo activo. */
  const restoreRoiSelection = useCallback(
    (selections: Array<[string, unknown]>) => {
      selections.forEach(([id, geojson]) => {
        selectedRoisRef.current.set(id, geojson);
        if (id !== "__temporary__") styleRoiLayer(id, true);
      });
      refreshRoiSelection();
    },
    [refreshRoiSelection, styleRoiLayer],
  );

  /** Alterna un ROI sin reemplazar los demÃ¡s y descarta anÃ¡lisis obsoletos. */
  const selectRoi = useCallback(
    (geojson: unknown, roiId: string | null = null) => {
      const selectionId = roiId ?? "__temporary__";
      const alreadySelected = selectedRoisRef.current.has(selectionId);
      if (alreadySelected) {
        selectedRoisRef.current.delete(selectionId);
        if (roiId) styleRoiLayer(roiId, false);
      } else {
        const map = mapRef.current;
        if (map && roiId && !roiLayersRef.current.has(roiId)) {
          const geometryLayer = L.geoJSON(geojson as Feature, {
            style: {
              color: "#ffffff",
              weight: 3,
              fillColor: "#6d9276",
              fillOpacity: 0.16,
            },
          }).addTo(map);
          roiLayersRef.current.set(roiId, geometryLayer);
        }
        selectedRoisRef.current.set(selectionId, geojson);
        if (roiId) styleRoiLayer(roiId, true);
      }
      const nextSelections = Array.from(selectedRoisRef.current.entries());
      if (activeCropIdRef.current || roiIndexResponsesRef.current) {
        clearRoiSelection();
        nextSelections.forEach(([id, selectedGeojson]) => {
          selectedRoisRef.current.set(id, selectedGeojson);
          if (id !== "__temporary__") styleRoiLayer(id, true);
        });
      }
      refreshRoiSelection();
    },
    [clearRoiSelection, refreshRoiSelection, styleRoiLayer],
  );

  /** Elimina la capa exacta y conserva cualquier otra selecciÃ³n activa. */
  const removeRoiPolygon = useCallback(
    (roiId: string) => {
      const wasSelected = selectedRoisRef.current.delete(roiId);
      const remainingSelections = Array.from(selectedRoisRef.current.entries());
      roiLayersRef.current.get(roiId)?.remove();
      roiLayersRef.current.delete(roiId);
      if (!wasSelected) return;
      clearRoiSelection();
      remainingSelections.forEach(([id, geojson]) => {
        selectedRoisRef.current.set(id, geojson);
        if (id !== "__temporary__") styleRoiLayer(id, true);
      });
      refreshRoiSelection();
    },
    [clearRoiSelection, refreshRoiSelection, styleRoiLayer],
  );



  return {
    analyzeRoi,
    clearRoiSelection,
    clearTileClip,
    cropSelectedRoi,
    refreshRoiSelection,
    removeRoiPolygon,
    restoreRoiSelection,
    selectRoi,
    styleRoiLayer,
    updateTileClip,
  };
}

