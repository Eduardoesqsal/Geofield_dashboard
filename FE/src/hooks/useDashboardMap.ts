/**
 * Hook central del dashboard geoespacial.
 * Coordina mapa Leaflet, ortomosaicos, ROI, Ã­ndices, histogramas, diÃ¡logos,
 * trazabilidad y sincronizaciÃ³n con el backend.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import L from "leaflet";
import type { Feature, FeatureCollection, GeoJsonObject } from "geojson";
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
  buildHistogramEqualization,
  equalizedPosition,
  type ClassificationFillMode,
  type HistogramEqualization,
  indexColorFromPosition,
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
  removeSingleSpectralLayer,
  replaceNdviTileLayer,
  replaceSpectralLayer,
} from "./useDashboardMap.spectral";
import { useDashboardMapPrescription } from "./useDashboardMap.prescription";
import { useDashboardMapRoi } from "./useDashboardMap.roiActions";
import { useDashboardMapTreeCore } from "./useDashboardMap.treeCore";
import { useDashboardMapTreeActions } from "./useDashboardMap.treeActions";
import { useDashboardMapWorkspace } from "./useDashboardMap.workspace";
import { useDashboardMapSpectralActions } from "./useDashboardMap.spectralActions";

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

/** Datos, estadÃ­sticas y rango visible de la capa NDVI actual. */
export interface NdviAnalysis {
  response: NdviResponse | null;
  stats: NdviStats;
  roiResponse: NdviResponse | null;
  roiStats: NdviStats;
  minimum: number;
  maximum: number;
  equalized: boolean;
  fillMode: ClassificationFillMode;
}

/** Estado equivalente para Ã­ndices adicionales que pueden coexistir. */
export interface IndexAnalysis {
  name: "NDWI" | "NDRE";
  response: NdviResponse;
  stats: NdviStats;
  minimum: number;
  maximum: number;
  visible: boolean;
  equalized: boolean;
  fillMode: ClassificationFillMode;
}

/**
 * Orquesta el ciclo de vida de Leaflet, sus capas imperativas y las llamadas
 * geoespaciales. React recibe solo estados derivados y acciones estables.
 */
export function useDashboardMap(
  mapElement: React.RefObject<HTMLDivElement>,
  activeCycleId: string | null,
) {
  // Recursos Leaflet: cada referencia representa una capa Ãºnica y reemplazable.
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
  const zoningPreviewGridRef = useRef<L.GeoJSON>();
  const prescriptionRef = useRef<L.TileLayer>();
  const classificationFillRef = useRef<L.GeoJSON>();
  const classificationGridRef = useRef<L.GeoJSON>();
  const prescriptionAreaLayerRef = useRef<L.Layer>();
  const prescriptionGeometryRef = useRef<unknown>(null);
  const prescriptionDrawCompleteRef = useRef<(() => void) | null>(null);
  const livePrescriptionGridRef = useRef<SVGSVGElement | null>(null);
  const livePrescriptionGridCleanupRef = useRef<(() => void) | null>(null);
  const zoningPreviewAbortRef = useRef<AbortController | null>(null);
  const zoningPreviewTokenRef = useRef(0);
  const cancelDetectionEditHandlerRef = useRef<() => void>(() => {});
  const commitTreeCollectionHandlerRef = useRef<
    (collection: TreeCollection, visible?: boolean) => void
  >(() => {});
  const selectRoiHandlerRef = useRef<
    (geojson: unknown, roiId?: string | null) => void
  >(() => {});
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
  const ndviRangeRef = useRef<{
    min: number;
    max: number;
    equalized: boolean;
    fillMode: ClassificationFillMode;
    values: number[];
  }>({
    min: -1,
    max: 1,
    equalized: false,
    fillMode: "transparent",
    values: [],
  });
  const ndviResponseRef = useRef<NdviResponse | null>(null);
  // SelecciÃ³n ROI, recorte activo y respuestas espectrales asociadas.
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

  const {
    clearClassificationFill,
    clearClassificationGrid,
    clearLivePrescriptionGrid,
    clearPrescription,
    clearPrescriptionArea,
    clearZoning,
    clearZoningPreview,
    generatePrescription,
    generateZoning,
    mountClassificationFill,
    mountClassificationGrid,
    previewZoning,
    setLivePrescriptionRotation,
  } = useDashboardMapPrescription({
    activeAnalysisRange,
    activeCropGeometryRef,
    boundsRef,
    classificationFillRef,
    classificationGridRef,
    indexAnalyses,
    livePrescriptionGridCleanupRef,
    livePrescriptionGridRef,
    mapRef,
    ndviAnalysis,
    prescription,
    prescriptionAreaLayerRef,
    prescriptionDrawCompleteRef,
    prescriptionGeometryRef,
    prescriptionRef,
    setPrescription,
    setPrescriptionAreaReady,
    setPrescriptionLoading,
    setState,
    setZoning,
    setZoningLoading,
    state,
    zoning,
    zoningPreviewAbortRef,
    zoningPreviewGridRef,
    zoningPreviewRef,
    zoningPreviewTokenRef,
    zoningRef,
  });
  const {
    cancelDetectionEdit,
    commitTreeCollection,
    refreshLabels,
    renderClassificationPixel,
    renderTreeLayer,
    syncTreeLayerVisibility,
  } = useDashboardMapTreeCore({
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
  });
  const shouldRenderIndexAsTiles = useCallback(
    (_equalized: boolean, _fillMode: ClassificationFillMode) => true,
    [],
  );

  const spectralTileUrl = useCallback(
    (
      name: "NDVI" | IndexAnalysis["name"],
      minimum: number,
      maximum: number,
      cropId: string | null,
      equalized = false,
      fillMode: ClassificationFillMode = "transparent",
    ) => {
      const safeMinimum = Math.min(minimum, maximum);
      const safeMaximum = Math.max(minimum, maximum);
      const params = `low=${safeMinimum}&high=${safeMaximum}&equalized=${equalized ? "true" : "false"}&fill_mode=${fillMode}`;
      if (cropId)
        return backendUrl(
          `/tiles/crop-index/${name}/${cropId}/{z}/{x}/{y}.png?${params}`,
        );
      return backendUrl(
        `/tiles/index/${name}/{z}/{x}/{y}.png?${params}`,
      );
    },
    [],
  );

  const activeCropRing = useCallback((): number[][] | null => {
    const source = activeCropGeometryRef.current as {
      type?: string;
      geometry?: unknown;
      coordinates?: unknown;
    } | null;
    const geometry =
      source?.type === "Feature"
        ? (source.geometry as { type?: string; coordinates?: unknown })
        : source;
    if (!geometry) return null;
    if (geometry.type === "Polygon")
      return (geometry.coordinates as number[][][])[0] ?? null;
    if (geometry.type === "MultiPolygon")
      return (geometry.coordinates as number[][][][])[0]?.[0] ?? null;
    return null;
  }, []);

  const currentSpectralClipPath = useCallback(() => {
    const map = mapRef.current;
    const ring = activeCropRing();
    if (map && ring?.length) {
      const points = ring.map(([longitude, latitude]) =>
        map.latLngToLayerPoint([latitude, longitude]),
      );
      return `polygon(${points.map((point) => `${point.x}px ${point.y}px`).join(", ")})`;
    }
    if (swipeEnabledRef.current) return `inset(0 0 0 ${ratioRef.current * 100}%)`;
    return "none";
  }, [activeCropRing]);

  const syncSpectralClip = useCallback(() => {
    const clipPath = currentSpectralClipPath();
    const image = ndviRef.current?.getElement();
    if (image) image.style.clipPath = clipPath;
    indexRefs.current.forEach((layer) => {
      const element =
        layer instanceof L.ImageOverlay
          ? layer.getElement()
          : layer instanceof L.TileLayer
            ? layer.getContainer()
            : undefined;
      if (element) element.style.clipPath = clipPath;
    });
  }, [currentSpectralClipPath]);

  /** Rasteriza NDVI en canvas aplicando mÃ¡scara, rampa y rango seleccionado. */
  const renderNdvi = useCallback((response: NdviResponse) => {
    const matrix = response.matrix;
    if (!matrix?.length) return;

    const canvas = document.createElement("canvas");
    canvas.width = matrix[0].length;
    canvas.height = matrix.length;
    const context = canvas.getContext("2d");
    if (!context) return;

    const image = context.createImageData(canvas.width, canvas.height);
    const {
      min,
      max,
      equalized,
      fillMode,
      values,
    } = ndviRangeRef.current;
    if (shouldRenderIndexAsTiles(equalized, fillMode)) {
      ndviRef.current?.remove();
      replaceNdviTileLayer({
        mapRef,
        ndviTileRef,
        url: spectralTileUrl(
          "NDVI",
          min,
          max,
          activeCropIdRef.current,
          equalized,
          fillMode,
        ),
      });
      return;
    }
    const equalization = equalized
      ? buildHistogramEqualization(values, min, max)
      : null;

    matrix.forEach((row, y) =>
      row.forEach((value, x) => {
        // El backend devuelve NDVI como byte normalizado (0..255).
        // Aceptar tambiÃ©n el rango NDVI clÃ¡sico (-1..1) para mantener el
        // cliente compatible con implementaciones anteriores.
        const numericValue = Number(value);
        const canonicalValue =
          numericValue > 1 ? (numericValue / 255) * 2 - 1 : numericValue;
        const position = (y * canvas.width + x) * 4;
        const maskValue = response.mask?.[y]?.[x];
        const validMask = maskValue === undefined || Number(maskValue) > 0;
        if (!validMask || !Number.isFinite(canonicalValue)) {
          image.data[position + 3] = 0;
          return;
        }
        const rendered = renderClassificationPixel(
          "NDVI",
          canonicalValue,
          min,
          max,
          fillMode,
          equalization,
        );
        if (!rendered) {
          image.data[position + 3] = 0;
          return;
        }
        image.data[position] = rendered.color[0];
        image.data[position + 1] = rendered.color[1];
        image.data[position + 2] = rendered.color[2];
        image.data[position + 3] = rendered.alpha;
      }),
    );

    context.putImageData(image, 0, 0);
    const map = mapRef.current;
    const overlayBounds = response.bounds
      ? L.latLngBounds(response.bounds)
      : boundsRef.current;
    if (!map || !overlayBounds) return;

    ndviTileRef.current?.remove();
    ndviTileRef.current = undefined;
    ndviRef.current?.remove();
    ndviRef.current = L.imageOverlay(canvas.toDataURL(), overlayBounds, {
      opacity: 1,
      interactive: false,
      pane: "classificationImagePane",
    }).addTo(map);
    const overlayImage = ndviRef.current.getElement();
    if (overlayImage) overlayImage.style.clipPath = currentSpectralClipPath();
  }, [
    currentSpectralClipPath,
    renderClassificationPixel,
    shouldRenderIndexAsTiles,
    spectralTileUrl,
  ]);

  const {
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
  } = useDashboardMapRoi({
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
  });
  useEffect(() => {
    cancelDetectionEditHandlerRef.current = cancelDetectionEdit;
  }, [cancelDetectionEdit]);

  useEffect(() => {
    commitTreeCollectionHandlerRef.current = commitTreeCollection;
  }, [commitTreeCollection]);

  useEffect(() => {
    selectRoiHandlerRef.current = selectRoi;
  }, [selectRoi]);

  /** Renderizador local de respaldo para matrices NDWI y NDRE. */
  const renderIndex = useCallback(
    (
      name: IndexAnalysis["name"],
      response: NdviResponse,
      minimum: number,
      maximum: number,
      equalized: boolean,
      fillMode: ClassificationFillMode,
      values: number[],
    ) => {
      if (shouldRenderIndexAsTiles(equalized, fillMode)) {
        replaceSpectralLayer({
          indexRefs,
          mapRef,
          name,
          url: spectralTileUrl(
            name,
            minimum,
            maximum,
            activeCropIdRef.current,
            equalized,
            fillMode,
          ),
        });
        return;
      }
      const matrix = response.matrix;
      if (!matrix?.length || !matrix[0]?.length) return;
      const canvas = document.createElement("canvas");
      canvas.width = matrix[0].length;
      canvas.height = matrix.length;
      const context = canvas.getContext("2d");
      if (!context || !boundsRef.current) return;
      const image = context.createImageData(canvas.width, canvas.height);
      const equalization = equalized
        ? buildHistogramEqualization(values, minimum, maximum)
        : null;
      matrix.forEach((row, y) =>
        row.forEach((value, x) => {
          const normalized = Number(value);
          const position = (y * canvas.width + x) * 4;
          const validMask =
            response.mask?.[y]?.[x] === undefined || Number(response.mask[y][x]) > 0;
          if (!validMask || !Number.isFinite(normalized)) {
            image.data[position + 3] = 0;
            return;
          }
          const rendered = renderClassificationPixel(
            name,
            normalized,
            minimum,
            maximum,
            fillMode,
            equalization,
          );
          if (!rendered) {
            image.data[position + 3] = 0;
            return;
          }
          image.data[position] = rendered.color[0];
          image.data[position + 1] = rendered.color[1];
          image.data[position + 2] = rendered.color[2];
          image.data[position + 3] = rendered.alpha;
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
        {
          opacity: 1,
          interactive: false,
          pane: "classificationImagePane",
        },
      ).addTo(map);
      indexRefs.current.set(name, overlay);
      const overlayImage = overlay.getElement();
      if (overlayImage) overlayImage.style.clipPath = currentSpectralClipPath();
    },
    [
      currentSpectralClipPath,
      renderClassificationPixel,
      shouldRenderIndexAsTiles,
      spectralTileUrl,
    ],
  );

  // InicializaciÃ³n Ãºnica del mapa base, Geoman y listeners de creaciÃ³n de ROI.
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
        attribution: "Tiles Â© Esri",
        maxNativeZoom: 18,
        maxZoom: 24,
        updateWhenZooming: false,
        keepBuffer: 4,
      },
    );
    const labels = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: "Labels Â© Esri",
        maxNativeZoom: 18,
        maxZoom: 24,
        updateWhenZooming: false,
        keepBuffer: 4,
      },
    );

    L.layerGroup([satellite, labels]).addTo(map);
    L.control.zoom({ position: "topright" }).addTo(map);
    map.createPane("classificationImagePane");
    const classificationImagePane = map.getPane("classificationImagePane");
    if (classificationImagePane) {
      classificationImagePane.style.zIndex = "520";
      classificationImagePane.style.pointerEvents = "none";
    }
    map.createPane("classificationFillPane");
    const classificationFillPane = map.getPane("classificationFillPane");
    if (classificationFillPane) {
      classificationFillPane.style.zIndex = "521";
      classificationFillPane.style.pointerEvents = "none";
    }
    map.createPane("classificationGridPane");
    const classificationGridPane = map.getPane("classificationGridPane");
    if (classificationGridPane) {
      classificationGridPane.style.zIndex = "522";
      classificationGridPane.style.pointerEvents = "none";
    }
    map.createPane("classificationPreviewPane");
    const classificationPreviewPane = map.getPane("classificationPreviewPane");
    if (classificationPreviewPane) {
      classificationPreviewPane.style.zIndex = "523";
      classificationPreviewPane.style.pointerEvents = "none";
    }
    map.createPane("classificationPreviewGridPane");
    const classificationPreviewGridPane = map.getPane(
      "classificationPreviewGridPane",
    );
    if (classificationPreviewGridPane) {
      classificationPreviewGridPane.style.zIndex = "524";
      classificationPreviewGridPane.style.pointerEvents = "none";
    }
    map.createPane("treeLabelsPane");
    const pane = map.getPane("treeLabelsPane");
    if (pane) {
      pane.style.zIndex = "650";
      pane.style.pointerEvents = "none";
    }

    map.pm?.setGlobalOptions({
      pathOptions: {
        color: "#ffffff",
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
          cancelDetectionEditHandlerRef.current();
          commitTreeCollectionHandlerRef.current(collection);
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
            "Selecciona un ciclo agrÃ­cola antes de guardar una regiÃ³n de interÃ©s.",
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
          selectRoiHandlerRef.current(roiGeojson, saved.roi.id);
        });
        selectRoiHandlerRef.current(roiGeojson, saved.roi.id);
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
    mapElement,
    updateTileClip,
  ]);

  const {
    hideIndex,
    hideIndices,
    hideNdvi,
    importOrtho,
    selectIndex,
    setIndexEqualization,
    setIndexFillMode,
    setIndexRange,
    setNdviEqualization,
    setNdviFillMode,
    setNdviRange,
    toggleIndexLayer,
    toggleNdvi,
  } = useDashboardMapSpectralActions({
    activeCropGeometryRef,
    activeCropIdRef,
    boundsRef,
    clearPrescription,
    clearTileClip,
    cropControlRef,
    indexAnalyses,
    indexRefs,
    labelsRef,
    mapRef,
    ndviAnalysis,
    ndviRangeRef,
    ndviRef,
    ndviResponseRef,
    ndviTileRef,
    orthoRef,
    renderIndex,
    renderNdvi,
    restoreRoiSelection,
    roiIndexResponsesRef,
    selectedRoiRef,
    selectedRoisRef,
    setFilteredTreeData,
    setIndexAnalyses,
    setNdviAnalysis,
    setState,
    setTreeData,
    state,
    treeDataRef,
    treeRef,
    uploadedRgbRef,
  });
  const {
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
  } = useDashboardMapTreeActions({
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
  });
  const {
    activateStoredOrtho,
    exportCrop,
    fitRgb,
    resetWorkspace,
    setSwipePosition,
    toggleSwipe,
  } = useDashboardMapWorkspace({
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
  });
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
    setLivePrescriptionRotation,
    clearLivePrescriptionGrid,
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
    setNdviEqualization,
    setNdviFillMode,
    setIndexRange,
    setIndexEqualization,
    setIndexFillMode,
  };
}







