import { apiClient } from "./client";

/**
 * Active-learning review queue + runtime tuning of the OpenCV pipeline.
 *
 * The queue exists so retraining happens on *human-confirmed* labels. The
 * API deliberately has no "approve everything" call — approving is the
 * human judgement the whole loop depends on.
 */

export type ReviewStatus = "pending" | "approved" | "rejected";
export type ReviewSource = "low_confidence" | "checkout_mismatch" | "manual";

export interface ReviewCandidate {
  id: string;
  organization_id: string;
  camera_id: string | null;
  storage_key: string;
  image_size_bytes: number;
  source: ReviewSource;
  status: ReviewStatus;
  predicted_product_id: string | null;
  predicted_class: string | null;
  confidence: number | null;
  confirmed_product_id: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  training_image_id: string | null;
  created_at: string;
  preview_url: string | null;
  /** Anh cat rieng vung phat hien — chinh la mau se vao tap huan luyen. */
  crop_key: string | null;
  bbox: { x1: number; y1: number; x2: number; y2: number } | null;
  crop_preview_url: string | null;
}

export interface ReviewCandidateList {
  items: ReviewCandidate[];
  total: number;
}

export interface ReviewStats {
  pending: number;
  approved: number;
  rejected: number;
}

export async function listReviewCandidates(params: {
  status?: ReviewStatus;
  source?: ReviewSource;
  skip?: number;
  limit?: number;
}): Promise<ReviewCandidateList> {
  const { data } = await apiClient.get<ReviewCandidateList>(
    "/ai/review/candidates",
    { params },
  );
  return data;
}

export async function getReviewStats(): Promise<ReviewStats> {
  const { data } = await apiClient.get<ReviewStats>("/ai/review/stats");
  return data;
}

export async function approveCandidate(
  id: string,
  confirmedProductId: string,
  note?: string,
): Promise<ReviewCandidate> {
  const { data } = await apiClient.post<ReviewCandidate>(
    `/ai/review/candidates/${id}/approve`,
    { confirmed_product_id: confirmedProductId, note },
  );
  return data;
}

export async function rejectCandidate(
  id: string,
  note?: string,
): Promise<ReviewCandidate> {
  const { data } = await apiClient.post<ReviewCandidate>(
    `/ai/review/candidates/${id}/reject`,
    { note },
  );
  return data;
}

// ---------------- Runtime vision config ----------------

export interface VisionConfigResponse {
  config_path: string;
  /** Effective values keyed by env-var name (ENABLE_CLAHE, GAMMA_VALUE, …). */
  effective: Record<string, string | number | boolean>;
  /** Only the values explicitly set from the admin UI. */
  overrides: Record<string, string>;
  overridden_keys: string[];
}

export async function getVisionConfig(): Promise<VisionConfigResponse> {
  const { data } = await apiClient.get<VisionConfigResponse>("/ai/vision-config");
  return data;
}

/** Partial update; a `null` value clears that override. */
export async function updateVisionConfig(
  settings: Record<string, string | number | boolean | null>,
): Promise<VisionConfigResponse> {
  const { data } = await apiClient.put<VisionConfigResponse>(
    "/ai/vision-config",
    { settings },
  );
  return data;
}

export async function resetVisionConfig(): Promise<VisionConfigResponse> {
  const { data } = await apiClient.delete<VisionConfigResponse>(
    "/ai/vision-config",
  );
  return data;
}
