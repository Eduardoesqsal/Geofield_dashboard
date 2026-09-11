// @ts-nocheck
import { useCallback } from "react";
import L from "leaflet";
import {
  backendUrl,
  dashboardApi,
  type NdviResponse,
  type OrthoMode,
  type OrthoSensor,
} from "../services/api";
import {
  type ClassificationFillMode,
  ndviStats,
} from "../utils/ndvi";
import {
  createEmptyNdviAnalysis,
  modeFromSensor,
} from "./useDashboardMap.helpers";
import { mountUploadedOrthomosaic, resetOrthomosaicArtifacts } from "./useDashboardMap.orthomosaic";
import {
  clearSpectralLayers,
  createNdviResponse,
  removeSingleSpectralLayer,
} from "./useDashboardMap.spectral";
import type { IndexAnalysis } from "./useDashboardMap";

export function useDashboardMapSpectralActions(ctx: any) {
  const {
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
  } = ctx;

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
              "El backend no devolviÃ³ la matriz NDVI del ortomosaico.",
            );
          const response: NdviResponse = {
            ...createNdviResponse(result.bounds, result.mask, result.ndvi_matrix),
          };
          const stats = ndviStats(response);
          ndviResponseRef.current = response;
          ndviRangeRef.current = {
            min: response.range_min ?? stats.min,
            max: response.range_max ?? stats.max,
            equalized: false,
            fillMode: "transparent",
            values: stats.values,
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

  /** Actualiza contraste y re-renderiza localmente un Ã­ndice adicional activo. */
  const setIndexRange = useCallback(
    (name: IndexAnalysis["name"], minimum: number, maximum: number) => {
      const safeMinimum = Math.min(minimum, maximum);
      const safeMaximum = Math.max(minimum, maximum);
      setIndexAnalyses((current) =>
        current.map((analysis) => {
          if (analysis.name !== name) return analysis;
          const next = {
            ...analysis,
            minimum: safeMinimum,
            maximum: safeMaximum,
          };
          renderIndex(
            name,
            next.response,
            next.minimum,
            next.maximum,
            next.equalized,
            next.fillMode,
            next.stats.values,
          );
          return next;
        }),
      );
    },
    [renderIndex],
  );

  const setNdviEqualization = useCallback(
    (equalized: boolean) => {
      ndviRangeRef.current = {
        min: ndviAnalysis.minimum,
        max: ndviAnalysis.maximum,
        equalized,
        fillMode: ndviAnalysis.fillMode,
        values: (ndviAnalysis.roiResponse ? ndviAnalysis.roiStats : ndviAnalysis.stats)
          .values,
      };
      setNdviAnalysis((current) => ({ ...current, equalized }));
      if (ndviResponseRef.current) renderNdvi(ndviResponseRef.current);
    },
    [
      ndviAnalysis.fillMode,
      ndviAnalysis.maximum,
      ndviAnalysis.minimum,
      ndviAnalysis.roiResponse,
      ndviAnalysis.roiStats,
      ndviAnalysis.stats,
      renderNdvi,
    ],
  );

  const setNdviFillMode = useCallback(
    (fillMode: ClassificationFillMode) => {
      setNdviAnalysis((current) => {
        ndviRangeRef.current = {
          min: current.minimum,
          max: current.maximum,
          equalized: current.equalized,
          fillMode,
          values: (current.roiResponse ? current.roiStats : current.stats).values,
        };
        return { ...current, fillMode };
      });
      if (ndviResponseRef.current) renderNdvi(ndviResponseRef.current);
    },
    [renderNdvi],
  );

  const setIndexEqualization = useCallback(
    (name: IndexAnalysis["name"], equalized: boolean) => {
      const analysis = indexAnalyses.find((item) => item.name === name);
      if (!analysis) return;
      renderIndex(
        name,
        analysis.response,
        analysis.minimum,
        analysis.maximum,
        equalized,
        analysis.fillMode,
        analysis.stats.values,
      );
      setIndexAnalyses((current) =>
        current.map((item) =>
          item.name === name ? { ...item, equalized } : item,
        ),
      );
    },
    [indexAnalyses, renderIndex],
  );

  const setIndexFillMode = useCallback(
    (name: IndexAnalysis["name"], fillMode: ClassificationFillMode) => {
      setIndexAnalyses((current) =>
        current.map((analysis) => {
          if (analysis.name !== name) return analysis;
          const next = { ...analysis, fillMode };
          renderIndex(
            name,
            next.response,
            next.minimum,
            next.maximum,
            next.equalized,
            next.fillMode,
            next.stats.values,
          );
          return next;
        }),
      );
    },
    [renderIndex],
  );

  /**
   * Activa NDVI, NDWI o NDRE eligiendo automÃ¡ticamente datos globales o los
   * resultados del recorte ROI vigente.
   */
  const selectIndex = useCallback(
    async (name: "NDVI" | IndexAnalysis["name"]) => {
      try {
        if (state.orthoMode !== "multispectral")
          throw new Error(
            "Carga un ortomosaico multiespectral para calcular Ã­ndices.",
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
              roiResponse: roiResponse ?? null,
              roiStats: roiResponse ? stats : current.roiStats,
              minimum: defaultMinimum,
              maximum: defaultMaximum,
            };
          });
          ndviRef.current?.remove();
          ndviTileRef.current?.remove();
          ndviTileRef.current = undefined;
          renderNdvi(response);
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
              equalized: false,
              fillMode: "transparent",
            },
          ]);
          renderIndex(
            name,
            roiResponse,
            defaultMinimum,
            defaultMaximum,
            false,
            "transparent",
            stats.values,
          );
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
            equalized: false,
            fillMode: "transparent",
          },
        ]);
        renderIndex(
          name,
          response,
          defaultMinimum,
          defaultMaximum,
          false,
          "transparent",
          stats.values,
        );
        setState((current) => ({ ...current, error: null }));
      } catch (error) {
        setState((current) => ({
          ...current,
          error:
            error instanceof Error
              ? error.message
              : "No se pudo calcular el Ã­ndice.",
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

  /** Oculta NDVI y restablece su indicador sin alterar otros Ã­ndices. */
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

  /** Retira una Ãºnica capa NDWI o NDRE y su tarjeta analÃ­tica. */
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
          error: "El anÃ¡lisis NDVI requiere un ortomosaico multiespectral.",
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

  /** Enciende o apaga una capa NDWI/NDRE sin retirar su panel analÃ­tico. */
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
      setNdviAnalysis((current) => {
        ndviRangeRef.current = {
          min: safeMinimum,
          max: safeMaximum,
          equalized: current.equalized,
          fillMode: current.fillMode,
          values: (current.roiResponse ? current.roiStats : current.stats).values,
        };
        return {
          ...current,
          minimum: safeMinimum,
          maximum: safeMaximum,
        };
      });
      if (ndviResponseRef.current) renderNdvi(ndviResponseRef.current);
    },
    [renderNdvi],
  );

  /** Muestra u oculta detecciones conservando la capa para reutilizarla. */


  return {
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
  };
}


