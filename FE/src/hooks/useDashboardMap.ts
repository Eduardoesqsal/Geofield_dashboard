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
  type AgriculturalCycleRecord,
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
import { createVariDiameterTileLayer } from "../utils/variDetections";
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
  INDEX_TILE_VERSION,
  clearSpectralLayers,
  createNdviResponse,
  removeSingleSpectralLayer,
  replaceNdviTileLayer,
  replaceSpectralLayer,
} from "./useDashboardMap.spectral";
import { useDashboardMapPrescription } from "./useDashboardMap.prescription";
import { useDashboardMapRoi } from "./useDashboardMap.roiActions";
import { useDashboardMapTreeCore } from "./useDashboardMap.treeCore";
import { useDetectionPersistence } from "./useDashboardMap.detectionsPersistence";
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
  name: "NDWI" | "NDRE" | "VARI";
  response: NdviResponse;
  stats: NdviStats;
  minimum: number;
  maximum: number;
  visible: boolean;
  equalized: boolean;
  fillMode: ClassificationFillMode;
}

interface PublicationContext {
  cycle: AgriculturalCycleRecord | null;
  orthomosaic: OrthomosaicRecord | null;
}

function statsPayload(
  stats: NdviStats,
  rangeMinimum: number,
  rangeMaximum: number,
) {
  return {
    count: stats.count,
    min: stats.min,
    max: stats.max,
    mean: stats.mean,
    median: stats.median,
    standard_deviation: stats.standardDeviation,
    p10: stats.percentiles.p10,
    p25: stats.percentiles.p25,
    p75: stats.percentiles.p75,
    p90: stats.percentiles.p90,
    range_min: rangeMinimum,
    range_max: rangeMaximum,
  };
}

function artifactsForPublication(
  zoning: NdviZoningResponse | null,
  prescription: PrescriptionMapResponse | null,
) {
  const artifacts: Array<Record<string, unknown>> = [];
  const response = prescription ?? zoning;
  if (!response) return artifacts;
  if (response.tile_url) {
    artifacts.push({
      artifact_type: response.stage === "prescription" ? "prescription_tiles" : "zoning_tiles",
      name: response.title,
      url: response.tile_url,
      metadata: { stage: response.stage },
    });
  }
  if (response.grid_url) {
    artifacts.push({
      artifact_type: "grid_geojson",
      name: `${response.title} grid`,
      url: response.grid_url,
      metadata: { stage: response.stage },
    });
  }
  if (response.geojson_url) {
    artifacts.push({
      artifact_type: response.stage === "prescription" ? "prescription_geojson" : "zoning_geojson",
      name: `${response.title} geojson`,
      url: response.geojson_url,
      metadata: { stage: response.stage },
    });
  }
  if (prescription?.json_url) {
    artifacts.push({
      artifact_type: "prescription_json",
      name: "Prescripcion JSON",
      url: prescription.json_url,
      storage_key: `prescriptions/${prescription.prescription_id}.json`,
      metadata: { stage: "prescription" },
    });
  }
  return artifacts;
}

function currentPublicationKey(
  orthomosaicId: string,
  roiId: string,
  zoning: NdviZoningResponse | null,
  prescription: PrescriptionMapResponse | null,
) {
  return [
    orthomosaicId,
    roiId,
    prescription?.prescription_id ?? zoning?.zoning_id ?? "indices",
  ].join(":");
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
  const diameterFillEnabledRef = useRef(true);
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
  const orthoModeRef = useRef(state.orthoMode);
  orthoModeRef.current = state.orthoMode;
  const [treeData, setTreeData] = useState<TreeCollection | null>(null);
  const [diameterFillEnabled, setDiameterFillEnabled] = useState(true);
  const [filteredTreeData, setFilteredTreeData] =
    useState<TreeCollection | null>(null);
  const [ndviAnalysis, setNdviAnalysis] = useState<NdviAnalysis>(
    createEmptyNdviAnalysis(),
  );
  const [indexAnalyses, setIndexAnalyses] = useState<IndexAnalysis[]>([]);
  const [variDetectionsEnabled, setVariDetectionsEnabled] = useState(false);
  const [variDetectionStyle, setVariDetectionStyle] = useState<{
    minimum: number;
    maximum: number;
    equalized: boolean;
    fillMode: ClassificationFillMode;
    cropId: string | null;
  } | null>(null);
  const variResponseRef = useRef<NdviResponse | null>(null);
  const variLoadFailedRef = useRef(false);
  const variDetectionOverlayRef = useRef<L.GridLayer>();
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
    diameterFillEnabledRef,
    diameterRangeRef,
    labelsEnabledRef,
    labelsRef,
    mapRef,
    orthoModeRef,
    rawTreeDataRef,
    setFilteredTreeData,
    setState,
    setTreeData,
    treeDataRef,
    treeDisplayModeRef,
    treeRef,
    variResponseRef,
    variLoadFailedRef,
    visibleTreeSizesRef,
  });
  const {
    activeOrthomosaicIdRef,
    detectionLoadTokenRef,
    saveDetectionsNow,
    commitAndPersistDetections,
    reloadDetections,
  } = useDetectionPersistence({
    orthomosaicId: state.orthomosaicId,
    commitTreeCollection,
    setState,
    treeDisplayModeRef,
  });
  const toggleDiameterFill = useCallback(() => {
    const enabled = !diameterFillEnabledRef.current;
    diameterFillEnabledRef.current = enabled;
    setDiameterFillEnabled(enabled);
    syncTreeLayerVisibility();
  }, [syncTreeLayerVisibility]);
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
    orthoMode: state.orthoMode,
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
    commitTreeCollectionHandlerRef.current = commitAndPersistDetections;
  }, [commitAndPersistDetections]);

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
    commitTreeCollection: commitAndPersistDetections,
    detectionLoadTokenRef,
    activeOrthomosaicIdRef,
    saveDetectionsNow,
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
  const toggleVariDetections = useCallback(() => {
    if (state.orthoMode !== "rgb" || !treeData?.features.length) return;
    if (!variDetectionsEnabled) {
      const selectedVari = indexAnalyses.find((item) => item.name === "VARI");
      setVariDetectionStyle((current) => selectedVari ? {
        minimum: selectedVari.minimum,
        maximum: selectedVari.maximum,
        equalized: selectedVari.equalized,
        fillMode: selectedVari.fillMode,
        cropId: activeCropIdRef.current,
      } : current);
      hideIndex("VARI");
    }
    setVariDetectionsEnabled((current) => !current);
  }, [hideIndex, indexAnalyses, state.orthoMode, treeData, variDetectionsEnabled]);
  const hideAllIndices = useCallback(() => {
    hideIndices();
    setVariDetectionsEnabled(false);
  }, [hideIndices]);

  useEffect(() => {
    if (variDetectionsEnabled && indexRefs.current.has("VARI"))
      hideIndex("VARI");
  }, [variDetectionsEnabled, indexAnalyses, hideIndex]);

  useEffect(() => {
    setVariDetectionsEnabled(false);
    setVariDetectionStyle(null);
    variResponseRef.current = null;
    variLoadFailedRef.current = false;
  }, [state.orthomosaicId, state.orthoMode]);

  useEffect(() => {
    if ((!variDetectionsEnabled && !state.labels) ||
        !state.trees || state.orthoMode !== "rgb") return;
    if (!state.labels && variDetectionStyle) return;
    if (variResponseRef.current) {
      refreshLabels();
      return;
    }
    let cancelled = false;
    variLoadFailedRef.current = false;
    dashboardApi.vegetationIndex("VARI")
      .then((response) => {
        if (cancelled) return;
        variResponseRef.current = response;
        variLoadFailedRef.current = false;
        setVariDetectionStyle((current) => {
          if (current) return current;
          let minimum = Infinity;
          let maximum = -Infinity;
          response.matrix.forEach((row, y) => row.forEach((value, x) => {
            if (!Number.isFinite(value) || Number(response.mask?.[y]?.[x] ?? 1) <= 0) return;
            minimum = Math.min(minimum, value);
            maximum = Math.max(maximum, value);
          }));
          return {
            minimum: Number.isFinite(minimum) ? minimum : -1,
            maximum: Number.isFinite(maximum) ? maximum : 1,
            equalized: true,
            fillMode: "transparent",
            cropId: null,
          };
        });
        refreshLabels();
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        variLoadFailedRef.current = true;
        refreshLabels();
        if (variDetectionsEnabled && !variDetectionStyle) setVariDetectionsEnabled(false);
        setState((current) => ({
          ...current,
          error: error instanceof Error ? error.message : "No se pudo calcular VARI.",
        }));
      });
    return () => { cancelled = true; };
  }, [variDetectionsEnabled, variDetectionStyle, state.labels, state.trees, state.orthoMode, state.orthomosaicId, refreshLabels]);

  useEffect(() => {
    variDetectionOverlayRef.current?.remove();
    variDetectionOverlayRef.current = undefined;
    const map = mapRef.current;
    if (!map || !variDetectionsEnabled || !state.trees ||
        state.treeDisplayMode !== "diameters" || !variDetectionStyle ||
        !filteredTreeData?.features.length) return;
    const url = spectralTileUrl(
      "VARI",
      variDetectionStyle.minimum,
      variDetectionStyle.maximum,
      variDetectionStyle.cropId,
      variDetectionStyle.equalized,
      variDetectionStyle.fillMode,
    );
    variDetectionOverlayRef.current = createVariDiameterTileLayer(
      `${url}&v=${encodeURIComponent(INDEX_TILE_VERSION)}`,
      filteredTreeData,
    ).addTo(map);
    return () => {
      variDetectionOverlayRef.current?.remove();
      variDetectionOverlayRef.current = undefined;
    };
  }, [variDetectionsEnabled, variDetectionStyle, filteredTreeData, state.trees, state.treeDisplayMode, spectralTileUrl]);
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

  const publishCurrentResults = useCallback(
    async ({ cycle, orthomosaic }: PublicationContext) => {
      const orthomosaicId = state.orthomosaicId;
      const roiId = state.selectedRoiId;
      const roiGeometry = activeCropGeometryRef.current ?? selectedRoiRef.current;
      if (!orthomosaicId) {
        throw new Error("Selecciona un ortomosaico antes de publicar resultados.");
      }
      if (!roiId || !roiGeometry || !ndviAnalysis.roiResponse) {
        throw new Error("Selecciona y recorta un ROI antes de publicar resultados.");
      }
      if (!prescription) {
        throw new Error("Genera la prescripcion antes de publicar resultados en Neon.");
      }

      const publicationKey = currentPublicationKey(
        orthomosaicId,
        roiId,
        zoning,
        prescription,
      );
      const indices = [
        {
          index_name: "NDVI",
          stats: statsPayload(
            ndviAnalysis.roiStats,
            ndviAnalysis.minimum,
            ndviAnalysis.maximum,
          ),
        },
        ...indexAnalyses.map((analysis) => ({
          index_name: analysis.name,
          stats: statsPayload(analysis.stats, analysis.minimum, analysis.maximum),
        })),
      ];
      const zoningPayload = zoning
        ? {
            source_zoning_id: zoning.zoning_id,
            index_name: zoning.index_name ?? "NDVI",
            classification_method: zoning.classification_method,
            cell_value_mode: zoning.cell_value_mode,
            zone_count: zoning.zone_count,
            cell_size_m: zoning.cell_size_m,
            grid_angle_deg: zoning.grid_angle_deg,
            detail_level: zoning.detail_level,
            field_mean: zoning.field_mean,
            valid_cell_count: zoning.valid_cell_count,
            area_hectares: zoning.area_hectares,
            thresholds: zoning.thresholds ?? [],
            histogram: zoning.histogram ?? {},
            legend: zoning.legend,
            response: zoning,
          }
        : undefined;
      const prescriptionPayload = prescription
        ? {
            source_prescription_id: prescription.prescription_id,
            index_name: prescription.index_name ?? "NDVI",
            classification_method: prescription.classification_method,
            cell_value_mode: prescription.cell_value_mode,
            zone_count: prescription.zone_count,
            cell_size_m: prescription.cell_size_m,
            grid_angle_deg: prescription.grid_angle_deg,
            detail_level: prescription.detail_level,
            field_mean: prescription.field_mean,
            valid_cell_count: prescription.valid_cell_count,
            area_hectares: prescription.area_hectares,
            thresholds: prescription.thresholds ?? [],
            histogram: prescription.histogram ?? {},
            legend: prescription.legend,
            rates: prescription.legend.map((zone) => ({
              class_id: zone.class_id,
              dosage: zone.dosage ?? 0,
            })),
            response: prescription,
          }
        : undefined;

      return dashboardApi.publishResults({
        project: {
          source_project_id: cycle?.id ?? null,
          name: cycle?.name ?? orthomosaic?.name ?? "Geofield",
          field_name: orthomosaic?.name ?? null,
          crop_name: cycle?.crop_name ?? null,
          cycle_name: cycle?.name ?? null,
          source_metadata: {
            orthomosaic_capture_date: orthomosaic?.capture_date ?? null,
            orthomosaic_sensor_type: orthomosaic?.sensor_type ?? state.sensor,
          },
        },
        analysis: {
          source_publication_key: publicationKey,
          source_orthomosaic_id: orthomosaicId,
          source_roi_id: roiId,
          analysis_type: "roi_prescription",
          payload_version: 1,
        },
        roi: {
          name: `ROI ${roiId.slice(0, 8)}`,
          geometry_geojson: roiGeometry,
          bounds: ndviAnalysis.roiResponse.bounds,
        },
        indices,
        zoning: zoningPayload,
        prescription: prescriptionPayload,
        artifacts: artifactsForPublication(zoning, prescription),
      });
    },
    [
      indexAnalyses,
      ndviAnalysis.maximum,
      ndviAnalysis.minimum,
      ndviAnalysis.roiResponse,
      ndviAnalysis.roiStats,
      prescription,
      state.orthomosaicId,
      state.selectedRoiId,
      state.sensor,
      zoning,
    ],
  );

  const deleteCurrentPublication = useCallback(async () => {
    const orthomosaicId = state.orthomosaicId;
    const roiId = state.selectedRoiId;
    if (!orthomosaicId || !roiId) {
      throw new Error("Selecciona un ortomosaico y ROI antes de eliminar la publicacion.");
    }
    return dashboardApi.deletePublication(
      currentPublicationKey(orthomosaicId, roiId, zoning, prescription),
    );
  }, [prescription, state.orthomosaicId, state.selectedRoiId, zoning]);
  return {
    state,
    treeData,
    reloadDetections,
    diameterFillEnabled,
    filteredTreeData,
    ndviAnalysis,
    indexAnalyses,
    variDetectionsEnabled,
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
    hideIndices: hideAllIndices,
    hideNdvi,
    hideIndex,
    toggleNdvi,
    toggleIndexLayer,
    toggleVariDetections,
    toggleDiameterFill,
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
    publishCurrentResults,
    deleteCurrentPublication,
  };
}







