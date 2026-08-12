/**
 * Helpers de capas espectrales.
 * Se encargan de crear, reemplazar y retirar overlays NDVI/NDWI/NDRE sobre
 * Leaflet sin duplicar manipulación de capas en otros módulos.
 */
import type { MutableRefObject, RefObject } from "react";
import L from "leaflet";
import type { NdviResponse } from "../services/api";

const TILE_OPTIONS: L.TileLayerOptions = {
  tileSize: 512,
  zoomOffset: -1,
  maxNativeZoom: 24,
  maxZoom: 24,
  keepBuffer: 3,
  updateWhenIdle: true,
  opacity: 1,
};

export function createSpectralTileLayer(url: string): L.TileLayer {
  return L.tileLayer(url, TILE_OPTIONS);
}

interface ReplaceSpectralLayerParams {
  indexRefs: MutableRefObject<Map<string, L.Layer>>;
  mapRef: RefObject<L.Map | undefined>;
  name: string;
  url: string;
}

export function replaceSpectralLayer({
  indexRefs,
  mapRef,
  name,
  url,
}: ReplaceSpectralLayerParams) {
  const map = mapRef.current;
  if (!map) return null;
  indexRefs.current.get(name)?.remove();
  const tileLayer = createSpectralTileLayer(url).addTo(map);
  indexRefs.current.set(name, tileLayer);
  return tileLayer;
}

interface ClearSpectralLayersParams {
  indexRefs: MutableRefObject<Map<string, L.Layer>>;
  ndviRef: MutableRefObject<L.ImageOverlay | undefined>;
  ndviTileRef: MutableRefObject<L.TileLayer | undefined>;
}

export function clearSpectralLayers({
  indexRefs,
  ndviRef,
  ndviTileRef,
}: ClearSpectralLayersParams) {
  ndviRef.current?.remove();
  ndviTileRef.current?.remove();
  ndviTileRef.current = undefined;
  indexRefs.current.forEach((layer) => layer.remove());
  indexRefs.current.clear();
}

interface RemoveSingleSpectralLayerParams {
  indexRefs: MutableRefObject<Map<string, L.Layer>>;
  name: string;
}

export function removeSingleSpectralLayer({
  indexRefs,
  name,
}: RemoveSingleSpectralLayerParams) {
  indexRefs.current.get(name)?.remove();
  indexRefs.current.delete(name);
}

interface ReplaceNdviTileLayerParams {
  mapRef: RefObject<L.Map | undefined>;
  ndviTileRef: MutableRefObject<L.TileLayer | undefined>;
  url: string;
}

export function replaceNdviTileLayer({
  mapRef,
  ndviTileRef,
  url,
}: ReplaceNdviTileLayerParams) {
  const map = mapRef.current;
  if (!map) return null;
  ndviTileRef.current?.remove();
  ndviTileRef.current = createSpectralTileLayer(url);
  ndviTileRef.current.addTo(map);
  return ndviTileRef.current;
}

export function createNdviResponse(
  bounds: [[number, number], [number, number]],
  mask: number[][] | undefined,
  matrix: number[][],
): NdviResponse {
  return { matrix, mask, bounds };
}
