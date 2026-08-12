import type { Feature, FeatureCollection, Geometry, Position } from "geojson";

/** Resultado uniforme al que se convierten todos los formatos geoespaciales. */
type ParsedCollection = FeatureCollection<Geometry, Record<string, unknown>>;

function collection(
  features: Feature<Geometry, Record<string, unknown>>[],
): ParsedCollection {
  return { type: "FeatureCollection", features };
}

/** Interpreta una coordenada KML y descarta pares incompletos. */
function coordinatePair(value: string): Position | null {
  const values = value
    .trim()
    .split(/[\s,]+/)
    .map(Number);
  return Number.isFinite(values[0]) && Number.isFinite(values[1])
    ? [values[0], values[1]]
    : null;
}

/** Convierte las geometrías KML compatibles al contrato GeoJSON. */
function kmlGeometry(element: Element): Geometry | null {
  const coordinates = element.querySelector("coordinates")?.textContent ?? "";
  const pairs = coordinates
    .trim()
    .split(/\s+/)
    .map(coordinatePair)
    .filter((pair): pair is Position => pair !== null);
  if (!pairs.length) return null;

  if (element.localName === "Point")
    return { type: "Point", coordinates: pairs[0] };
  if (element.localName === "LineString")
    return { type: "LineString", coordinates: pairs };
  if (element.localName === "Polygon") {
    const rings = Array.from(element.querySelectorAll("LinearRing"))
      .map((ring) => {
        const ringPairs = (ring.textContent ?? "")
          .trim()
          .split(/\s+/)
          .map(coordinatePair)
          .filter((pair): pair is Position => pair !== null);
        return ringPairs.length > 2 ? ringPairs : null;
      })
      .filter((ring): ring is Position[] => ring !== null);
    return rings.length ? { type: "Polygon", coordinates: rings } : null;
  }
  return null;
}

/** Recorre los Placemark de un documento KML y conserva nombre y geometría. */
function parseKml(text: string): ParsedCollection {
  const document = new DOMParser().parseFromString(text, "application/xml");
  if (document.querySelector("parsererror"))
    throw new Error("El archivo KML no tiene un XML válido.");
  const features: Feature<Geometry, Record<string, unknown>>[] = [];
  document.querySelectorAll("Placemark").forEach((placemark) => {
    const geometryElement = Array.from(placemark.children).find((child) =>
      ["Point", "LineString", "Polygon"].includes(child.localName),
    );
    const geometry = geometryElement ? kmlGeometry(geometryElement) : null;
    if (!geometry) return;
    const name = placemark.querySelector("name")?.textContent?.trim();
    features.push({
      type: "Feature",
      geometry,
      properties: name ? { name } : {},
    });
  });
  return collection(features);
}

// Lectura binaria mínima para SHP/ZIP sin incorporar dependencias pesadas.
function readString(bytes: Uint8Array, start: number, length: number): string {
  return new TextDecoder()
    .decode(bytes.slice(start, start + length))
    .replace(/\0/g, "")
    .trim();
}

/** Extrae puntos, líneas y polígonos desde los registros binarios de un SHP. */
function parseShp(buffer: ArrayBuffer): ParsedCollection {
  const view = new DataView(buffer);
  const features: Feature<Geometry, Record<string, unknown>>[] = [];
  let offset = 100;
  let recordIndex = 0;
  while (offset + 8 <= buffer.byteLength) {
    const contentLength = view.getInt32(offset + 4, false) * 2;
    const recordStart = offset + 8;
    if (recordStart + contentLength > buffer.byteLength) break;
    const shape = view.getInt32(recordStart, true);
    const recordProperties = { __shp_record_index: recordIndex };
    if (shape === 1 || shape === 11 || shape === 21) {
      // Point, PointZ y PointM comparten X/Y en los primeros 16 bytes.
      features.push({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [
            view.getFloat64(recordStart + 4, true),
            view.getFloat64(recordStart + 12, true),
          ],
        },
        properties: recordProperties,
      });
    } else if (shape === 8 || shape === 18 || shape === 28) {
      // MultiPoint, MultiPointZ y MultiPointM se expanden a detecciones simples.
      const pointCount = view.getInt32(recordStart + 36, true);
      const pointsStart = recordStart + 40;
      const safePointCount =
        pointCount > 0 &&
        pointsStart + pointCount * 16 <= recordStart + contentLength
          ? pointCount
          : 0;
      for (let pointIndex = 0; pointIndex < safePointCount; pointIndex += 1) {
        const pointOffset = pointsStart + pointIndex * 16;
        features.push({
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [
              view.getFloat64(pointOffset, true),
              view.getFloat64(pointOffset + 8, true),
            ],
          },
          properties: recordProperties,
        });
      }
    } else {
      const geometry =
        shape === 3 || shape === 5
          ? parseShapeParts(
              view,
              recordStart,
              shape === 3 ? "LineString" : "Polygon",
            )
          : null;
      if (geometry)
        features.push({
          type: "Feature",
          geometry,
          properties: recordProperties,
        });
    }
    recordIndex += 1;
    offset = recordStart + contentLength;
  }
  return collection(features);
}

/** Lee la tabla DBF complementaria y conserva tipos numéricos para diámetros. */
function parseDbf(buffer: ArrayBuffer): Record<string, unknown>[] {
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  if (buffer.byteLength < 32)
    throw new Error("El archivo DBF está incompleto.");

  const recordCount = view.getUint32(4, true);
  const headerLength = view.getUint16(8, true);
  const recordLength = view.getUint16(10, true);
  const decoder = new TextDecoder("windows-1252");
  const fields: Array<{ name: string; type: string; length: number }> = [];

  for (
    let offset = 32;
    offset + 32 <= headerLength && bytes[offset] !== 0x0d;
    offset += 32
  ) {
    fields.push({
      name: decoder
        .decode(bytes.slice(offset, offset + 11))
        .replace(/\0/g, "")
        .trim(),
      type: String.fromCharCode(bytes[offset + 11]),
      length: bytes[offset + 16],
    });
  }

  return Array.from({ length: recordCount }, (_, recordIndex) => {
    const start = headerLength + recordIndex * recordLength;
    if (start + recordLength > bytes.length || bytes[start] === 0x2a) return {};
    const properties: Record<string, unknown> = {};
    let cursor = start + 1;
    fields.forEach((field) => {
      const raw = decoder
        .decode(bytes.slice(cursor, cursor + field.length))
        .trim();
      cursor += field.length;
      if (!raw) return;
      if (field.type === "N" || field.type === "F") {
        const numeric = Number(raw);
        properties[field.name] = Number.isFinite(numeric) ? numeric : raw;
      } else if (field.type === "L") {
        properties[field.name] = /^[YyTt]$/.test(raw);
      } else if (field.type === "D" && /^\d{8}$/.test(raw)) {
        properties[field.name] =
          `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
      } else {
        properties[field.name] = raw;
      }
    });
    return properties;
  });
}

/** Une por posición las geometrías SHP con sus atributos DBF. */
function attachDbf(
  source: ParsedCollection,
  properties: Record<string, unknown>[],
): ParsedCollection {
  return collection(
    source.features.map((feature, index) => ({
      ...feature,
      properties: {
        ...Object.fromEntries(
          Object.entries(feature.properties ?? {}).filter(
            ([key]) => key !== "__shp_record_index",
          ),
        ),
        ...(properties[
          Number(feature.properties?.__shp_record_index ?? index)
        ] ?? {}),
      },
    })),
  );
}

/** Reconstruye las partes de una línea o los anillos de un polígono SHP. */
function parseShapeParts(
  view: DataView,
  start: number,
  type: "LineString" | "Polygon",
): Geometry | null {
  const parts = view.getInt32(start + 36, true);
  const points = view.getInt32(start + 40, true);
  if (!parts || !points) return null;
  const partsOffset = start + 44;
  const pointsOffset = partsOffset + parts * 4;
  const rings: Position[][] = [];
  for (let part = 0; part < parts; part += 1) {
    const from = view.getInt32(partsOffset + part * 4, true);
    const to =
      part + 1 < parts
        ? view.getInt32(partsOffset + (part + 1) * 4, true)
        : points;
    const line: Position[] = [];
    for (let index = from; index < to; index += 1)
      line.push([
        view.getFloat64(pointsOffset + index * 16, true),
        view.getFloat64(pointsOffset + index * 16 + 8, true),
      ]);
    if (line.length > 1) rings.push(line);
  }
  if (type === "LineString")
    return rings.length === 1
      ? { type, coordinates: rings[0] }
      : { type: "MultiLineString", coordinates: rings };
  return rings.length === 1
    ? { type, coordinates: rings }
    : { type: "MultiPolygon", coordinates: rings.map((ring) => [ring]) };
}

/** Localiza y descomprime una entrada concreta dentro de un contenedor ZIP. */
async function unzipEntry(
  buffer: ArrayBuffer,
  extension: string,
): Promise<Uint8Array> {
  const bytes = new Uint8Array(buffer);
  const view = new DataView(buffer);
  let offset = 0;
  while (offset + 30 <= bytes.length) {
    if (view.getUint32(offset, true) !== 0x04034b50) break;
    const method = view.getUint16(offset + 8, true);
    const compressedSize = view.getUint32(offset + 18, true);
    const nameLength = view.getUint16(offset + 26, true);
    const extraLength = view.getUint16(offset + 28, true);
    const name = readString(bytes, offset + 30, nameLength).toLowerCase();
    const dataStart = offset + 30 + nameLength + extraLength;
    const compressed = bytes.slice(dataStart, dataStart + compressedSize);
    if (name.endsWith(extension)) {
      return method === 0
        ? compressed
        : new Uint8Array(
            await new Response(
              new Blob([compressed])
                .stream()
                .pipeThrough(new DecompressionStream("deflate-raw")),
            ).arrayBuffer(),
          );
    }
    offset = dataStart + compressedSize;
  }
  throw new Error(
    `El archivo comprimido no contiene un ${extension.slice(1)} válido.`,
  );
}

/** KMZ es un ZIP cuyo contenido geográfico principal es un archivo KML. */
async function unzipKmz(buffer: ArrayBuffer): Promise<string> {
  return new TextDecoder().decode(await unzipEntry(buffer, ".kml"));
}

/**
 * Detecta el formato por extensión y devuelve un FeatureCollection listo para
 * guardar o representar en Leaflet.
 */
export async function parseImportFile(file: File): Promise<ParsedCollection> {
  const extension = file.name.toLowerCase().split(".").pop();
  if (extension === "kml") return parseKml(await file.text());
  if (extension === "kmz")
    return parseKml(await unzipKmz(await file.arrayBuffer()));
  if (extension === "shp") return parseShp(await file.arrayBuffer());
  if (extension === "zip") {
    const bytes = await unzipEntry(await file.arrayBuffer(), ".shp");
    const shpBuffer = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(shpBuffer).set(bytes);
    return parseShp(shpBuffer);
  }
  const parsed = JSON.parse(await file.text()) as
    | ParsedCollection
    | Feature<Geometry, Record<string, unknown>>;
  if (parsed.type === "Feature") return collection([parsed]);
  if (parsed.type !== "FeatureCollection" || !Array.isArray(parsed.features))
    throw new Error("El archivo debe ser un FeatureCollection GeoJSON.");
  return parsed;
}

/**
 * Importador específico de detecciones. Admite GeoJSON, un juego SHP+DBF o un
 * ZIP que contenga ambos archivos y normaliza el resultado a puntos de árbol.
 */
export async function parseDetectionFiles(
  files: File[],
): Promise<import("../types/geo").TreeCollection> {
  if (!files.length) throw new Error("Selecciona un archivo de detecciones.");
  const lowerName = (file: File) => file.name.toLowerCase();
  const zip = files.find((file) => lowerName(file).endsWith(".zip"));
  let parsed: ParsedCollection;

  if (zip) {
    const buffer = await zip.arrayBuffer();
    const shpBytes = await unzipEntry(buffer, ".shp");
    const shpBuffer = shpBytes.buffer.slice(
      shpBytes.byteOffset,
      shpBytes.byteOffset + shpBytes.byteLength,
    ) as ArrayBuffer;
    parsed = parseShp(shpBuffer);
    try {
      const dbfBytes = await unzipEntry(buffer, ".dbf");
      const dbfBuffer = dbfBytes.buffer.slice(
        dbfBytes.byteOffset,
        dbfBytes.byteOffset + dbfBytes.byteLength,
      ) as ArrayBuffer;
      parsed = attachDbf(parsed, parseDbf(dbfBuffer));
    } catch {
      // El SHP sigue siendo utilizable como puntos aunque no incluya atributos.
    }
  } else {
    const shp = files.find((file) => lowerName(file).endsWith(".shp"));
    if (shp) {
      parsed = parseShp(await shp.arrayBuffer());
      const shapefileStem = lowerName(shp).replace(/\.shp$/, "");
      const dbf = files.find(
        (file) => lowerName(file).replace(/\.dbf$/, "") === shapefileStem,
      );
      if (dbf) parsed = attachDbf(parsed, parseDbf(await dbf.arrayBuffer()));
    } else {
      const geojson = files.find((file) =>
        /\.(geojson|json)$/i.test(file.name),
      );
      if (!geojson)
        throw new Error(
          "Importa un GeoJSON, un SHP con su DBF o un ZIP de Shapefile.",
        );
      parsed = await parseImportFile(geojson);
    }
  }

  const points = parsed.features.flatMap((feature) => {
    if (
      feature.geometry.type !== "Point" ||
      feature.geometry.coordinates.length < 2
    )
      return [];
    return [
      {
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [
            Number(feature.geometry.coordinates[0]),
            Number(feature.geometry.coordinates[1]),
          ] as [number, number],
        },
        properties: feature.properties,
      },
    ];
  });
  if (!points.length)
    throw new Error("El archivo no contiene detecciones puntuales válidas.");
  return { type: "FeatureCollection", features: points };
}
