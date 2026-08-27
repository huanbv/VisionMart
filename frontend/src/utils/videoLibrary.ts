import type { RoiZone } from "@/api/cameras";

const DB_NAME = "visionmart-video-lib";
const STORE = "videos";
const DB_VERSION = 1;

export type VideoLibraryMeta = {
  id: string;
  name: string;
  size: number;
  type: string;
  createdAt: number;
  roiZones: RoiZone[];
};

type VideoRecord = VideoLibraryMeta & { blob: Blob };

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexedDB open failed"));
  });
}

function reqToPromise<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexedDB request failed"));
  });
}

export async function listLibraryVideos(): Promise<VideoLibraryMeta[]> {
  const db = await openDb();
  const rows = await reqToPromise(
    db.transaction(STORE, "readonly").objectStore(STORE).getAll(),
  );
  db.close();
  return (rows as VideoRecord[])
    .map(({ blob: _blob, ...meta }) => meta)
    .sort((a, b) => b.createdAt - a.createdAt);
}

export async function addLibraryVideo(file: File): Promise<VideoLibraryMeta> {
  const record: VideoRecord = {
    id: crypto.randomUUID(),
    name: file.name,
    size: file.size,
    type: file.type || "video/mp4",
    createdAt: Date.now(),
    roiZones: [],
    blob: file,
  };
  const db = await openDb();
  try {
    await reqToPromise(db.transaction(STORE, "readwrite").objectStore(STORE).put(record));
  } catch (err) {
    db.close();
    const quota =
      err instanceof DOMException &&
      (err.name === "QuotaExceededError" || err.code === 22);
    if (quota) {
      throw new Error("Thư viện đầy — xóa bớt video cũ rồi tải lại.");
    }
    throw err;
  }
  db.close();
  const { blob: _blob, ...meta } = record;
  return meta;
}

export async function getLibraryVideo(id: string): Promise<VideoRecord | null> {
  const db = await openDb();
  const row = await reqToPromise(
    db.transaction(STORE, "readonly").objectStore(STORE).get(id),
  );
  db.close();
  return (row as VideoRecord | undefined) ?? null;
}

export async function deleteLibraryVideo(id: string): Promise<void> {
  const db = await openDb();
  await reqToPromise(db.transaction(STORE, "readwrite").objectStore(STORE).delete(id));
  db.close();
}

export async function saveLibraryRoi(id: string, roiZones: RoiZone[]): Promise<void> {
  const row = await getLibraryVideo(id);
  if (!row) return;
  const db = await openDb();
  await reqToPromise(
    db.transaction(STORE, "readwrite").objectStore(STORE).put({ ...row, roiZones }),
  );
  db.close();
}
