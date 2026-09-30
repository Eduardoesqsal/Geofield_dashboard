import type { NdviResponse } from "../services/api";
import L from "leaflet";
import type { TreeCollection, TreeFeature } from "../types/geo";
import { diameterOf } from "./tree";

/** Media de VARI de los píxeles válidos bajo la copa de un árbol. */
export function treeVariValue(response: NdviResponse, feature: TreeFeature): number | null {
  const { matrix, mask, bounds } = response;
  const diameter = diameterOf(feature);
  if (!bounds || !matrix.length || !matrix[0]?.length ||
      !Number.isFinite(diameter) || diameter <= 0) return null;
  const height = matrix.length;
  const width = matrix[0].length;
  const [[south, west], [north, east]] = bounds;
  const [longitude, latitude] = feature.geometry.coordinates;
  const spanLongitude = east - west;
  const spanLatitude = north - south;
  if (spanLongitude <= 0 || spanLatitude <= 0) return null;
  const centerX = (longitude - west) / spanLongitude * width;
  const centerY = (north - latitude) / spanLatitude * height;
  if (centerX < 0 || centerX >= width || centerY < 0 || centerY >= height) return null;
  const radiusMeters = diameter / 2;
  const radiusX = radiusMeters / (111_320 * Math.max(0.01, Math.cos(latitude * Math.PI / 180)))
    / spanLongitude * width;
  const radiusY = radiusMeters / 111_320 / spanLatitude * height;
  if (radiusX <= 0 || radiusY <= 0) return null;

  let sum = 0;
  let count = 0;
  const left = Math.max(0, Math.floor(centerX - radiusX));
  const right = Math.min(width - 1, Math.ceil(centerX + radiusX));
  const top = Math.max(0, Math.floor(centerY - radiusY));
  const bottom = Math.min(height - 1, Math.ceil(centerY + radiusY));
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const dx = (x + 0.5 - centerX) / radiusX;
      const dy = (y + 0.5 - centerY) / radiusY;
      if (dx * dx + dy * dy > 1) continue;
      const value = matrix[y]?.[x];
      if (!Number.isFinite(value) || Number(mask?.[y]?.[x] ?? 1) <= 0) continue;
      sum += value;
      count += 1;
    }
  }
  if (count) return sum / count;
  const nearestX = Math.floor(centerX);
  const nearestY = Math.floor(centerY);
  const nearest = matrix[nearestY]?.[nearestX];
  return Number.isFinite(nearest) && Number(mask?.[nearestY]?.[nearestX] ?? 1) > 0
    ? nearest : null;
}


/** Usa los mismos tiles VARI del índice general y oculta lo exterior a las copas. */
export function createVariDiameterTileLayer(
  urlTemplate: string,
  detections: TreeCollection,
): L.GridLayer {
  type ProjectedCircle = { x: number; y: number; radiusX: number; radiusY: number };
  const circlesByZoom = new Map<number, ProjectedCircle[]>();

  class VariDiameterLayer extends L.GridLayer {
    createTile(coords: L.Coords, done: L.DoneCallback): HTMLElement {
      const canvas = document.createElement("canvas");
      canvas.width = 256;
      canvas.height = 256;
      const context = canvas.getContext("2d");
      if (!context) {
        queueMicrotask(() => done(new Error("No se pudo crear el tile VARI."), canvas));
        return canvas;
      }
      let circles = circlesByZoom.get(coords.z);
      if (!circles) {
        circles = detections.features.flatMap((feature) => {
          const diameter = diameterOf(feature);
          if (!Number.isFinite(diameter) || diameter <= 0) return [];
          const [longitude, latitude] = feature.geometry.coordinates;
          const center = L.CRS.EPSG3857.latLngToPoint(L.latLng(latitude, longitude), coords.z);
          const radiusMeters = diameter / 2;
          const latitudeOffset = radiusMeters / 111_320;
          const longitudeOffset = radiusMeters /
            (111_320 * Math.max(0.01, Math.cos(latitude * Math.PI / 180)));
          const east = L.CRS.EPSG3857.latLngToPoint(
            L.latLng(latitude, longitude + longitudeOffset), coords.z,
          );
          const north = L.CRS.EPSG3857.latLngToPoint(
            L.latLng(latitude + latitudeOffset, longitude), coords.z,
          );
          return [{
            x: center.x,
            y: center.y,
            radiusX: Math.abs(east.x - center.x),
            radiusY: Math.abs(north.y - center.y),
          }];
        });
        circlesByZoom.set(coords.z, circles);
      }
      const tileLeft = coords.x * 256;
      const tileTop = coords.y * 256;
      const intersecting = circles.filter(({ x, y, radiusX, radiusY }) =>
        x + radiusX >= tileLeft && x - radiusX <= tileLeft + 256 &&
        y + radiusY >= tileTop && y - radiusY <= tileTop + 256,
      );
      if (!intersecting.length) {
        queueMicrotask(() => done(undefined, canvas));
        return canvas;
      }

      const image = new Image();
      image.crossOrigin = "anonymous";
      image.onload = () => {
        context.drawImage(image, 0, 0, 256, 256);
        const mask = document.createElement("canvas");
        mask.width = 256;
        mask.height = 256;
        const maskContext = mask.getContext("2d");
        if (!maskContext) {
          context.clearRect(0, 0, 256, 256);
          done(new Error("No se pudo crear la máscara VARI."), canvas);
          return;
        }
        maskContext.fillStyle = "#fff";
        for (const { x, y, radiusX, radiusY } of intersecting) {
          const centerX = x - tileLeft;
          const centerY = y - tileTop;
          const safeRadiusX = Math.max(radiusX, 0.01);
          const safeRadiusY = Math.max(radiusY, 0.01);
          maskContext.beginPath();
          maskContext.ellipse(centerX, centerY,
            safeRadiusX, safeRadiusY, 0, 0, Math.PI * 2);
          maskContext.fill();
        }
        context.globalCompositeOperation = "destination-in";
        context.drawImage(mask, 0, 0);
        done(undefined, canvas);
      };
      image.onerror = () => done(new Error("No se pudo cargar el tile VARI."), canvas);
      image.src = urlTemplate
        .replace("{z}", String(coords.z))
        .replace("{x}", String(coords.x))
        .replace("{y}", String(coords.y));
      return canvas;
    }
  }

  return new VariDiameterLayer({
    pane: "classificationImagePane",
    tileSize: 256,
    maxNativeZoom: 24,
    maxZoom: 24,
    keepBuffer: 3,
    updateWhenIdle: true,
    updateWhenZooming: false,
    opacity: 1,
  });
}
