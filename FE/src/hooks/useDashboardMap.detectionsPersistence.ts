import { useCallback, useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { dashboardApi } from "../services/api";
import type { TreeCollection } from "../types/geo";
import type { MapState, TreeDisplayMode } from "./useDashboardMap";

interface DetectionPersistenceContext {
  orthomosaicId: string | null;
  commitTreeCollection: (collection: TreeCollection, visible?: boolean) => void;
  setState: Dispatch<SetStateAction<MapState>>;
  treeDisplayModeRef: MutableRefObject<TreeDisplayMode>;
}

/** Guarda ediciones en orden y recupera el conjunto del vuelo activo. */
export function useDetectionPersistence({
  orthomosaicId,
  commitTreeCollection,
  setState,
  treeDisplayModeRef,
}: DetectionPersistenceContext) {
  const activeOrthomosaicIdRef = useRef<string | null>(orthomosaicId);
  activeOrthomosaicIdRef.current = orthomosaicId;
  const detectionLoadTokenRef = useRef(0);
  const saveTailRef = useRef<Promise<unknown>>(Promise.resolve());
  const pendingSaveRef = useRef<{
    id: string;
    collection: TreeCollection;
    timer: number;
  } | null>(null);

  const saveDetectionsNow = useCallback((id: string, collection: TreeCollection) => {
    const pending = pendingSaveRef.current;
    if (pending?.id === id) {
      window.clearTimeout(pending.timer);
      pendingSaveRef.current = null;
    }
    const job = saveTailRef.current
      .catch(() => undefined)
      .then(() => dashboardApi.saveDetections(id, collection));
    saveTailRef.current = job.catch(() => undefined);
    return job;
  }, []);

  const commitAndPersistDetections = useCallback(
    (collection: TreeCollection, visible?: boolean) => {
      detectionLoadTokenRef.current += 1;
      commitTreeCollection(collection, visible);
      const id = activeOrthomosaicIdRef.current;
      if (!id) return;
      const pending = pendingSaveRef.current;
      if (pending) {
        window.clearTimeout(pending.timer);
        pendingSaveRef.current = null;
        if (pending.id !== id)
          void saveDetectionsNow(pending.id, pending.collection).catch(() => undefined);
      }
      const timer = window.setTimeout(() => {
        pendingSaveRef.current = null;
        void saveDetectionsNow(id, collection).catch((error: unknown) => {
          if (activeOrthomosaicIdRef.current === id)
            setState((current) => ({
              ...current,
              error: `No se pudieron guardar las detecciones: ${error instanceof Error ? error.message : String(error)}`,
            }));
        });
      }, 500);
      pendingSaveRef.current = { id, collection, timer };
    },
    [commitTreeCollection, saveDetectionsNow, setState],
  );

  const reloadDetections = useCallback(async () => {
    const id = activeOrthomosaicIdRef.current;
    if (!id) return;
    const token = ++detectionLoadTokenRef.current;
    try {
      const pending = pendingSaveRef.current;
      if (pending?.id === id) await saveDetectionsNow(id, pending.collection);
      await saveTailRef.current;
      if (detectionLoadTokenRef.current !== token) return;
      commitTreeCollection({ type: "FeatureCollection", features: [] }, false);
      const { detections } = await dashboardApi.getDetections(id);
      if (detectionLoadTokenRef.current !== token || !detections) return;
      treeDisplayModeRef.current = "diameters";
      commitTreeCollection(detections.geojson, true);
      setState((current) => ({ ...current, treeDisplayMode: "diameters" }));
    } catch (error) {
      if (detectionLoadTokenRef.current === token) {
        setState((current) => ({
          ...current,
          error: `No se pudieron cargar las detecciones: ${error instanceof Error ? error.message : String(error)}`,
        }));
        throw error;
      }
    }
  }, [commitTreeCollection, saveDetectionsNow, setState, treeDisplayModeRef]);

  useEffect(() => {
    if (orthomosaicId) void reloadDetections().catch(() => undefined);
  }, [orthomosaicId, reloadDetections]);

  return {
    activeOrthomosaicIdRef,
    detectionLoadTokenRef,
    saveDetectionsNow,
    commitAndPersistDetections,
    reloadDetections,
  };
}
