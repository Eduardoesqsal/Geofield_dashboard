// @ts-nocheck
import { useCallback } from "react";
import L from "leaflet";
import type { FeatureCollection, GeoJsonObject } from "geojson";
import {
  backendUrl,
  dashboardApi,
  type NdviZoningResponse,
} from "../services/api";

export function useDashboardMapPrescription(ctx: any) {
  const {
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
  } = ctx;

  const clearClassificationGrid = useCallback(() => {
    classificationGridRef.current?.remove();
    classificationGridRef.current = undefined;
  }, []);

  const clearClassificationFill = useCallback(() => {
    classificationFillRef.current?.remove();
    classificationFillRef.current = undefined;
  }, []);

  const clearLivePrescriptionGrid = useCallback(() => {
    livePrescriptionGridCleanupRef.current?.();
    livePrescriptionGridCleanupRef.current = null;
    livePrescriptionGridRef.current?.remove();
    livePrescriptionGridRef.current = null;
    const map = mapRef.current;
    [
      "classificationImagePane",
      "classificationFillPane",
      "classificationGridPane",
    ].forEach((paneName) => {
      const pane = map?.getPane(paneName);
      pane?.style.removeProperty("display");
      pane?.style.removeProperty("transform");
      pane?.style.removeProperty("transform-origin");
      pane?.style.removeProperty("will-change");
    });
  }, []);

  const setLivePrescriptionRotation = useCallback(
    (
      cellSizeM: number,
      gridAngleDeg: number,
      visible = true,
      baseAngleDeg = 0,
      hasCurrentMap = false,
    ) => {
      void baseAngleDeg;
      void hasCurrentMap;
      const map = mapRef.current;
      if (!map || !visible) {
        clearLivePrescriptionGrid();
        return;
      }
      [
        "classificationImagePane",
        "classificationFillPane",
        "classificationGridPane",
      ].forEach((paneName) => {
        const pane = map.getPane(paneName);
        pane?.style.removeProperty("transform");
        pane?.style.removeProperty("transform-origin");
        pane?.style.removeProperty("will-change");
      });
      const container = map.getContainer();
      let overlay = livePrescriptionGridRef.current;
      if (!overlay) {
        overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        overlay.setAttribute("class", "prescription-live-grid");
        container.appendChild(overlay);
        livePrescriptionGridRef.current = overlay;
      }

      const updateLiveGrid = () => {
        if (!livePrescriptionGridRef.current) return;
        const geometry = prescriptionGeometryRef.current ?? activeCropGeometryRef.current;
        if (!geometry) {
          clearLivePrescriptionGrid();
          return;
        }
        const anchorBounds = geometry
          ? L.geoJSON(geometry as GeoJsonObject).getBounds()
          : boundsRef.current;
        const anchor = anchorBounds?.isValid()
          ? anchorBounds.getCenter()
          : map.getCenter();
        const anchorPoint = map.latLngToContainerPoint(anchor);
        const gridExtent = Math.max(
          map.getContainer().clientWidth,
          map.getContainer().clientHeight,
          1,
        ) * 2;
        const center = anchor;
        const centerPoint = map.latLngToContainerPoint(center);
        const referencePoint = L.point(centerPoint.x + 100, centerPoint.y);
        const referenceLatLng = map.containerPointToLatLng(referencePoint);
        const metersForReference = Math.max(
          map.distance(center, referenceLatLng),
          0.001,
        );
        const pixelsPerMeter = 100 / metersForReference;
        const cellPixels = Math.max(8, Math.min(96, cellSizeM * pixelsPerMeter));

        const pathFromRing = (ring: number[][]) =>
          ring
            .map((coordinate, index) => {
              const [longitude, latitude] = coordinate;
              const point = map.latLngToContainerPoint([latitude, longitude]);
              return `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`;
            })
            .join(" ");
        const polygonPaths: string[] = [];
        const appendPolygon = (rings: number[][][]) => {
          rings.forEach((ring) => {
            if (ring.length >= 3) polygonPaths.push(`${pathFromRing(ring)} Z`);
          });
        };
        const appendGeometry = (source: any) => {
          if (!source) return;
          if (source.type === "FeatureCollection") {
            source.features?.forEach((feature: any) => appendGeometry(feature));
            return;
          }
          if (source.type === "Feature") {
            appendGeometry(source.geometry);
            return;
          }
          if (source.type === "Polygon") {
            appendPolygon(source.coordinates);
            return;
          }
          if (source.type === "MultiPolygon") {
            source.coordinates.forEach((polygon: number[][][]) =>
              appendPolygon(polygon),
            );
          }
        };
        appendGeometry(geometry);
        const clipPath = polygonPaths.join(" ");
        if (!clipPath) {
          clearLivePrescriptionGrid();
          return;
        }

        const width = Math.max(container.clientWidth, 1);
        const height = Math.max(container.clientHeight, 1);
        livePrescriptionGridRef.current.setAttribute("width", `${width}`);
        livePrescriptionGridRef.current.setAttribute("height", `${height}`);
        livePrescriptionGridRef.current.setAttribute("viewBox", `0 0 ${width} ${height}`);
        livePrescriptionGridRef.current.innerHTML = `
          <defs>
            <clipPath id="prescription-live-grid-clip">
              <path d="${clipPath}" clip-rule="evenodd"></path>
            </clipPath>
            <pattern id="prescription-live-grid-pattern" patternUnits="userSpaceOnUse" x="${anchorPoint.x.toFixed(2)}" y="${anchorPoint.y.toFixed(2)}" width="${cellPixels.toFixed(2)}" height="${cellPixels.toFixed(2)}">
              <path d="M 0 0 H ${cellPixels.toFixed(2)} M 0 0 V ${cellPixels.toFixed(2)}" fill="none" stroke="rgba(255,255,255,0.68)" stroke-width="1"></path>
            </pattern>
          </defs>
          <g clip-path="url(#prescription-live-grid-clip)">
            <g transform="rotate(${-gridAngleDeg} ${anchorPoint.x.toFixed(2)} ${anchorPoint.y.toFixed(2)})">
              <rect x="${(anchorPoint.x - gridExtent).toFixed(2)}" y="${(anchorPoint.y - gridExtent).toFixed(2)}" width="${(gridExtent * 2).toFixed(2)}" height="${(gridExtent * 2).toFixed(2)}" fill="url(#prescription-live-grid-pattern)"></rect>
            </g>
          </g>
        `;
      };

      updateLiveGrid();
      livePrescriptionGridCleanupRef.current?.();
      map.on("zoom move", updateLiveGrid);
      livePrescriptionGridCleanupRef.current = () => {
        map.off("zoom move", updateLiveGrid);
      };
    },
    [clearLivePrescriptionGrid],
  );

  const mountClassificationFill = useCallback(
    async (geojsonUrl?: string) => {
      const map = mapRef.current;
      clearClassificationFill();
      if (!map || !geojsonUrl) return;

      const response = await fetch(backendUrl(geojsonUrl), {
        headers: { Accept: "application/geo+json, application/json" },
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(
          `No se pudo cargar la capa de prescripcion (error ${response.status}).`,
        );
      }

      const geojson = (await response.json()) as FeatureCollection;
      const featureCount = Array.isArray(geojson.features) ? geojson.features.length : 0;
      console.info("[classification-fill]", {
        url: geojsonUrl,
        featureCount,
      });
      classificationFillRef.current = L.geoJSON(geojson, {
        pane: "classificationFillPane",
        interactive: false,
        style: (feature) => {
          const color =
            typeof feature?.properties?.color === "string"
              ? feature.properties.color
              : "#ffffff";
          return {
            color: "#ffffff",
            weight: 1,
            opacity: 0.1,
            fillColor: color,
            fillOpacity: 0.72,
          };
        },
      }).addTo(map);
    },
    [clearClassificationFill],
  );

  const mountClassificationGrid = useCallback(
    async (gridUrl?: string) => {
      const map = mapRef.current;
      clearClassificationGrid();
      if (!map || !gridUrl) return;

      const response = await fetch(backendUrl(gridUrl), {
        headers: { Accept: "application/geo+json, application/json" },
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(
          `No se pudo cargar el overlay de grilla (error ${response.status}).`,
        );
      }

      const geojson = (await response.json()) as GeoJsonObject;
      const gridOpacityForZoom = (zoom: number) => {
        if (zoom <= 18) return 0.008;
        if (zoom >= 22) return 0.05;
        return 0.008 + ((zoom - 18) / 4) * 0.042;
      };
      const gridLayer = L.geoJSON(geojson, {
        pane: "classificationGridPane",
        interactive: false,
        style: {
          color: "#ffffff",
          weight: 1,
          opacity: gridOpacityForZoom(map.getZoom()),
          lineCap: "square",
          lineJoin: "miter",
        },
      }).addTo(map);
      const updateGridOpacity = () => {
        gridLayer.setStyle({ opacity: gridOpacityForZoom(map.getZoom()) });
      };
      map.on("zoomend", updateGridOpacity);
      gridLayer.once("remove", () => map.off("zoomend", updateGridOpacity));
      classificationGridRef.current = gridLayer;
    },
    [clearClassificationGrid],
  );

  const clearZoning = useCallback(() => {
    zoningPreviewTokenRef.current += 1;
    clearLivePrescriptionGrid();
    zoningPreviewAbortRef.current?.abort();
    zoningPreviewAbortRef.current = null;
    zoningPreviewRef.current?.remove();
    zoningPreviewRef.current = undefined;
    zoningPreviewGridRef.current?.remove();
    zoningPreviewGridRef.current = undefined;
    zoningRef.current?.remove();
    zoningRef.current = undefined;
    clearClassificationFill();
    clearClassificationGrid();
    setZoning(null);
  }, [clearClassificationFill, clearClassificationGrid, clearLivePrescriptionGrid]);

  const clearZoningPreview = useCallback(() => {
    zoningPreviewTokenRef.current += 1;
    clearLivePrescriptionGrid();
    zoningPreviewAbortRef.current?.abort();
    zoningPreviewAbortRef.current = null;
    zoningPreviewRef.current?.remove();
    zoningPreviewRef.current = undefined;
    zoningPreviewGridRef.current?.remove();
    zoningPreviewGridRef.current = undefined;
  }, [clearLivePrescriptionGrid]);

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
      allowExisting = false,
    ) => {
      const map = mapRef.current;
      if (
        !map ||
        !state.orthomosaicId ||
        (!allowExisting && (zoning || prescription))
      ) return;
      if (state.orthoMode !== "multispectral") return;
      const indexReady =
        indexName === "NDVI"
          ? ndviAnalysis.roiResponse
          : indexAnalyses.some((analysis) => analysis.name === indexName);
      if (!activeCropGeometryRef.current || !indexReady) return;
      const geometry =
        prescriptionGeometryRef.current ?? activeCropGeometryRef.current;
      const token = ++zoningPreviewTokenRef.current;
      zoningPreviewAbortRef.current?.abort();
      const abortController = new AbortController();
      zoningPreviewAbortRef.current = abortController;
      const releasePreviewAbortController = () => {
        if (zoningPreviewAbortRef.current === abortController) {
          zoningPreviewAbortRef.current = null;
        }
      };
      let result: NdviZoningResponse;
      try {
        result = await dashboardApi.createNdviZoning(
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
            signal: abortController.signal,
          },
        );
      } catch (error) {
        if (abortController.signal.aborted) return;
        releasePreviewAbortController();
        throw error;
      }
      if (
        token !== zoningPreviewTokenRef.current ||
        (!allowExisting && (zoning || prescription))
      ) {
        releasePreviewAbortController();
        return;
      }
      let previewGrid: GeoJsonObject | null = null;
      try {
        if (result.grid_url) {
          const gridResponse = await fetch(backendUrl(result.grid_url), {
            headers: { Accept: "application/geo+json, application/json" },
            cache: "no-store",
            signal: abortController.signal,
          });
          if (gridResponse.ok) {
            previewGrid = (await gridResponse.json()) as GeoJsonObject;
          }
        }
      } catch (error) {
        if (abortController.signal.aborted) return;
        releasePreviewAbortController();
        throw error;
      }
      if (token !== zoningPreviewTokenRef.current) {
        releasePreviewAbortController();
        return;
      }
      zoningPreviewRef.current?.remove();
      zoningPreviewGridRef.current?.remove();
      if (allowExisting) {
        zoningRef.current?.remove();
        prescriptionRef.current?.remove();
        clearClassificationFill();
      }
      clearClassificationGrid();
      zoningPreviewRef.current = L.tileLayer(backendUrl(result.tile_url), {
        pane: "classificationPreviewPane",
        tileSize: 256,
        maxNativeZoom: 24,
        maxZoom: 24,
        keepBuffer: 3,
        updateWhenIdle: true,
        updateWhenZooming: false,
        opacity: 1,
        className: "zoning-map-overlay is-preview",
      }).addTo(map);
      if (previewGrid) {
        zoningPreviewGridRef.current = L.geoJSON(previewGrid, {
          pane: "classificationPreviewGridPane",
          interactive: false,
          style: {
            color: "#ffffff",
            weight: 1,
            opacity: 0.28,
            lineCap: "square",
            lineJoin: "miter",
          },
        }).addTo(map);
      }
      releasePreviewAbortController();
    },
    [
      activeAnalysisRange,
      clearClassificationFill,
      clearClassificationGrid,
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
          pane: "classificationImagePane",
          tileSize: 256,
          maxNativeZoom: 24,
          maxZoom: 24,
          keepBuffer: 3,
          updateWhenIdle: true,
          updateWhenZooming: false,
          opacity: 1,
          className: "zoning-map-overlay",
        }).addTo(map);
        await mountClassificationFill(result.geojson_url);
        await mountClassificationGrid(result.grid_url);
        console.info("[zoning-response-debug]", result.debug ?? null);
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
      mountClassificationFill,
      mountClassificationGrid,
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
        throw new Error("Selecciona un vuelo antes de generar la prescripciÃ³n.");
      if (state.orthoMode !== "multispectral")
        throw new Error("La prescripciÃ³n NDVI requiere un ortomosaico multiespectral.");
      const indexReady =
        indexName === "NDVI"
          ? ndviAnalysis.roiResponse
          : indexAnalyses.some((analysis) => analysis.name === indexName);
      if (!activeCropGeometryRef.current || !indexReady)
        throw new Error(
          "Selecciona un ROI, recÃ³rtalo y abre su histograma NDVI antes de generar la prescripciÃ³n.",
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
          pane: "classificationImagePane",
          tileSize: 256,
          maxNativeZoom: 24,
          maxZoom: 24,
          keepBuffer: 3,
          updateWhenIdle: true,
          updateWhenZooming: false,
          opacity: 1,
          className: "prescription-map-overlay",
        }).addTo(map);
        await mountClassificationFill(result.geojson_url);
        await mountClassificationGrid(result.grid_url);
        console.info("[prescription-response-debug]", result.debug ?? null);
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
      mountClassificationFill,
      mountClassificationGrid,
      ndviAnalysis.roiResponse,
      state.orthoMode,
      state.orthomosaicId,
    ],
  );



  return {
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
  };
}

