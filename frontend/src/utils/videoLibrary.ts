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
  poster: string | null;
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

function toMeta(row: VideoRecord): VideoLibraryMeta {
  return {
    id: row.id,
    name: row.name,
    size: row.size,
    type: row.type,
    createdAt: row.createdAt,
    roiZones: Array.isArray(row.roiZones) ? row.roiZones : [],
    poster: row.poster ?? null,
  };
}

export function capturePosterFromBlob(blob: Blob): Promise<string | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    video.src = url;
    let done = false;
    const finish = (data: string | null) => {
      if (done) return;
      done = true;
      window.clearTimeout(timer);
      URL.revokeObjectURL(url);
      video.src = "";
      resolve(data);
    };
    const grab = () => {
      const w = video.videoWidth;
      const h = video.videoHeight;
      if (!w || !h) {
        finish(null);
        return;
      }
      const maxW = 320;
      const scale = Math.min(1, maxW / w);
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(w * scale));
      canvas.height = Math.max(1, Math.round(h * scale));
      const ctx = canvas.getContext("2d");
      if (!ctx) {
        finish(null);
        return;
      }
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      finish(canvas.toDataURL("image/jpeg", 0.72));
    };
    video.addEventListener("seeked", grab, { once: true });
    video.addEventListener("loadeddata", () => {
      const t = Math.min(0.4, Math.max(0.05, (video.duration || 1) * 0.08));
      try {
        video.currentTime = t;
      } catch {
        grab();
      }
    });
    video.addEventListener("error", () => finish(null));
    const timer = window.setTimeout(() => finish(null), 8000);
  });
}

export async function listLibraryVideos(): Promise<VideoLibraryMeta[]> {
  const db = await openDb();
  const rows = await reqToPromise(
    db.transaction(STORE, "readonly").objectStore(STORE).getAll(),
  );
  db.close();
  return (rows as VideoRecord[])
    .map(toMeta)
    .sort((a, b) => b.createdAt - a.createdAt);
}

export async function addLibraryVideo(file: File): Promise<VideoLibraryMeta> {
  const poster = await capturePosterFromBlob(file);
  const record: VideoRecord = {
    id: crypto.randomUUID(),
    name: file.name,
    size: file.size,
    type: file.type || "video/mp4",
    createdAt: Date.now(),
    roiZones: [],
    poster,
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
  return toMeta(record);
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

async function patchLibraryVideo(
  id: string,
  patch: Partial<Pick<VideoLibraryMeta, "roiZones" | "poster">>,
): Promise<void> {
  const row = await getLibraryVideo(id);
  if (!row) return;
  const db = await openDb();
  await reqToPromise(
    db.transaction(STORE, "readwrite").objectStore(STORE).put({ ...row, ...patch }),
  );
  db.close();
}

export async function saveLibraryRoi(id: string, roiZones: RoiZone[]): Promise<void> {
  await patchLibraryVideo(id, { roiZones });
}

export async function saveLibraryPoster(id: string, poster: string): Promise<void> {
  await patchLibraryVideo(id, { poster });
}

/** Fill missing posters for videos added before thumbnails existed. */
export async function backfillLibraryPosters(
  onItem?: (id: string, poster: string) => void,
): Promise<void> {
  const items = await listLibraryVideos();
  for (const it of items) {
    if (it.poster) continue;
    const row = await getLibraryVideo(it.id);
    if (!row) continue;
    const poster = await capturePosterFromBlob(row.blob);
    if (!poster) continue;
    await saveLibraryPoster(it.id, poster);
    onItem?.(it.id, poster);
  }
}
