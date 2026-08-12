/**
 * Helpers del ciclo de vida del ortomosaico dentro del mapa.
 * Encapsulan limpieza de capas previas, montaje de vuelos cargados y
 * restauración de la capa base cuando cambia el contexto visual.
 */
import type { MutableRefObject, RefObject } from "react";
import L from "leaflet";
import type { NdviResponse } from "../services/api";
import type { TreeCollection } from "../types/geo";

interface ResetOrthomosaicArtifactsParams {
  cropControlRef: MutableRefObject<L.Marker | undefined>;
  indexRefs: MutableRefObject<Map<string, L.Layer>>;
  labelsRef: MutableRefObject<L.LayerGroup | undefined>;
  ndviRef: MutableRefObject<L.ImageOverlay | undefined>;
  ndviResponseRef: MutableRefObject<NdviResponse | null>;
  ndviTileRef: MutableRefObject<L.TileLayer | undefined>;
  roiIndexResponsesRef: MutableRefObject<
    Partial<Record<"NDVI" | "NDWI" | "NDRE", NdviResponse>> | null
  >;
  selectedRoiRef: MutableRefObject<unknown>;
  selectedRoisRef: MutableRefObject<Map<string, unknown>>;
  treeDataRef: MutableRefObject<TreeCollection | null>;
  treeRef: MutableRefObject<L.GeoJSON | undefined>;
}

export function resetOrthomosaicArtifacts({
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
}: ResetOrthomosaicArtifactsParams) {
  ndviRef.current?.remove();
  ndviRef.current = undefined;
  ndviTileRef.current?.remove();
  ndviTileRef.current = undefined;
  indexRefs.current.forEach((layer) => layer.remove());
  indexRefs.current.clear();
  treeRef.current?.remove();
  labelsRef.current?.clearLayers();
  treeDataRef.current = null;
  ndviResponseRef.current = null;
  roiIndexResponsesRef.current = null;
  selectedRoisRef.current.clear();
  selectedRoiRef.current = null;
  cropControlRef.current?.remove();
  cropControlRef.current = undefined;
}

interface MountUploadedOrthomosaicParams {
  backendUrl: (path: string) => string;
  bounds: [[number, number], [number, number]];
  mapRef: RefObject<L.Map | undefined>;
  orthoRef: MutableRefObject<L.TileLayer | undefined>;
}

export function mountUploadedOrthomosaic({
  backendUrl,
  bounds,
  mapRef,
  orthoRef,
}: MountUploadedOrthomosaicParams) {
  const map = mapRef.current;
  if (!map) return false;
  orthoRef.current?.remove();
  orthoRef.current = L.tileLayer(backendUrl("/tiles/rgb/{z}/{x}/{y}.png"), {
    tileSize: 512,
    zoomOffset: -1,
    maxNativeZoom: 24,
    maxZoom: 24,
    keepBuffer: 3,
    updateWhenIdle: true,
    updateWhenZooming: false,
    opacity: 1,
  }).addTo(map);
  map.fitBounds(L.latLngBounds(bounds));
  return true;
}

interface MountStoredOrthomosaicParams {
  backendUrl: (path: string) => string;
  bounds: [[number, number], [number, number]];
  mapRef: RefObject<L.Map | undefined>;
  orthomosaicId: string;
  orthoRef: MutableRefObject<L.TileLayer | undefined>;
}

export function mountStoredOrthomosaic({
  backendUrl,
  bounds,
  mapRef,
  orthomosaicId,
  orthoRef,
}: MountStoredOrthomosaicParams) {
  const map = mapRef.current;
  if (!map) return false;
  orthoRef.current?.remove();
  orthoRef.current = L.tileLayer(
    backendUrl(
      `/tiles/rgb/{z}/{x}/{y}.png?orthomosaic_id=${encodeURIComponent(orthomosaicId)}`,
    ),
    {
      tileSize: 512,
      zoomOffset: -1,
      maxNativeZoom: 24,
      maxZoom: 24,
      keepBuffer: 3,
      updateWhenIdle: true,
      opacity: 1,
    },
  ).addTo(map);
  map.fitBounds(L.latLngBounds(bounds));
  return true;
}
