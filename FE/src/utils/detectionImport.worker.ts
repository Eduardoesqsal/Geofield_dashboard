import { parseDetectionFiles } from "./importFormats";
import { normalizeTreeCollection } from "./tree";

self.onmessage = async (event: MessageEvent<File[]>) => {
  try {
    const parsed = normalizeTreeCollection(await parseDetectionFiles(event.data));
    self.postMessage({ collection: parsed });
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : String(error) });
  }
};
