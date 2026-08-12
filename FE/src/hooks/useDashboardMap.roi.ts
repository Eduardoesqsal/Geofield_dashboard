/**
 * Helpers específicos del flujo ROI.
 * Aíslan la limpieza de overlays del recorte y la reinstalación de la capa
 * base para que el hook principal no concentre toda la lógica visual.
 */
import type { MutableRefObject, RefObject } from "react";
import L from "leaflet";
import type { NdviResponse } from "../services/api";

interface ClearRoiArtifactsParams {
  clearTileClip: () => void;
  cropControlRef: MutableRefObject<L.Marker | undefined>;
  indexRefs: MutableRefObject<Map<string, L.Layer>>;
  ndviRangeRef: MutableRefObject<{ min: number; max: number }>;
  ndviRef: MutableRefObject<L.ImageOverlay | undefined>;
  ndviResponseRef: MutableRefObject<NdviResponse | null>;
  ndviTileRef: MutableRefObject<L.TileLayer | undefined>;
  orthoRef: MutableRefObject<L.TileLayer | undefined>;
  roiIndexResponsesRef: MutableRefObject<
    Partial<Record<"NDVI" | "NDWI" | "NDRE", NdviResponse>> | null
  >;
  selectedRoiRef: MutableRefObject<unknown>;
  selectedRoisRef: MutableRefObject<Map<string, unknown>>;
}

export function clearRoiArtifacts({
  clearTileClip,
  cropControlRef,
  indexRefs,
  ndviRangeRef,
  ndviRef,
  ndviResponseRef,
  ndviTileRef,
  roiIndexResponsesRef,
  selectedRoiRef,
  selectedRoisRef,
}: ClearRoiArtifactsParams) {
  selectedRoisRef.current.clear();
  selectedRoiRef.current = null;
  roiIndexResponsesRef.current = null;
  ndviResponseRef.current = null;
  ndviRangeRef.current = { min: -1, max: 1 };
  clearTileClip();

  cropControlRef.current?.remove();
  cropControlRef.current = undefined;
  ndviRef.current?.remove();
  ndviRef.current = undefined;
  ndviTileRef.current?.remove();
  ndviTileRef.current = undefined;
  indexRefs.current.forEach((layer) => layer.remove());
  indexRefs.current.clear();
}

interface RestoreBaseOrthoParams {
  mapRef: RefObject<L.Map | undefined>;
  orthoRef: MutableRefObject<L.TileLayer | undefined>;
}

export function restoreBaseOrthoLayer({
  mapRef,
  orthoRef,
}: RestoreBaseOrthoParams) {
  const map = mapRef.current;
  if (map && orthoRef.current) orthoRef.current.addTo(map);
}

interface ApplyRoiCropLayerParams {
  activeCropIdRef: MutableRefObject<string | null>;
  backendUrl: (path: string) => string;
  bounds: [[number, number], [number, number]];
  cropId: string;
  cropTileRef: MutableRefObject<L.TileLayer | undefined>;
  mapRef: RefObject<L.Map | undefined>;
  orthoRef: MutableRefObject<L.TileLayer | undefined>;
  uploadedRgbRef: MutableRefObject<L.ImageOverlay | undefined>;
}

export function applyRoiCropLayer({
  activeCropIdRef,
  backendUrl,
  bounds,
  cropId,
  cropTileRef,
  mapRef,
  orthoRef,
  uploadedRgbRef,
}: ApplyRoiCropLayerParams) {
  const map = mapRef.current;
  if (!map) return;
  uploadedRgbRef.current?.remove();
  orthoRef.current?.remove();
  cropTileRef.current?.remove();
  cropTileRef.current = L.tileLayer(
    backendUrl(`/tiles/crop/${cropId}/{z}/{x}/{y}.png`),
    {
      tileSize: 512,
      zoomOffset: -1,
      maxNativeZoom: 24,
      maxZoom: 24,
      bounds,
      keepBuffer: 3,
      updateWhenIdle: true,
      opacity: 1,
    },
  ).addTo(map);
  activeCropIdRef.current = cropId;
}
