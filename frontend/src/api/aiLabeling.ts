import { apiClient, downloadApiFile, UPLOAD_TIMEOUT_MS } from "./client";
import type { TrainingJob } from "./aiTraining";

export interface LabelPoint {
  x: number;
  y: number;
}

export interface LabelBox {
  id?: string;
  product_id: string;
  product_name?: string;
  sku?: string;
  cx: number;
  cy: number;
  w: number;
  h: number;
  polygon?: LabelPoint[] | null;
}

export interface LabelImageSummary {
  id: string;
  storage_key: string;
  original_filename: string | null;
  image_width: number | null;
  image_height: number | null;
  box_count: number;
  labeled: boolean;
  is_cropped: boolean;
  preview_url?: string | null;
  created_at: string;
}

export interface LabelImageDetail extends LabelImageSummary {
  preview_url: string;
  boxes: LabelBox[];
}

export interface LabelImageListResponse {
  items: LabelImageSummary[];
  total: number;
  labeled_count: number;
  pending_count: number;
}

export interface LabelingStats {
  total_images: number;
  labeled_images: number;
  pending_images: number;
  pending_crop: number;
  total_boxes: number;
  distinct_skus: number;
  ready_for_training: boolean;
  training_message: string | null;
}

export interface BulkUploadResponse {
  uploaded: number;
  failed: number;
  items: LabelImageSummary[];
}

export async function uploadLabelImages(files: File[]): Promise<BulkUploadResponse> {
  const form = new FormData();
  for (const f of files) {
    form.append("images", f);
  }
  const { data } = await apiClient.post<BulkUploadResponse>(
    "/ai/training/labels/images",
    form,
    {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: UPLOAD_TIMEOUT_MS,
    }
  );
  return data;
}

export async function listLabelImages(params?: {
  skip?: number;
  limit?: number;
  labeled?: boolean;
  cropped?: boolean;
  product_id?: string;
}): Promise<LabelImageListResponse> {
  const { data } = await apiClient.get<LabelImageListResponse>(
    "/ai/training/labels/images",
    { params }
  );
  return data;
}

export async function getLabelImage(imageId: string): Promise<LabelImageDetail> {
  const { data } = await apiClient.get<LabelImageDetail>(
    `/ai/training/labels/images/${imageId}`
  );
  return data;
}

export async function saveLabelBoxes(
  imageId: string,
  boxes: Omit<LabelBox, "id" | "product_name" | "sku">[]
): Promise<LabelBox[]> {
  const { data } = await apiClient.put<LabelBox[]>(
    `/ai/training/labels/images/${imageId}/boxes`,
    { boxes }
  );
  return data;
}

export interface CropRect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export async function cropLabelImage(
  imageId: string,
  rect: CropRect
): Promise<LabelImageDetail> {
  const { data } = await apiClient.post<LabelImageDetail>(
    `/ai/training/labels/images/${imageId}/crop`,
    rect
  );
  return data;
}

export async function markLabelImageCropped(imageId: string): Promise<LabelImageSummary> {
  const { data } = await apiClient.post<LabelImageSummary>(
    `/ai/training/labels/images/${imageId}/mark-cropped`
  );
  return data;
}

export async function deleteLabelImage(imageId: string): Promise<void> {
  await apiClient.delete(`/ai/training/labels/images/${imageId}`);
}

export async function getLabelingStats(): Promise<LabelingStats> {
  const { data } = await apiClient.get<LabelingStats>("/ai/training/labels/stats");
  return data;
}

export async function exportLabelImages(options?: {
  mode?: "crops" | "scenes";
  productId?: string;
}): Promise<void> {
  const params: Record<string, string | undefined> = {
    mode: options?.mode ?? "crops",
  };
  if (options?.productId) params.product_id = options.productId;
  await downloadApiFile("/ai/training/labels/export", params, "label-images.zip");
}

export async function createLabeledTrainingJob(payload: {
  name: string;
  epochs?: number;
  image_size?: number;
}): Promise<TrainingJob> {
  const { data } = await apiClient.post<TrainingJob>(
    "/ai/training/labels/jobs",
    payload
  );
  return data;
}

/** Draft box while drawing (pixel-normalized 0–1). */
export interface DraftBox {
  clientId: string;
  product_id: string;
  sku: string;
  product_name: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  /** Hiển thị trên canvas; lưu DB nhưng không dùng train YOLO. */
  polygon?: LabelPoint[];
}

export function draftToYolo(box: DraftBox): Omit<LabelBox, "id"> {
  const x1 = Math.min(box.x1, box.x2);
  const x2 = Math.max(box.x1, box.x2);
  const y1 = Math.min(box.y1, box.y2);
  const y2 = Math.max(box.y1, box.y2);
  const w = x2 - x1;
  const h = y2 - y1;
  const payload: Omit<LabelBox, "id"> = {
    product_id: box.product_id,
    cx: x1 + w / 2,
    cy: y1 + h / 2,
    w,
    h,
  };
  if (box.polygon && box.polygon.length >= 3) {
    payload.polygon = box.polygon.map((p) => ({ x: p.x, y: p.y }));
  }
  return payload;
}

export function yoloToDraft(
  box: LabelBox,
  sku: string,
  product_name: string
): DraftBox {
  const x1 = box.cx - box.w / 2;
  const y1 = box.cy - box.h / 2;
  const draft: DraftBox = {
    clientId: box.id ?? crypto.randomUUID(),
    product_id: box.product_id,
    sku,
    product_name,
    x1,
    y1,
    x2: x1 + box.w,
    y2: y1 + box.h,
  };
  if (box.polygon && box.polygon.length >= 3) {
    draft.polygon = box.polygon.map((p) => ({ x: p.x, y: p.y }));
  }
  return draft;
}
