// @ts-nocheck
import { useCallback } from "react";
import L from "leaflet";
import type { Feature } from "geojson";
import type { TreeCollection, TreeFeature } from "../types/geo";
import {
  diameterOf,
  sizeOf,
  treeSizeColors,
} from "../utils/tree";
import {
  equalizedPosition,
  indexColorFromPosition,
  type ClassificationFillMode,
  type HistogramEqualization,
} from "../utils/ndvi";
import { buildTreePopupHtml, filterVisibleTrees } from "./useDashboardMap.helpers";

export function useDashboardMapTreeCore(ctx: any) {
  const {
    addDetectionClickRef,
    deleteDetectionHandlersRef,
    detectionEditModeRef,
    diameterRangeRef,
    labelsEnabledRef,
    labelsRef,
    mapRef,
    rawTreeDataRef,
    setFilteredTreeData,
    setState,
    setTreeData,
    treeDataRef,
    treeDisplayModeRef,
    treeRef,
    visibleTreeSizesRef,
  } = ctx;

  /** Reconstruye etiquetas visibles respetando el filtro de diÃ¡metro vigente. */
  const refreshLabels = useCallback(() => {
    const map = mapRef.current;
    if (!map || !labelsEnabledRef.current || !treeDataRef.current) return;
    labelsRef.current?.clearLayers();
    treeDataRef.current.features.forEach((feature) => {
      const diameter = diameterOf(feature);
      const { min, max } = diameterRangeRef.current;
      const category = sizeOf(diameter);
      if (
        !Number.isFinite(diameter) ||
        diameter < min ||
        diameter > max ||
        (category !== "unknown" && !visibleTreeSizesRef.current[category])
      )
        return;
      L.marker(
        [feature.geometry.coordinates[1], feature.geometry.coordinates[0]],
        {
          pane: "treeLabelsPane",
          interactive: false,
          icon: L.divIcon({
            className: "tree-diameter-label-icon",
            html: `<span>${diameter.toFixed(2)} m</span>`,
            iconSize: [1, 1],
          }),
        },
      ).addTo(labelsRef.current!);
    });
  }, []);

  /** Crea la capa de detecciones en modo puntual o con diÃ¡metro proporcional. */
  const renderTreeLayer = useCallback(
    (collection: TreeCollection, visible = true) => {
      const map = mapRef.current;
      if (!map) return;
      treeRef.current?.remove();
      treeRef.current = L.geoJSON(collection, {
        pointToLayer: (feature, latlng) => {
          const treeFeature = feature as TreeFeature;
          const diameter = diameterOf(treeFeature);
          const category = sizeOf(diameter);
          const options: L.PathOptions = {
            color: treeSizeColors[category],
            fillColor: treeSizeColors[category],
            opacity: category === "unknown" ? 0.35 : 0.85,
            fillOpacity: category === "unknown" ? 0.12 : 0.35,
            weight: category === "unknown" ? 1 : 2,
          };
          return treeDisplayModeRef.current === "diameters"
            ? L.circle(latlng, {
                ...options,
                radius: Number.isFinite(diameter)
                  ? Math.max(0.2, diameter / 2)
                  : 1,
              })
            : L.circleMarker(latlng, { ...options, radius: 5 });
        },
        onEachFeature: (feature: Feature, layer) => {
          layer.bindPopup(buildTreePopupHtml(feature as TreeFeature));
        },
      });
      if (visible) treeRef.current.addTo(map);
    },
    [],
  );

  /** Aplica en la capa los filtros de rango y categorÃ­as seleccionadas. */
  const syncTreeLayerVisibility = useCallback(() => {
    treeRef.current?.eachLayer((layer) => {
      const feature = (layer as L.Layer & { feature?: TreeFeature }).feature;
      if (!feature) return;
      const diameter = diameterOf(feature);
      const category = sizeOf(diameter);
      const { min, max } = diameterRangeRef.current;
      const withinRange =
        Number.isFinite(diameter) && diameter >= min && diameter <= max;
      const visibleBySize =
        category === "unknown" || visibleTreeSizesRef.current[category];
      (layer as L.Path).setStyle({
        opacity: !visibleBySize
          ? 0
          : category === "unknown"
            ? 0.2
            : withinRange
              ? 0.85
              : 0.1,
        fillOpacity: !visibleBySize
          ? 0
          : category === "unknown"
            ? 0.08
            : withinRange
              ? 0.35
              : 0.08,
        weight: withinRange ? 2 : 1,
      });
    });
  }, []);

  /** Cancela cualquier herramienta manual y restaura la interacciÃ³n del mapa. */
  const cancelDetectionEdit = useCallback(() => {
    const map = mapRef.current;
    if (map && addDetectionClickRef.current)
      map.off("click", addDetectionClickRef.current);
    addDetectionClickRef.current = null;
    deleteDetectionHandlersRef.current.forEach((handler, layer) =>
      layer.off("click", handler),
    );
    deleteDetectionHandlersRef.current.clear();
    map?.pm?.disableDraw("Rectangle");
    if (map) map.getContainer().style.cursor = "";
    detectionEditModeRef.current = null;
    setState((current) => ({ ...current, detectionEditMode: null }));
  }, []);

  /** Sustituye el conjunto editado y sincroniza mapa, filtros y estadÃ­sticas. */
  const commitTreeCollection = useCallback(
    (collection: TreeCollection, makeVisible?: boolean) => {
      const map = mapRef.current;
      const wasVisible =
        makeVisible ??
        Boolean(map && treeRef.current && map.hasLayer(treeRef.current));
      rawTreeDataRef.current = collection;
      treeDataRef.current = collection;
      setTreeData(collection);
      setFilteredTreeData(
        filterVisibleTrees(
          collection,
          diameterRangeRef.current,
          visibleTreeSizesRef.current,
        ),
      );
      labelsRef.current?.clearLayers();
      if (collection.features.length) {
        renderTreeLayer(collection, wasVisible);
        syncTreeLayerVisibility();
        refreshLabels();
      } else {
        treeRef.current?.remove();
        treeRef.current = undefined;
      }
      setState((current) => ({
        ...current,
        trees: collection.features.length > 0 && wasVisible,
        labels: collection.features.length ? current.labels : false,
        error: null,
      }));
    },
    [refreshLabels, renderTreeLayer, syncTreeLayerVisibility],
  );

  const renderClassificationPixel = useCallback(
    (
      name: "NDVI" | "NDWI" | "NDRE",
      value: number,
      minimum: number,
      maximum: number,
      fillMode: ClassificationFillMode,
      equalization: HistogramEqualization | null,
    ) => {
      if (!Number.isFinite(value)) return null;
      const inRange = value >= minimum && value <= maximum;
      const normalizedPosition = Math.max(
        0,
        Math.min(1, (value - minimum) / Math.max(maximum - minimum, Number.EPSILON)),
      );
      const palettePosition =
        equalization && inRange
          ? (equalizedPosition(value, equalization) ?? normalizedPosition)
          : normalizedPosition;
      const color = indexColorFromPosition(name, palettePosition)
        .match(/\d+/g)
        ?.map(Number) ?? [0, 0, 0];
      const alpha = inRange ? 255 : fillMode === "solid" ? 255 : 0;
      return { color, alpha };
    },
    [],
  );



  return {
    cancelDetectionEdit,
    commitTreeCollection,
    refreshLabels,
    renderClassificationPixel,
    renderTreeLayer,
    syncTreeLayerVisibility,
  };
}

