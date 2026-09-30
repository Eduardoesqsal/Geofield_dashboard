import type { TreeCollection } from "../types/geo";
import { parseDetectionFiles } from "./importFormats";
import { normalizeTreeCollection } from "./tree";

export async function importDetectionsInWorker(files: File[]): Promise<TreeCollection> {
  if (typeof Worker === "undefined")
    return normalizeTreeCollection(await parseDetectionFiles(files));

  return new Promise<TreeCollection>((resolve, reject) => {
    const worker = new Worker(new URL("./detectionImport.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.onmessage = (event: MessageEvent<{ collection?: TreeCollection; error?: string }>) => {
      worker.terminate();
      if (event.data.error) reject(new Error(event.data.error));
      else if (event.data.collection) resolve(event.data.collection);
      else reject(new Error("El importador no devolvió detecciones."));
    };
    worker.onerror = (event) => {
      worker.terminate();
      reject(new Error(event.message || "No se pudo leer el archivo de detecciones."));
    };
    worker.postMessage(files);
  });
}
