// @ts-nocheck
import { useCallback } from "react";
import L from "leaflet";
import type { Feature } from "geojson";
import { dashboardApi } from "../services/api";
import type { TreeCollection, TreeFeature } from "../types/geo";
import {
  diameterOf,
  normalizeTreeCollection,
  sizeOf,
  treeSizeColors,
  type VisibleTreeSize,
} from "../utils/tree";
import { parseDetectionFiles, parseImportFile } from "../utils/importFormats";
import { ndviStats } from "../utils/ndvi";
import { buildGeometryPopupHtml, filterVisibleTrees } from "./useDashboardMap.helpers";
import type { TreeDisplayMode } from "./useDashboardMap";

export function useDashboardMapTreeActions(ctx: any) {
  const {
    activeCropGeometryRef,
    activeCycleId,
    addDetectionClickRef,
    boundsRef,
    cancelDetectionEdit,
    clearPrescription,
    commitTreeCollection,
    deleteDetectionHandlersRef,
    detectionEditModeRef,
    diameterRangeRef,
    labelsEnabledRef,
    labelsRef,
    mapRef,
    ndviAnalysis,
    ndviRangeRef,
    ndviResponseRef,
    ndviTileRef,
    prescriptionDrawCompleteRef,
    rawTreeDataRef,
    refreshLabels,
    renderNdvi,
    renderTreeLayer,
    roiLayersRef,
    selectRoi,
    setFilteredTreeData,
    setNdviAnalysis,
    setState,
    setTreeData,
    state,
    syncTreeLayerVisibility,
    treeDataRef,
    treeDisplayModeRef,
    treeRef,
    visibleTreeSizesRef,
  } = ctx;

  const toggleTrees = useCallback(() => {
    const map = mapRef.current;
    if (!map || !treeRef.current) return;
    if (map.hasLayer(treeRef.current)) {
      map.removeLayer(treeRef.current);
      labelsRef.current?.remove();
      setState((current) => ({ ...current, trees: false, labels: false }));
    } else {
      treeRef.current.addTo(map);
      setState((current) => ({ ...current, trees: true }));
    }
  }, []);

  /** Habilita en Geoman una Ãºnica operaciÃ³n de dibujo poligonal. */
  const drawRoi = useCallback(() => {
    if (state.orthoMode !== "multispectral") {
      setState((current) => ({
        ...current,
        error:
          "Carga un ortomosaico multiespectral antes de dibujar una regiÃ³n de interÃ©s.",
      }));
      return;
    }
    const map = mapRef.current;
    if (!map) return;
    map.pm?.enableDraw("Polygon");
  }, [state.orthoMode]);

  /** Dibuja un limite temporal usado solo por la zonificacion/prescripcion. */
  const drawPrescriptionArea = useCallback(
    (onComplete: () => void) => {
      const map = mapRef.current;
      if (!map || !activeCropGeometryRef.current || !ndviAnalysis.roiResponse) {
        setState((current) => ({
          ...current,
          error: "Primero recorta un ROI y abre su histograma NDVI.",
        }));
        return;
      }
      clearPrescription();
      prescriptionDrawCompleteRef.current = onComplete;
      map.pm?.enableDraw("Polygon", {
        pathOptions: {
          color: "#244f32",
          weight: 2,
          dashArray: "6 4",
          fillColor: "#65a36f",
          fillOpacity: 0.12,
        },
      });
      setState((current) => ({
        ...current,
        error: "Dibuja en el mapa el poligono que delimita la zona de cultivo.",
      }));
    },
    [clearPrescription, ndviAnalysis.roiResponse],
  );

  /** Importa, guarda y selecciona de forma aditiva todas las geometrÃ­as vÃ¡lidas. */
  const importRoi = useCallback(
    async (files: File[]) => {
      try {
        if (!activeCycleId)
          throw new Error(
            "Selecciona un ciclo agrÃ­cola antes de importar una regiÃ³n de interÃ©s.",
          );
        if (state.orthoMode !== "multispectral")
          throw new Error(
            "Carga un ortomosaico multiespectral antes de analizar una regiÃ³n de interÃ©s.",
          );
        const collections = await Promise.all(
          files.map((file) => parseImportFile(file)),
        );
        const features = collections
          .flatMap((collection) => collection.features)
          .filter(
            (feature) =>
              feature.geometry.type === "Polygon" ||
              feature.geometry.type === "MultiPolygon",
          );
        if (!features.length)
          throw new Error(
            "La geometrÃ­a importada debe contener al menos un polÃ­gono.",
          );
        const map = mapRef.current;
        if (!map) return;
        const roi = { type: "FeatureCollection" as const, features };
        const layer = L.geoJSON(roi, {
          style: {
            color: "#ffffff",
            weight: 2,
            fillColor: "#ff3b30",
            fillOpacity: 0.08,
          },
        }).addTo(map);
        if (layer.getBounds().isValid()) map.fitBounds(layer.getBounds());
        const savedRois = await Promise.all(
          features.map((feature, index) => {
            const featureName =
              typeof feature.properties?.name === "string"
                ? feature.properties.name
                : `Zona ${index + 1}`;
            // El ROI se guarda como geometrÃ­a reutilizable para cualquier vuelo.
            return dashboardApi.saveRoi(
              feature,
              null,
              activeCycleId,
              featureName,
            );
          }),
        );
        let polygonIndex = 0;
        layer.eachLayer((polygon) => {
          const roiId = savedRois[polygonIndex]?.roi.id ?? null;
          polygonIndex += 1;
          if (roiId) roiLayersRef.current.set(roiId, polygon);
          polygon.on("click", () => {
            selectRoi(
              (polygon as L.Layer & { toGeoJSON: () => unknown }).toGeoJSON(),
              roiId,
            );
          });
        });
        features.forEach((feature, index) =>
          selectRoi(feature, savedRois[index]?.roi.id ?? null),
        );
      } catch (error) {
        setState((current) => ({
          ...current,
          error:
            error instanceof Error
              ? error.message
              : "No se pudo analizar la regiÃ³n importada.",
        }));
      }
    },
    [activeCycleId, selectRoi, state.orthoMode],
  );

  /** Alterna el grupo de etiquetas de diÃ¡metro sin volver a crear el mapa. */
  const toggleLabels = useCallback(() => {
    const map = mapRef.current;
    if (
      !map ||
      !treeDataRef.current ||
      !treeRef.current ||
      !map.hasLayer(treeRef.current)
    )
      return;
    const enabled = !state.labels;

    if (enabled) {
      labelsEnabledRef.current = true;
      refreshLabels();
      labelsRef.current?.addTo(map);
    } else {
      labelsEnabledRef.current = false;
      labelsRef.current?.remove();
    }

    setState((current) => ({ ...current, labels: enabled }));
  }, [state.labels]);

  /** Cede un cuadro al navegador para que el modal pueda pintar el progreso. */
  const waitForPaint = useCallback(
    () =>
      new Promise<void>((resolve) => {
        window.requestAnimationFrame(() => resolve());
      }),
    [],
  );

  /**
   * Importa detecciones desde GeoJSON o Shapefile y mantiene el modal informado
   * de cada etapa costosa antes de representar los puntos en Leaflet.
   */
  const importDetections = useCallback(
    async (
      files: File[],
      reportProgress?: (progress: number, message: string) => void,
    ) => {
      try {
        reportProgress?.(8, "Leyendo archivos...");
        await waitForPaint();
        reportProgress?.(34, "Interpretando geometrÃ­as...");
        const rawCollection = await parseDetectionFiles(files);
        rawTreeDataRef.current = rawCollection;
        const parsed = normalizeTreeCollection(rawCollection);
        await waitForPaint();

        reportProgress?.(54, "Normalizando diÃ¡metros en el servidor...");
        let collection = parsed;
        try {
          const normalized = await dashboardApi.treePoints(parsed);
          collection = normalizeTreeCollection(normalized.geojson);
        } catch {
          // El render local mantiene operativo el mapa si la API estÃ¡ apagada.
          reportProgress?.(
            62,
            "Backend no disponible; usando datos locales...",
          );
        }
        await waitForPaint();

        reportProgress?.(70, "Clasificando tamaÃ±os...");
        const allSizesVisible = { small: true, medium: true, large: true };
        treeDataRef.current = collection;
        diameterRangeRef.current = { min: -Infinity, max: Infinity };
        visibleTreeSizesRef.current = allSizesVisible;
        // El diÃ¡metro fÃ­sico es la vista principal; el usuario puede volver a puntos.
        treeDisplayModeRef.current = "diameters";
        setTreeData(collection);
        setFilteredTreeData(collection);

        reportProgress?.(88, "Dibujando detecciones...");
        await waitForPaint();
        renderTreeLayer(collection, true);
        labelsRef.current?.remove();
        labelsRef.current = L.layerGroup();
        labelsEnabledRef.current = false;

        const map = mapRef.current;
        const bounds = treeRef.current?.getBounds();
        if (map && bounds?.isValid())
          map.fitBounds(bounds, { padding: [32, 32] });
        setState((current) => ({
          ...current,
          trees: true,
          labels: false,
          treeDisplayMode: "diameters",
          visibleTreeSizes: allSizesVisible,
          error: null,
        }));
        reportProgress?.(100, "Detecciones listas");
        return collection;
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "No se pudieron importar las detecciones.";
        setState((current) => ({ ...current, error: message }));
        throw error;
      }
    },
    [renderTreeLayer, waitForPaint],
  );

  /** Cambia entre sÃ­mbolos puntuales y cÃ­rculos con diÃ¡metro fÃ­sico en metros. */
  const setTreeDisplayMode = useCallback(
    (mode: TreeDisplayMode) => {
      treeDisplayModeRef.current = mode;
      const map = mapRef.current;
      const collection = treeDataRef.current;
      const wasVisible = Boolean(
        map && treeRef.current && map.hasLayer(treeRef.current),
      );
      if (collection) {
        renderTreeLayer(collection, wasVisible);
        syncTreeLayerVisibility();
      }
      refreshLabels();
      setState((current) => ({ ...current, treeDisplayMode: mode }));
    },
    [refreshLabels, renderTreeLayer, syncTreeLayerVisibility],
  );

  /** Asigna un atributo numÃ©rico como diÃ¡metro y reconstruye todo el anÃ¡lisis. */
  const setTreeDiameterField = useCallback(
    (field: string | null) => {
      const source = rawTreeDataRef.current ?? treeDataRef.current;
      if (!source) return;
      try {
        const collection = normalizeTreeCollection(source, field);
        const map = mapRef.current;
        const wasVisible = Boolean(
          map && treeRef.current && map.hasLayer(treeRef.current),
        );
        treeDataRef.current = collection;
        diameterRangeRef.current = { min: -Infinity, max: Infinity };
        setTreeData(collection);
        setFilteredTreeData(
          filterVisibleTrees(
            collection,
            diameterRangeRef.current,
            visibleTreeSizesRef.current,
          ),
        );
        renderTreeLayer(collection, wasVisible);
        syncTreeLayerVisibility();
        refreshLabels();
        setState((current) => ({ ...current, error: null }));
      } catch (error) {
        setState((current) => ({
          ...current,
          error:
            error instanceof Error
              ? error.message
              : "No se pudo asignar el campo de diÃ¡metro.",
        }));
      }
    },
    [refreshLabels, renderTreeLayer, syncTreeLayerVisibility],
  );

  /** Espera un clic sobre el mapa y agrega una detecciÃ³n con diÃ¡metro conocido. */
  const startAddDetection = useCallback(
    (diameter: number) => {
      const map = mapRef.current;
      if (!map || !Number.isFinite(diameter) || diameter <= 0) return;
      cancelDetectionEdit();
      detectionEditModeRef.current = "add";
      map.getContainer().style.cursor = "crosshair";
      const handler = (event: L.LeafletMouseEvent) => {
        const source = treeDataRef.current ?? {
          type: "FeatureCollection" as const,
          features: [],
        };
        const next = normalizeTreeCollection({
          ...source,
          features: [
            ...source.features,
            {
              type: "Feature",
              geometry: {
                type: "Point",
                coordinates: [event.latlng.lng, event.latlng.lat],
              },
              properties: {
                id: `manual-${Date.now()}`,
                diameter_m: diameter,
                diameter_source: "manual",
              },
            },
          ],
        });
        cancelDetectionEdit();
        // La primera detecciÃ³n manual inaugura y muestra la capa; las
        // siguientes respetan la visibilidad que el usuario ya eligiÃ³.
        commitTreeCollection(next, source.features.length === 0);
      };
      addDetectionClickRef.current = handler;
      map.once("click", handler);
      setState((current) => ({
        ...current,
        detectionEditMode: "add",
        error: null,
      }));
    },
    [cancelDetectionEdit, commitTreeCollection],
  );

  /** Permite eliminar la siguiente detecciÃ³n pulsada directamente en el mapa. */
  const startDeleteDetection = useCallback(() => {
    const map = mapRef.current;
    const layerGroup = treeRef.current;
    if (!map || !layerGroup || !treeDataRef.current) return;
    cancelDetectionEdit();
    detectionEditModeRef.current = "delete-one";
    map.getContainer().style.cursor = "not-allowed";
    layerGroup.eachLayer((layer) => {
      const feature = (layer as L.Layer & { feature?: TreeFeature }).feature;
      if (!feature) return;
      const handler = (event: L.LeafletMouseEvent) => {
        if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
        const source = treeDataRef.current;
        if (!source) return;
        const next = {
          ...source,
          features: source.features.filter((candidate) => candidate !== feature),
        };
        cancelDetectionEdit();
        commitTreeCollection(next);
      };
      deleteDetectionHandlersRef.current.set(layer, handler);
      layer.on("click", handler);
    });
    setState((current) => ({
      ...current,
      detectionEditMode: "delete-one",
      error: null,
    }));
  }, [cancelDetectionEdit, commitTreeCollection]);

  /** Dibuja un rectÃ¡ngulo sombreado y elimina todas las detecciones interiores. */
  const startDeleteDetectionsArea = useCallback(() => {
    const map = mapRef.current;
    if (!map || !treeDataRef.current?.features.length) return;
    cancelDetectionEdit();
    detectionEditModeRef.current = "delete-area";
    map.getContainer().style.cursor = "crosshair";
    map.pm?.enableDraw("Rectangle", {
      pathOptions: {
        color: "#9b3f36",
        weight: 2,
        fillColor: "#b95a4f",
        fillOpacity: 0.18,
      },
    });
    setState((current) => ({
      ...current,
      detectionEditMode: "delete-area",
      error: null,
    }));
  }, [cancelDetectionEdit]);

  /** Activa u oculta una talla y sincroniza mapa, etiquetas e histogramas. */
  const toggleTreeSize = useCallback(
    (size: VisibleTreeSize) => {
      const next = {
        ...visibleTreeSizesRef.current,
        [size]: !visibleTreeSizesRef.current[size],
      };
      visibleTreeSizesRef.current = next;
      setFilteredTreeData(
        filterVisibleTrees(treeDataRef.current, diameterRangeRef.current, next),
      );
      setState((current) => ({ ...current, visibleTreeSizes: next }));
      syncTreeLayerVisibility();
      refreshLabels();
    },
    [refreshLabels, syncTreeLayerVisibility],
  );

  /** Importa Ã¡rboles, crea popups seguros y ajusta el mapa a su extensiÃ³n. */
  const importFile = useCallback(
    async (file: File) => {
      try {
        const parsed = await parseImportFile(file);
        const map = mapRef.current;
        if (!map) return;

        const hasArea = parsed.features.some(
          (feature) => feature.geometry.type !== "Point",
        );
        if (!hasArea && state.orthoMode !== "rgb")
          throw new Error(
            "Carga un ortomosaico RGB antes de importar detecciones.",
          );
        if (
          hasArea &&
          boundsRef.current &&
          state.orthoMode === "multispectral"
        ) {
          const response = await dashboardApi.roi(parsed);
          const stats = ndviStats(response);
          const defaultMinimum = response.range_min ?? stats.min;
          const defaultMaximum = response.range_max ?? stats.max;
          ndviResponseRef.current = response;
          setNdviAnalysis((current) => {
            ndviRangeRef.current = {
              min: defaultMinimum,
              max: defaultMaximum,
              equalized: current.equalized,
              fillMode: current.fillMode,
              values: stats.values,
            };
            return {
              ...current,
              response,
              stats,
              roiResponse: response,
              roiStats: stats,
              minimum: defaultMinimum,
              maximum: defaultMaximum,
            };
          });
          ndviTileRef.current?.remove();
          ndviTileRef.current = undefined;
          renderNdvi(response);
        }

        const points: TreeFeature[] = parsed.features
          .filter(
            (feature) =>
              feature.geometry.type === "Point" &&
              feature.geometry.coordinates.length >= 2,
          )
          .map((feature) => {
            const coordinates =
              feature.geometry.type === "Point"
                ? feature.geometry.coordinates
                : [0, 0];
            return {
              type: "Feature",
              geometry: {
                type: "Point",
                coordinates: [
                  Number(coordinates[0]),
                  Number(coordinates[1]),
                ] as [number, number],
              },
              properties: feature.properties,
            };
          });
        const pointCollection: TreeCollection = {
          type: "FeatureCollection",
          features: points,
        };
        treeDataRef.current = pointCollection;
        setTreeData(points.length ? pointCollection : null);
        setFilteredTreeData(points.length ? pointCollection : null);
        diameterRangeRef.current = { min: -Infinity, max: Infinity };
        treeRef.current?.remove();
        treeRef.current = L.geoJSON(parsed, {
          pointToLayer: (feature, latlng) => {
            const diameter = diameterOf(feature as never);
            const size = sizeOf(diameter);
            return L.circle(latlng, {
              radius: Math.max(
                0.2,
                Number.isFinite(diameter) ? diameter / 2 : 1,
              ),
              color: treeSizeColors[size],
              fillColor: treeSizeColors[size],
              fillOpacity: 0.58,
              weight: 1,
            });
          },
          style: {
            color: "#2563eb",
            weight: 2,
            fillColor: "#60a5fa",
            fillOpacity: 0.18,
          },
          onEachFeature: (feature: Feature, layer) =>
            layer.bindPopup(buildGeometryPopupHtml(feature)),
        });
        treeRef.current.addTo(map);
        labelsRef.current = L.layerGroup();
        setState((current) => ({
          ...current,
          trees: points.length > 0 && state.orthoMode === "rgb",
          labels: false,
          ndvi:
            state.orthoMode === "multispectral" && hasArea
              ? true
              : current.ndvi,
          error: null,
        }));
      } catch (error) {
        setState((current) => ({
          ...current,
          error: error instanceof Error ? error.message : "GeoJSON invÃ¡lido",
        }));
      }
    },
    [renderNdvi, state.orthoMode],
  );

  /** Aplica el filtro de diÃ¡metro tanto a sÃ­mbolos como a etiquetas. */
  const setDiameterRange = useCallback(
    (min: number, max: number) => {
      diameterRangeRef.current = { min, max };
      setFilteredTreeData(
        filterVisibleTrees(
          treeDataRef.current,
          { min, max },
          visibleTreeSizesRef.current,
        ),
      );
      syncTreeLayerVisibility();
      refreshLabels();
    },
    [refreshLabels, syncTreeLayerVisibility],
  );



  return {
    drawPrescriptionArea,
    drawRoi,
    importDetections,
    importFile,
    importRoi,
    setDiameterRange,
    setTreeDiameterField,
    setTreeDisplayMode,
    startAddDetection,
    startDeleteDetection,
    startDeleteDetectionsArea,
    toggleLabels,
    toggleTrees,
    toggleTreeSize,
    waitForPaint,
  };
}

