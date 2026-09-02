/**
 * Hook central del dashboard geoespacial.
 * Coordina mapa Leaflet, ortomosaicos, ROI, índices, histogramas, diálogos,
 * trazabilidad y sincronización con el backend.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import L from "leaflet";
import type { Feature } from "geojson";
import "@geoman-io/leaflet-geoman-free";
import {
  backendUrl,
  dashboardApi,
  type NdviResponse,
  type NdviZoningResponse,
  type OrthomosaicRecord,
  type OrthoMode,
  type OrthoSensor,
  type PrescriptionMapResponse,
} from "../services/api";
import type { TreeCollection, TreeFeature } from "../types/geo";
import {
  diameterOf,
  normalizeTreeCollection,
  sizeOf,
  treeSizeColors,
  type VisibleTreeSize,
} from "../utils/tree";
import { parseDetectionFiles, parseImportFile } from "../utils/importFormats";
import {
  indexColor,
  ndviColor,
  ndviStats,
  type NdviStats,
} from "../utils/ndvi";
import {
  buildGeometryPopupHtml,
  buildRoiSelection,
  buildTreePopupHtml,
  createEmptyNdviAnalysis,
  createInitialMapState,
  filterVisibleTrees,
  modeFromSensor,
} from "./useDashboardMap.helpers";
import {
  mountStoredOrthomosaic,
  mountUploadedOrthomosaic,
  resetOrthomosaicArtifacts,
} from "./useDashboardMap.orthomosaic";
import {
  applyRoiCropLayer,
  clearRoiArtifacts,
  restoreBaseOrthoLayer,
} from "./useDashboardMap.roi";
import {
  clearSpectralLayers,
  createNdviResponse,
  createSpectralTileLayer,
  removeSingleSpectralLayer,
  replaceNdviTileLayer,
  replaceSpectralLayer,
} from "./useDashboardMap.spectral";

export type TreeDisplayMode = "points" | "diameters";
export type DetectionEditMode = "add" | "delete-one" | "delete-area" | null;

/** Estado serializable que consumen los componentes declarativos de React. */
export interface MapState {
  orthoMode: OrthoMode | null;
  sensor: OrthoSensor | null;
  orthomosaicId: string | null;
  ndvi: boolean;
  trees: boolean;
  labels: boolean;
  prescription: boolean;
  vari: boolean;
  exg: boolean;
  swipe: boolean;
  swipePosition: number;
  loaded: boolean;
  rgb: boolean;
  uploading: boolean;
  roiSelected: boolean;
  selectedRoiId: string | null;
  selectedRoiIds: string[];
  treeDisplayMode: TreeDisplayMode;
  visibleTreeSizes: Record<VisibleTreeSize, boolean>;
  detectionEditMode: DetectionEditMode;
  error: string | null;
}

/** Datos, estadísticas y rango visible de la capa NDVI actual. */
export interface NdviAnalysis {
  response: NdviResponse | null;
  stats: NdviStats;
  roiResponse: NdviResponse | null;
  roiStats: NdviStats;
  minimum: number;
  maximum: number;
}

/** Estado equivalente para índices adicionales que pueden coexistir. */
export interface IndexAnalysis {
  name: "NDWI" | "NDRE";
  response: NdviResponse;
  stats: NdviStats;
  minimum: number;
  maximum: number;
  visible: boolean;
}

/**
 * Orquesta el ciclo de vida de Leaflet, sus capas imperativas y las llamadas
 * geoespaciales. React recibe solo estados derivados y acciones estables.
 */
export function useDashboardMap(
  mapElement: React.RefObject<HTMLDivElement>,
  activeCycleId: string | null,
) {
  // Recursos Leaflet: cada referencia representa una capa única y reemplazable.
  const mapRef = useRef<L.Map>();
  const orthoRef = useRef<L.TileLayer>();
  const cropTileRef = useRef<L.TileLayer>();
  const uploadedRgbRef = useRef<L.ImageOverlay>();
  const ndviRef = useRef<L.ImageOverlay>();
  const ndviTileRef = useRef<L.TileLayer>();
  const indexRefs = useRef(new Map<string, L.Layer>());
  const treeRef = useRef<L.GeoJSON>();
  const labelsRef = useRef<L.LayerGroup>();
  const zoningRef = useRef<L.TileLayer>();
  const zoningPreviewRef = useRef<L.TileLayer>();
  const prescriptionRef = useRef<L.TileLayer>();
  const prescriptionAreaLayerRef = useRef<L.Layer>();
  const prescriptionGeometryRef = useRef<unknown>(null);
  const prescriptionDrawCompleteRef = useRef<(() => void) | null>(null);
  const zoningPreviewTokenRef = useRef(0);
  // Datos y controles que deben estar disponibles dentro de callbacks de mapa.
  const boundsRef = useRef<L.LatLngBounds>();
  const rawTreeDataRef = useRef<TreeCollection | null>(null);
  const treeDataRef = useRef<TreeCollection | null>(null);
  const diameterRangeRef = useRef({ min: -Infinity, max: Infinity });
  const treeDisplayModeRef = useRef<TreeDisplayMode>("points");
  const visibleTreeSizesRef = useRef<Record<VisibleTreeSize, boolean>>({
    small: true,
    medium: true,
    large: true,
  });
  const detectionEditModeRef = useRef<DetectionEditMode>(null);
  const addDetectionClickRef = useRef<
    ((event: L.LeafletMouseEvent) => void) | null
  >(null);
  const deleteDetectionHandlersRef = useRef(
    new Map<L.Layer, (event: L.LeafletMouseEvent) => void>(),
  );
  const labelsEnabledRef = useRef(false);
  const ratioRef = useRef(0.5);
  const swipeEnabledRef = useRef(false);
  const ndviRangeRef = useRef({ min: -1, max: 1 });
  const ndviResponseRef = useRef<NdviResponse | null>(null);
  // Selección ROI, recorte activo y respuestas espectrales asociadas.
  const selectedRoiRef = useRef<unknown>(null);
  const activeCropGeometryRef = useRef<unknown>(null);
  const activeCropIdRef = useRef<string | null>(null);
  const cropControlRef = useRef<L.Marker>();
  const roiIndexResponsesRef = useRef<Record<
    "NDVI" | "NDWI" | "NDRE",
    NdviResponse
  > | Partial<Record<"NDVI" | "NDWI" | "NDRE", NdviResponse>> | null>(null);
  const roiLayersRef = useRef(new Map<string, L.Layer>());
  const selectedRoisRef = useRef(new Map<string, unknown>());
  // Los listeners de Leaflet se registran una sola vez. Esta referencia evita
  // que conserven el ciclo nulo del primer render al persistir un ROI.
  const activeCycleIdRef = useRef(activeCycleId);
  // Estado declarativo expuesto a la interfaz.
  const [state, setState] = useState<MapState>(createInitialMapState());
  const [treeData, setTreeData] = useState<TreeCollection | null>(null);
  const [filteredTreeData, setFilteredTreeData] =
    useState<TreeCollection | null>(null);
  const [ndviAnalysis, setNdviAnalysis] = useState<NdviAnalysis>(
    createEmptyNdviAnalysis(),
  );
  const [indexAnalyses, setIndexAnalyses] = useState<IndexAnalysis[]>([]);
  const [zoning, setZoning] = useState<NdviZoningResponse | null>(null);
  const [zoningLoading, setZoningLoading] = useState(false);
  const [prescription, setPrescription] =
    useState<PrescriptionMapResponse | null>(null);
  const [prescriptionLoading, setPrescriptionLoading] = useState(false);
  const [prescriptionAreaReady, setPrescriptionAreaReady] = useState(false);
  const [cropAvailable, setCropAvailable] = useState(false);
  const [cropExporting, setCropExporting] = useState(false);

  const activeAnalysisRange = useCallback(
    (name: "NDVI" | "NDWI" | "NDRE") => {
      if (name === "NDVI") {
        return {
          minimum: ndviAnalysis.minimum,
          maximum: ndviAnalysis.maximum,
        };
      }
      const analysis = indexAnalyses.find((item) => item.name === name);
      return analysis
        ? { minimum: analysis.minimum, maximum: analysis.maximum }
        : null;
    },
    [indexAnalyses, ndviAnalysis.maximum, ndviAnalysis.minimum],
  );

  useEffect(() => {
    activeCycleIdRef.current = activeCycleId;
  }, [activeCycleId]);

  const clearZoning = useCallback(() => {
    zoningPreviewTokenRef.current += 1;
    zoningPreviewRef.current?.remove();
    zoningPreviewRef.current = undefined;
    zoningRef.current?.remove();
    zoningRef.current = undefined;
    setZoning(null);
  }, []);

  const clearZoningPreview = useCallback(() => {
    zoningPreviewTokenRef.current += 1;
    zoningPreviewRef.current?.remove();
    zoningPreviewRef.current = undefined;
  }, []);

  const previewZoning = useCallback(
    async (
      indexName: "NDVI" | "NDWI" | "NDRE",
      zoneCount: number,
      cellSizeM: number,
      gridAngleDeg = 0,
      classificationMethod: "quantiles" | "equal_intervals" | "manual" = "quantiles",
      cellValueMode: "mean" | "min" | "max" = "mean",
      detailLevel = 1,
      manualBreaks?: number[],
    ) => {
      const map = mapRef.current;
      if (!map || !state.orthomosaicId || zoning || prescription) return;
      if (state.orthoMode !== "multispectral") return;
      const indexReady =
        indexName === "NDVI"
          ? ndviAnalysis.roiResponse
          : indexAnalyses.some((analysis) => analysis.name === indexName);
      if (!activeCropGeometryRef.current || !indexReady) return;
      const geometry =
        prescriptionGeometryRef.current ?? activeCropGeometryRef.current;
      const token = ++zoningPreviewTokenRef.current;
      const result = await dashboardApi.createNdviZoning(
        state.orthomosaicId,
        indexName,
        geometry,
        zoneCount,
        cellSizeM,
        gridAngleDeg,
        {
          classificationMethod,
          cellValueMode,
          detailLevel,
          manualBreaks,
          analysisMin: activeAnalysisRange(indexName)?.minimum,
          analysisMax: activeAnalysisRange(indexName)?.maximum,
        },
      );
      if (token !== zoningPreviewTokenRef.current || zoning || prescription) return;
      zoningPreviewRef.current?.remove();
      zoningPreviewRef.current = L.tileLayer(backendUrl(result.tile_url), {
        tileSize: 256,
        maxNativeZoom: 24,
        maxZoom: 24,
        keepBuffer: 3,
        updateWhenIdle: true,
        updateWhenZooming: false,
        opacity: 0.92,
        className: "zoning-map-overlay is-preview",
      }).addTo(map);
      zoningPreviewRef.current.setZIndex(515);
    },
    [
      activeAnalysisRange,
      indexAnalyses,
      ndviAnalysis.roiResponse,
      prescription,
      state.orthoMode,
      state.orthomosaicId,
      zoning,
    ],
  );

  const clearPrescription = useCallback(() => {
    clearZoning();
    prescriptionRef.current?.remove();
    prescriptionRef.current = undefined;
    setPrescription(null);
    setState((current) => ({ ...current, prescription: false }));
  }, [clearZoning]);

  const clearPrescriptionArea = useCallback(() => {
    prescriptionDrawCompleteRef.current = null;
    prescriptionGeometryRef.current = null;
    prescriptionAreaLayerRef.current?.remove();
    prescriptionAreaLayerRef.current = undefined;
    setPrescriptionAreaReady(false);
  }, []);

  const generateZoning = useCallback(
    async (
      indexName: "NDVI" | "NDWI" | "NDRE",
      zoneCount: number,
      cellSizeM: number,
      gridAngleDeg = 0,
      classificationMethod: "quantiles" | "equal_intervals" | "manual" = "quantiles",
      cellValueMode: "mean" | "min" | "max" = "mean",
      detailLevel = 1,
      manualBreaks?: number[],
    ) => {
      const map = mapRef.current;
      if (!map || !state.orthomosaicId)
        throw new Error("Selecciona un vuelo antes de generar la zonificacion.");
      if (state.orthoMode !== "multispectral")
        throw new Error(`La zonificacion ${indexName} requiere un ortomosaico multiespectral.`);
      const indexReady =
        indexName === "NDVI"
          ? ndviAnalysis.roiResponse
          : indexAnalyses.some((analysis) => analysis.name === indexName);
      if (!activeCropGeometryRef.current || !indexReady)
        throw new Error(
          `Selecciona un ROI, recortalo y abre su histograma ${indexName} antes de generar la zonificacion.`,
        );
      setZoningLoading(true);
      try {
        const geometry =
          prescriptionGeometryRef.current ?? activeCropGeometryRef.current;
        const result = await dashboardApi.createNdviZoning(
          state.orthomosaicId,
          indexName,
          geometry,
          zoneCount,
          cellSizeM,
          gridAngleDeg,
          {
            classificationMethod,
            cellValueMode,
            detailLevel,
            manualBreaks,
            analysisMin: activeAnalysisRange(indexName)?.minimum,
            analysisMax: activeAnalysisRange(indexName)?.maximum,
          },
        );
        clearZoningPreview();
        clearPrescription();
        zoningRef.current?.remove();
        zoningRef.current = L.tileLayer(backendUrl(result.tile_url), {
          tileSize: 256,
          maxNativeZoom: 24,
          maxZoom: 24,
          keepBuffer: 3,
          updateWhenIdle: true,
          updateWhenZooming: false,
          opacity: 1,
          className: "zoning-map-overlay",
        }).addTo(map);
        zoningRef.current.setZIndex(520);
        setZoning(result);
        setState((current) => ({ ...current, prescription: true, error: null }));
        map.fitBounds(result.bounds);
        return result;
      } finally {
        setZoningLoading(false);
      }
    },
    [
      activeAnalysisRange,
      clearZoningPreview,
      clearPrescription,
      indexAnalyses,
      ndviAnalysis.roiResponse,
      state.orthoMode,
      state.orthomosaicId,
    ],
  );

  const generatePrescription = useCallback(
    async (
      indexName: "NDVI" | "NDWI" | "NDRE",
      zoneCount: number,
      cellSizeM: number,
      gridAngleDeg = 0,
      classificationMethod: "quantiles" | "equal_intervals" | "manual" = "quantiles",
      cellValueMode: "mean" | "min" | "max" = "mean",
      detailLevel = 1,
      manualBreaks?: number[],
      doses?: number[],
    ) => {
      const map = mapRef.current;
      if (!map || !state.orthomosaicId)
        throw new Error("Selecciona un vuelo antes de generar la prescripción.");
      if (state.orthoMode !== "multispectral")
        throw new Error("La prescripción NDVI requiere un ortomosaico multiespectral.");
      const indexReady =
        indexName === "NDVI"
          ? ndviAnalysis.roiResponse
          : indexAnalyses.some((analysis) => analysis.name === indexName);
      if (!activeCropGeometryRef.current || !indexReady)
        throw new Error(
          "Selecciona un ROI, recórtalo y abre su histograma NDVI antes de generar la prescripción.",
        );
      setPrescriptionLoading(true);
      try {
        const geometry =
          prescriptionGeometryRef.current ?? activeCropGeometryRef.current;
        const result = await dashboardApi.createPrescription(
          state.orthomosaicId,
          indexName,
          geometry,
          zoneCount,
          cellSizeM,
          gridAngleDeg,
          {
            classificationMethod,
            cellValueMode,
            detailLevel,
            manualBreaks,
            analysisMin: activeAnalysisRange(indexName)?.minimum,
            analysisMax: activeAnalysisRange(indexName)?.maximum,
            doses,
          },
        );
        clearZoningPreview();
        zoningRef.current?.remove();
        zoningRef.current = undefined;
        setZoning(null);
        prescriptionRef.current?.remove();
        prescriptionRef.current = L.tileLayer(backendUrl(result.tile_url), {
          tileSize: 256,
          maxNativeZoom: 24,
          maxZoom: 24,
          keepBuffer: 3,
          updateWhenIdle: true,
          updateWhenZooming: false,
          opacity: 1,
          className: "prescription-map-overlay",
        }).addTo(map);
        prescriptionRef.current.setZIndex(520);
        setPrescription(result);
        setState((current) => ({ ...current, prescription: true, error: null }));
        map.fitBounds(result.bounds);
        return result;
      } finally {
        setPrescriptionLoading(false);
      }
    },
    [
      activeAnalysisRange,
      clearZoningPreview,
      indexAnalyses,
      ndviAnalysis.roiResponse,
      state.orthoMode,
      state.orthomosaicId,
    ],
  );

  /** Reconstruye etiquetas visibles respetando el filtro de diámetro vigente. */
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

  /** Crea la capa de detecciones en modo puntual o con diámetro proporcional. */
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

  /** Aplica en la capa los filtros de rango y categorías seleccionadas. */
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

  /** Cancela cualquier herramienta manual y restaura la interacción del mapa. */
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

  /** Sustituye el conjunto editado y sincroniza mapa, filtros y estadísticas. */
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

  /** Rasteriza NDVI en canvas aplicando máscara, rampa y rango seleccionado. */
  const renderNdvi = useCallback((response: NdviResponse) => {
    const matrix = response.matrix;
    if (!matrix?.length) return;

    const canvas = document.createElement("canvas");
    canvas.width = matrix[0].length;
    canvas.height = matrix.length;
    const context = canvas.getContext("2d");
    if (!context) return;

    const image = context.createImageData(canvas.width, canvas.height);
    const { min, max } = ndviRangeRef.current;

    matrix.forEach((row, y) =>
      row.forEach((value, x) => {
        // El backend devuelve NDVI como byte normalizado (0..255).
        // Aceptar también el rango NDVI clásico (-1..1) para mantener el
        // cliente compatible con implementaciones anteriores.
        const numericValue = Number(value);
        const canonicalValue =
          numericValue > 1 ? (numericValue / 255) * 2 - 1 : numericValue;
        const position = (y * canvas.width + x) * 4;
        const color = ndviColor(canonicalValue, min, max)
          .match(/\d+/g)
          ?.map(Number) ?? [0, 0, 0];
        image.data[position] = color[0];
        image.data[position + 1] = color[1];
        image.data[position + 2] = color[2];
        const maskValue = response.mask?.[y]?.[x];
        image.data[position + 3] =
          Number.isFinite(canonicalValue) &&
          canonicalValue >= min &&
          canonicalValue <= max &&
          (maskValue === undefined || Number(maskValue) > 0)
            ? 255
            : 0;
      }),
    );

    context.putImageData(image, 0, 0);
    const map = mapRef.current;
    const overlayBounds = response.bounds
      ? L.latLngBounds(response.bounds)
      : boundsRef.current;
    if (!map || !overlayBounds) return;

    ndviRef.current?.remove();
    ndviRef.current = L.imageOverlay(canvas.toDataURL(), overlayBounds, {
      opacity: 1,
      interactive: false,
    }).addTo(map);
    const overlayImage = ndviRef.current.getElement();
    if (overlayImage)
      overlayImage.style.clipPath = swipeEnabledRef.current
        ? `inset(0 0 0 ${ratioRef.current * 100}%)`
        : "none";
  }, []);

  /** Recalcula el recorte CSS cuando el mapa cambia de zoom o posición. */
  const updateTileClip = useCallback(() => {
    const map = mapRef.current;
    const layer = orthoRef.current;
    const container = layer?.getContainer();
    const source = activeCropGeometryRef.current as {
      type?: string;
      geometry?: unknown;
      coordinates?: unknown;
    } | null;
    const geometry =
      source?.type === "Feature"
        ? (source.geometry as { type?: string; coordinates?: unknown })
        : source;
    if (
      !map ||
      !container ||
      !geometry ||
      (geometry.type !== "Polygon" && geometry.type !== "MultiPolygon")
    )
      return;
    const ring =
      geometry.type === "Polygon"
        ? (geometry.coordinates as number[][][])[0]
        : (geometry.coordinates as number[][][][])[0]?.[0];
    if (!ring?.length) return;
    // El clip se aplica al contenedor de la capa de tiles, por lo que debe
    // usar coordenadas de capa y no coordenadas del contenedor del mapa.
    const points = ring.map(([longitude, latitude]) =>
      map.latLngToLayerPoint([latitude, longitude]),
    );
    container.style.clipPath = `polygon(${points.map((point) => `${point.x}px ${point.y}px`).join(", ")})`;
  }, []);

  /** Elimina tiles de recorte y cualquier clip aplicado a la capa base. */
  const clearTileClip = useCallback(() => {
    activeCropGeometryRef.current = null;
    activeCropIdRef.current = null;
    cropTileRef.current?.remove();
    cropTileRef.current = undefined;
    const container = orthoRef.current?.getContainer();
    if (container) container.style.clipPath = "";
    setCropAvailable(false);
  }, []);

  /** Diferencia visualmente polígonos seleccionados y disponibles. */
  const styleRoiLayer = useCallback((roiId: string, selected: boolean) => {
    const layer = roiLayersRef.current.get(roiId);
    if (!layer) return;
    const style = selected
      ? { color: "#496f56", weight: 3, fillColor: "#6d9276", fillOpacity: 0.16 }
      : {
          color: "#ff3b30",
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
   * Restablece selección, recorte e índices ROI para que el mapa vuelva al
   * comportamiento global sin conservar resultados de una geometría anterior.
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

  /** Solicita el recorte ROI y deja NDWI/NDRE para cálculo explícito. */
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
    ndviRangeRef.current = { min: ndviZoneStats.min, max: ndviZoneStats.max };
    setNdviAnalysis((current) => ({
      ...current,
      response: null,
      stats: current.stats,
      roiResponse: null,
      roiStats: current.roiStats,
      minimum: ndviZoneStats.min,
      maximum: ndviZoneStats.max,
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

  /** Ejecuta el análisis para la colección ROI construida actualmente. */
  const cropSelectedRoi = useCallback(async () => {
    if (!selectedRoiRef.current) {
      setState((current) => ({
        ...current,
        error: "Selecciona una región de interés antes de recortar.",
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
   * única tijera sobre los límites conjuntos.
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
            html: '<span aria-hidden="true">✂</span>',
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

  /** Restaura geometrías persistentes después de cambiar el vuelo activo. */
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

  /** Alterna un ROI sin reemplazar los demás y descarta análisis obsoletos. */
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
              color: "#496f56",
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

  /** Elimina la capa exacta y conserva cualquier otra selección activa. */
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

  /** Renderizador local de respaldo para matrices NDWI y NDRE. */
  const renderIndex = useCallback(
    (
      name: IndexAnalysis["name"],
      response: NdviResponse,
      minimum: number,
      maximum: number,
    ) => {
      const matrix = response.matrix;
      if (!matrix?.length || !matrix[0]?.length) return;
      const canvas = document.createElement("canvas");
      canvas.width = matrix[0].length;
      canvas.height = matrix.length;
      const context = canvas.getContext("2d");
      if (!context || !boundsRef.current) return;
      const image = context.createImageData(canvas.width, canvas.height);
      matrix.forEach((row, y) =>
        row.forEach((value, x) => {
          const normalized = Number(value);
          const color = indexColor(name, normalized, minimum, maximum)
            .match(/\d+/g)
            ?.map(Number) ?? [0, 0, 0];
          const position = (y * canvas.width + x) * 4;
          image.data[position] = color[0];
          image.data[position + 1] = color[1];
          image.data[position + 2] = color[2];
          const visible =
            Number.isFinite(normalized) &&
            normalized >= minimum &&
            normalized <= maximum &&
            (response.mask?.[y]?.[x] === undefined ||
              Number(response.mask[y][x]) > 0);
          image.data[position + 3] = visible ? 255 : 0;
        }),
      );
      context.putImageData(image, 0, 0);
      const map = mapRef.current;
      if (!map) return;
      const previous = indexRefs.current.get(name);
      previous?.remove();
      const overlay = L.imageOverlay(
        canvas.toDataURL(),
        response.bounds ? L.latLngBounds(response.bounds) : boundsRef.current!,
        { opacity: 1, interactive: false },
      ).addTo(map);
      indexRefs.current.set(name, overlay);
    },
    [],
  );

  // Inicialización única del mapa base, Geoman y listeners de creación de ROI.
  useEffect(() => {
    const element = mapElement.current;
    if (!element || mapRef.current) return;

    const map = L.map(element, { maxZoom: 24, zoomControl: false }).setView(
      [23.6345, -102.5528],
      5,
    );
    mapRef.current = map;
    let disposed = false;
    const satellite = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: "Tiles © Esri",
        maxNativeZoom: 18,
        maxZoom: 24,
        updateWhenZooming: false,
        keepBuffer: 4,
      },
    );
    const labels = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: "Labels © Esri",
        maxNativeZoom: 18,
        maxZoom: 24,
        updateWhenZooming: false,
        keepBuffer: 4,
      },
    );

    L.layerGroup([satellite, labels]).addTo(map);
    L.control.zoom({ position: "topright" }).addTo(map);
    map.createPane("treeLabelsPane");
    const pane = map.getPane("treeLabelsPane");
    if (pane) {
      pane.style.zIndex = "650";
      pane.style.pointerEvents = "none";
    }

    map.pm?.setGlobalOptions({
      pathOptions: {
        color: "#ff3b30",
        weight: 2,
        opacity: 0.55,
        fillColor: "#ff3b30",
        fillOpacity: 0.08,
      },
    });
    map.pm?.addControls({
      position: "topleft",
      drawPolygon: false,
      drawPolyline: false,
      drawCircle: false,
      drawMarker: false,
      drawCircleMarker: false,
      drawRectangle: false,
      drawText: false,
      editMode: false,
      dragMode: false,
      cutPolygon: false,
      removalMode: false,
      rotateMode: false,
      scaleMode: false,
    });
    const handleRoiCreate = async (event: {
      layer: L.Layer & { toGeoJSON: () => unknown };
    }) => {
      if (disposed || mapRef.current !== map) return;
      if (prescriptionDrawCompleteRef.current) {
        const onComplete = prescriptionDrawCompleteRef.current;
        prescriptionDrawCompleteRef.current = null;
        map.pm?.disableDraw();
        prescriptionAreaLayerRef.current?.remove();
        prescriptionAreaLayerRef.current = event.layer;
        prescriptionGeometryRef.current = event.layer.toGeoJSON();
        if (event.layer instanceof L.Path) {
          event.layer.setStyle({
            color: "#244f32",
            weight: 2,
            dashArray: "6 4",
            fillColor: "#65a36f",
            fillOpacity: 0.12,
          });
        }
        setPrescriptionAreaReady(true);
        setState((current) => ({
          ...current,
          error: "Zona de cultivo delimitada. Ya puedes generar la prescripcion.",
        }));
        onComplete();
        return;
      }
      if (detectionEditModeRef.current === "delete-area") {
        const selection = event.layer as L.Layer & {
          getBounds?: () => L.LatLngBounds;
        };
        const selectionBounds = selection.getBounds?.();
        const source = treeDataRef.current;
        if (selectionBounds && source) {
          const collection: TreeCollection = {
            ...source,
            features: source.features.filter((feature) => {
              const [longitude, latitude] = feature.geometry.coordinates;
              return !selectionBounds.contains([latitude, longitude]);
            }),
          };
          event.layer.remove();
          cancelDetectionEdit();
          commitTreeCollection(collection);
        }
        return;
      }
      if (!boundsRef.current) {
        setState((current) => ({
          ...current,
          error: "Importa un ortomosaico antes de calcular un ROI.",
        }));
        return;
      }

      try {
        const roiGeojson = event.layer.toGeoJSON();
        const cycleId = activeCycleIdRef.current;
        if (!cycleId) {
          event.layer.remove();
          throw new Error(
            "Selecciona un ciclo agrícola antes de guardar una región de interés.",
          );
        }
        const saved = await dashboardApi.saveRoi(
          roiGeojson,
          null,
          cycleId,
          "ROI dibujado",
        );
        roiLayersRef.current.set(saved.roi.id, event.layer);
        event.layer.on("click", () => {
          selectRoi(roiGeojson, saved.roi.id);
        });
        selectRoi(roiGeojson, saved.roi.id);
      } catch (error) {
        if (disposed || mapRef.current !== map) return;
        setState((current) => ({
          ...current,
          error:
            error instanceof Error
              ? error.message
              : "No se pudo calcular el NDVI de la zona",
        }));
      }
    };
    map.on("pm:create", handleRoiCreate);
    map.on("moveend zoomend", updateTileClip);

    return () => {
      disposed = true;
      map.off("pm:create", handleRoiCreate);
      map.off("moveend zoomend", updateTileClip);
      map.remove();
      ndviTileRef.current = undefined;
      indexRefs.current.clear();
      roiLayersRef.current.clear();
      if (mapRef.current === map) mapRef.current = undefined;
    };
  }, [
    cancelDetectionEdit,
    commitTreeCollection,
    mapElement,
    selectRoi,
    updateTileClip,
  ]);

  /**
   * Guarda y activa un ortomosaico nuevo; limpia capas dependientes para no
   * mezclar resultados pertenecientes a vuelos diferentes.
   */
  const importOrtho = useCallback(
    async (file: File, sensor: OrthoSensor, agriculturalCycleId: string) => {
      setState((current) => ({ ...current, uploading: true, error: null }));
      const persistentRoiSelections = Array.from(
        selectedRoisRef.current.entries(),
      );
      try {
        const type: OrthoMode = modeFromSensor(sensor);
        const captureDate = new Date().toISOString().slice(0, 10);
        const upload = await dashboardApi.uploadOrthomosaic(
          file,
          sensor,
          captureDate,
          agriculturalCycleId,
        );
        const result =
          upload.analysis ?? (await dashboardApi.orthoAnalysis(file, sensor));
        clearPrescription();
        if (
          !mountUploadedOrthomosaic({
            backendUrl,
            bounds: result.bounds,
            mapRef,
            orthoRef,
            tileVersion: result.tile_version,
          })
        )
          return;
        boundsRef.current = L.latLngBounds(result.bounds);
        clearTileClip();
        setIndexAnalyses([]);
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
        setState((current) => ({
          ...current,
          orthoMode: type,
          sensor,
          orthomosaicId: upload.orthomosaic.id,
          rgb: true,
          trees: false,
          labels: false,
          ndvi: false,
          vari: false,
          exg: false,
          swipe: false,
          roiSelected: false,
          selectedRoiId: null,
          selectedRoiIds: [],
        }));
        restoreRoiSelection(persistentRoiSelections);
        if (type === "multispectral") {
          if (!result.ndvi_matrix)
            throw new Error(
              "El backend no devolvió la matriz NDVI del ortomosaico.",
            );
          const response: NdviResponse = {
            ...createNdviResponse(result.bounds, result.mask, result.ndvi_matrix),
          };
          const stats = ndviStats(response);
          ndviResponseRef.current = response;
          ndviRangeRef.current = {
            min: response.range_min ?? stats.min,
            max: response.range_max ?? stats.max,
          };
          setNdviAnalysis(createEmptyNdviAnalysis());
          setState((current) => ({
            ...current,
            ndvi: false,
            loaded: true,
            error: null,
          }));
          return;
        }
        uploadedRgbRef.current?.remove();
        uploadedRgbRef.current = undefined;
        setState((current) => ({ ...current, loaded: true, error: null }));
      } catch (error) {
        setState((current) => ({
          ...current,
          error:
            error instanceof Error
              ? error.message
              : "No se pudo procesar el ortomosaico",
        }));
      } finally {
        setState((current) => ({ ...current, uploading: false }));
      }
    },
    [clearPrescription, clearTileClip, restoreRoiSelection],
  );

  /** Actualiza contraste y URL de tiles para un índice adicional activo. */
  const setIndexRange = useCallback(
    (name: IndexAnalysis["name"], minimum: number, maximum: number) => {
      const safeMinimum = Math.min(minimum, maximum);
      const safeMaximum = Math.max(minimum, maximum);
      setIndexAnalyses((current) =>
        current.map((analysis) =>
          analysis.name === name
            ? { ...analysis, minimum: safeMinimum, maximum: safeMaximum }
            : analysis,
        ),
      );
      const cropId = activeCropIdRef.current;
      const layer = indexRefs.current.get(name) as L.TileLayer | undefined;
      if (layer?.setUrl)
        layer.setUrl(
          cropId
            ? backendUrl(
                `/tiles/crop-index/${name}/${cropId}/{z}/{x}/{y}.png?low=${safeMinimum}&high=${safeMaximum}`,
              )
            : backendUrl(
                `/tiles/index/${name}/{z}/{x}/{y}.png?low=${safeMinimum}&high=${safeMaximum}`,
              ),
        );
    },
    [],
  );

  /**
   * Activa NDVI, NDWI o NDRE eligiendo automáticamente datos globales o los
   * resultados del recorte ROI vigente.
   */
  const selectIndex = useCallback(
    async (name: "NDVI" | IndexAnalysis["name"]) => {
      try {
        if (state.orthoMode !== "multispectral")
          throw new Error(
            "Carga un ortomosaico multiespectral para calcular índices.",
          );
        const map = mapRef.current;
        if (!map) return;
        if (name === "NDVI") {
          const roiResponse = roiIndexResponsesRef.current?.NDVI;
          const cropId = activeCropIdRef.current;
          const response =
            roiResponse ??
            ndviResponseRef.current ??
            (await dashboardApi.ndvi());
          ndviResponseRef.current = response;
          const stats = ndviStats(response);
          const defaultMinimum = response.range_min ?? stats.min;
          const defaultMaximum = response.range_max ?? stats.max;
          ndviRangeRef.current = { min: defaultMinimum, max: defaultMaximum };
          setNdviAnalysis((current) => ({
            ...current,
            response,
            stats,
            roiResponse: roiResponse ?? null,
            roiStats: roiResponse ? stats : current.roiStats,
            minimum: defaultMinimum,
            maximum: defaultMaximum,
          }));
          ndviRef.current?.remove();
          if (roiResponse && cropId) {
            replaceNdviTileLayer({
              mapRef,
              ndviTileRef,
              url: backendUrl(`/tiles/crop-index/NDVI/${cropId}/{z}/{x}/{y}.png`),
            });
            setState((current) => ({ ...current, ndvi: true, error: null }));
            return;
          }
          ndviTileRef.current ??= createSpectralTileLayer(
            backendUrl("/tiles/index/NDVI/{z}/{x}/{y}.png"),
          );
          ndviTileRef.current.addTo(map);
          setState((current) => ({ ...current, ndvi: true, error: null }));
          return;
        }
        const cropId = activeCropIdRef.current;
        if (cropId) {
          const cachedResponse = roiIndexResponsesRef.current?.[name];
          const roiGeometry =
            activeCropGeometryRef.current ?? selectedRoiRef.current;
          const roiResponse =
            cachedResponse ??
            (roiGeometry
              ? await dashboardApi.roiVegetationIndex(name, roiGeometry)
              : null);
          if (!roiResponse)
            throw new Error(
              `Selecciona y recorta un ROI antes de activar ${name}.`,
            );
          roiIndexResponsesRef.current = {
            ...roiIndexResponsesRef.current,
            [name]: roiResponse,
          };
          const stats = ndviStats(roiResponse);
          const defaultMinimum = roiResponse.range_min ?? stats.min;
          const defaultMaximum = roiResponse.range_max ?? stats.max;
          setIndexAnalyses((current) => [
            ...current.filter((item) => item.name !== name),
            {
              name,
              response: roiResponse,
              stats,
              minimum: defaultMinimum,
              maximum: defaultMaximum,
              visible: true,
            },
          ]);
          renderIndex(name, roiResponse, defaultMinimum, defaultMaximum);
          replaceSpectralLayer({
            indexRefs,
            mapRef,
            name,
            url: backendUrl(`/tiles/crop-index/${name}/${cropId}/{z}/{x}/{y}.png`),
          });
          setState((current) => ({ ...current, error: null }));
          return;
        }
        const response = await dashboardApi.vegetationIndex(name);
        const stats = ndviStats(response);
        const defaultMinimum = response.range_min ?? stats.min;
        const defaultMaximum = response.range_max ?? stats.max;
        setIndexAnalyses((current) => [
          ...current.filter((item) => item.name !== name),
          {
            name,
            response,
            stats,
            minimum: defaultMinimum,
            maximum: defaultMaximum,
            visible: true,
          },
        ]);
        renderIndex(name, response, defaultMinimum, defaultMaximum);
        replaceSpectralLayer({
          indexRefs,
          mapRef,
          name,
          url: backendUrl(`/tiles/index/${name}/{z}/{x}/{y}.png`),
        });
        setState((current) => ({ ...current, error: null }));
      } catch (error) {
        setState((current) => ({
          ...current,
          error:
            error instanceof Error
              ? error.message
              : "No se pudo calcular el índice.",
        }));
      }
    },
    [renderIndex, state.orthoMode],
  );

  /** Retira todas las capas espectrales sin modificar el ortomosaico RGB. */
  const hideIndices = useCallback(() => {
    clearSpectralLayers({ indexRefs, ndviRef, ndviTileRef });
    setNdviAnalysis((current) => ({
      ...current,
      response: null,
      roiResponse: null,
    }));
    setIndexAnalyses([]);
    setState((current) => ({
      ...current,
      ndvi: false,
      vari: false,
      exg: false,
    }));
  }, []);

  /** Oculta NDVI y restablece su indicador sin alterar otros índices. */
  const hideNdvi = useCallback(() => {
    ndviRef.current?.remove();
    ndviTileRef.current?.remove();
    ndviTileRef.current = undefined;
    setNdviAnalysis((current) => ({
      ...current,
      response: null,
      roiResponse: null,
    }));
    setState((current) => ({ ...current, ndvi: false }));
  }, []);

  /** Retira una única capa NDWI o NDRE y su tarjeta analítica. */
  const hideIndex = useCallback((name: IndexAnalysis["name"]) => {
    removeSingleSpectralLayer({ indexRefs, name });
    setIndexAnalyses((current) => current.filter((item) => item.name !== name));
  }, []);

  /** Compatibilidad interna para alternar NDVI desde flujos existentes. */
  const toggleNdvi = useCallback(async () => {
    try {
      if (state.orthoMode !== "multispectral") {
        setState((current) => ({
          ...current,
          error: "El análisis NDVI requiere un ortomosaico multiespectral.",
        }));
        return;
      }
      if (!ndviResponseRef.current) {
        setState((current) => ({
          ...current,
          error: "Importa un ortomosaico multiespectral antes de activar NDVI.",
        }));
        return;
      }
      const map = mapRef.current;
      const layer = ndviRef.current ?? ndviTileRef.current;
      if (!map || !layer) return;
      if (map.hasLayer(layer)) {
        map.removeLayer(layer);
        setState((current) => ({ ...current, ndvi: false }));
      } else {
        layer.addTo(map);
        setState((current) => ({ ...current, ndvi: true }));
      }
    } catch (error) {
      setState((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "Error cargando NDVI",
      }));
    }
  }, [state.orthoMode]);

  /** Enciende o apaga una capa NDWI/NDRE sin retirar su panel analítico. */
  const toggleIndexLayer = useCallback((name: IndexAnalysis["name"]) => {
    const map = mapRef.current;
    const layer = indexRefs.current.get(name);
    if (!map || !layer) return;
    const visible = map.hasLayer(layer);
    if (visible) map.removeLayer(layer);
    else layer.addTo(map);
    setIndexAnalyses((current) =>
      current.map((analysis) =>
        analysis.name === name ? { ...analysis, visible: !visible } : analysis,
      ),
    );
  }, []);

  /** Sincroniza el rango NDVI del panel con la capa global o recortada. */
  const setNdviRange = useCallback(
    (minimum: number, maximum: number) => {
      const safeMinimum = Math.min(minimum, maximum);
      const safeMaximum = Math.max(minimum, maximum);
      ndviRangeRef.current = { min: safeMinimum, max: safeMaximum };
      setNdviAnalysis((current) => ({
        ...current,
        minimum: safeMinimum,
        maximum: safeMaximum,
      }));
      if (ndviTileRef.current) {
        const cropId = activeCropIdRef.current;
        ndviTileRef.current.setUrl(
          cropId
            ? backendUrl(
                `/tiles/crop-index/NDVI/${cropId}/{z}/{x}/{y}.png?low=${safeMinimum}&high=${safeMaximum}`,
              )
            : backendUrl(
                `/tiles/ndvi/{z}/{x}/{y}.png?low=${safeMinimum}&high=${safeMaximum}`,
              ),
        );
      } else if (ndviResponseRef.current) renderNdvi(ndviResponseRef.current);
    },
    [renderNdvi],
  );

  /** Muestra u oculta detecciones conservando la capa para reutilizarla. */
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

  /** Habilita en Geoman una única operación de dibujo poligonal. */
  const drawRoi = useCallback(() => {
    if (state.orthoMode !== "multispectral") {
      setState((current) => ({
        ...current,
        error:
          "Carga un ortomosaico multiespectral antes de dibujar una región de interés.",
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

  /** Importa, guarda y selecciona de forma aditiva todas las geometrías válidas. */
  const importRoi = useCallback(
    async (files: File[]) => {
      try {
        if (!activeCycleId)
          throw new Error(
            "Selecciona un ciclo agrícola antes de importar una región de interés.",
          );
        if (state.orthoMode !== "multispectral")
          throw new Error(
            "Carga un ortomosaico multiespectral antes de analizar una región de interés.",
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
            "La geometría importada debe contener al menos un polígono.",
          );
        const map = mapRef.current;
        if (!map) return;
        const roi = { type: "FeatureCollection" as const, features };
        const layer = L.geoJSON(roi, {
          style: {
            color: "#ff3b30",
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
            // El ROI se guarda como geometría reutilizable para cualquier vuelo.
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
              : "No se pudo analizar la región importada.",
        }));
      }
    },
    [activeCycleId, selectRoi, state.orthoMode],
  );

  /** Alterna el grupo de etiquetas de diámetro sin volver a crear el mapa. */
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
        reportProgress?.(34, "Interpretando geometrías...");
        const rawCollection = await parseDetectionFiles(files);
        rawTreeDataRef.current = rawCollection;
        const parsed = normalizeTreeCollection(rawCollection);
        await waitForPaint();

        reportProgress?.(54, "Normalizando diámetros en el servidor...");
        let collection = parsed;
        try {
          const normalized = await dashboardApi.treePoints(parsed);
          collection = normalizeTreeCollection(normalized.geojson);
        } catch {
          // El render local mantiene operativo el mapa si la API está apagada.
          reportProgress?.(
            62,
            "Backend no disponible; usando datos locales...",
          );
        }
        await waitForPaint();

        reportProgress?.(70, "Clasificando tamaños...");
        const allSizesVisible = { small: true, medium: true, large: true };
        treeDataRef.current = collection;
        diameterRangeRef.current = { min: -Infinity, max: Infinity };
        visibleTreeSizesRef.current = allSizesVisible;
        // El diámetro físico es la vista principal; el usuario puede volver a puntos.
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

  /** Cambia entre símbolos puntuales y círculos con diámetro físico en metros. */
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

  /** Asigna un atributo numérico como diámetro y reconstruye todo el análisis. */
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
              : "No se pudo asignar el campo de diámetro.",
        }));
      }
    },
    [refreshLabels, renderTreeLayer, syncTreeLayerVisibility],
  );

  /** Espera un clic sobre el mapa y agrega una detección con diámetro conocido. */
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
        // La primera detección manual inaugura y muestra la capa; las
        // siguientes respetan la visibilidad que el usuario ya eligió.
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

  /** Permite eliminar la siguiente detección pulsada directamente en el mapa. */
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

  /** Dibuja un rectángulo sombreado y elimina todas las detecciones interiores. */
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

  /** Importa árboles, crea popups seguros y ajusta el mapa a su extensión. */
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
          ndviRangeRef.current = { min: defaultMinimum, max: defaultMaximum };
          setNdviAnalysis((current) => ({
            ...current,
            response,
            stats,
            roiResponse: response,
            roiStats: stats,
            minimum: defaultMinimum,
            maximum: defaultMaximum,
          }));
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
          error: error instanceof Error ? error.message : "GeoJSON inválido",
        }));
      }
    },
    [renderNdvi, state.orthoMode],
  );

  /** Aplica el filtro de diámetro tanto a símbolos como a etiquetas. */
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

  /** Alterna la visibilidad del ortomosaico base y recupera su extensión. */
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

  /** Activa un vuelo persistido y elimina cualquier análisis del vuelo anterior. */
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
    const image = ndviRef.current?.getElement();
    if (image) image.style.clipPath = `inset(0 0 0 ${next}%)`;
    indexRefs.current.forEach((layer) => {
      const indexImage =
        layer instanceof L.ImageOverlay
          ? layer.getElement()
          : layer instanceof L.TileLayer
            ? layer.getContainer()
            : undefined;
      if (indexImage) indexImage.style.clipPath = `inset(0 0 0 ${next}%)`;
    });
  }, []);

  /** Activa o elimina el recorte visual del divisor sin destruir las capas. */
  const toggleSwipe = useCallback(() => {
    setState((current) => {
      const enabled = !current.swipe;
      swipeEnabledRef.current = enabled;
      const image = ndviRef.current?.getElement();
      if (image)
        image.style.clipPath = enabled
          ? `inset(0 0 0 ${current.swipePosition}%)`
          : "none";
      swipeEnabledRef.current = enabled;
      indexRefs.current.forEach((layer) => {
        const indexImage =
          layer instanceof L.ImageOverlay
            ? layer.getElement()
            : layer instanceof L.TileLayer
              ? layer.getContainer()
              : undefined;
        if (indexImage)
          indexImage.style.clipPath = enabled
            ? `inset(0 0 0 ${current.swipePosition}%)`
            : "none";
      });
      return { ...current, swipe: enabled };
    });
  }, []);

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
  }, [cancelDetectionEdit, clearPrescription, clearRoiSelection]);

  return {
    state,
    treeData,
    filteredTreeData,
    ndviAnalysis,
    indexAnalyses,
    zoning,
    zoningLoading,
    prescription,
    prescriptionLoading,
    prescriptionAreaReady,
    cropAvailable,
    cropExporting,
    generateZoning,
    previewZoning,
    generatePrescription,
    clearPrescription,
    clearZoning,
    clearZoningPreview,
    selectIndex,
    hideIndices,
    hideNdvi,
    hideIndex,
    toggleNdvi,
    toggleIndexLayer,
    drawRoi,
    drawPrescriptionArea,
    importRoi,
    selectRoi,
    clearRoiSelection,
    removeRoiPolygon,
    cropSelectedRoi,
    exportCrop,
    toggleTrees,
    toggleLabels,
    importDetections,
    setTreeDisplayMode,
    setTreeDiameterField,
    startAddDetection,
    startDeleteDetection,
    startDeleteDetectionsArea,
    cancelDetectionEdit,
    toggleTreeSize,
    importFile,
    importOrtho,
    fitRgb,
    activateStoredOrtho,
    resetWorkspace,
    toggleSwipe,
    setSwipePosition,
    setDiameterRange,
    setNdviRange,
    setIndexRange,
  };
}
