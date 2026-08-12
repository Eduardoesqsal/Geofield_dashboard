/** Geometría puntual normalizada usada por las detecciones de árboles. */
export interface TreeGeometry {
  type: "Point";
  coordinates: [number, number];
}

/** Feature GeoJSON de árbol; sus propiedades admiten campos de fuentes distintas. */
export interface TreeFeature {
  type: "Feature";
  geometry: TreeGeometry;
  properties: Record<string, unknown> | null;
}

/** Colección GeoJSON que alimenta las capas y filtros de detecciones. */
export interface TreeCollection {
  type: "FeatureCollection";
  features: TreeFeature[];
}

/** Resumen agregado que el panel utiliza para conteos y diámetros. */
export interface TreeStats {
  count: number;
  mean: number;
  min: number;
  max: number;
  small: number;
  medium: number;
  large: number;
  unknown: number;
}
