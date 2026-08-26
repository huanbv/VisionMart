import { apiClient, downloadApiFile, UPLOAD_TIMEOUT_MS } from "./client";

export interface TrainingImage {
  id: string;
  product_id: string;
  storage_key: string;
  image_size_bytes: number;
  image_format: string | null;
  created_at: string;
  preview_url: string | null;
}

export interface TrainingImageList {
  items: TrainingImage[];
  total: number;
}

export interface TrainingJob {
  id: string;
  name: string;
  status: "pending" | "running" | "succeeded" | "failed";
  epochs: number;
  image_size: number;
  branch_id: string | null;
  class_map: Record<string, unknown>;
  metrics: Record<string, number> | null;
  weight_key: string | null;
  error_message: string | null;
  deployed_at: string | null;
  created_at: string;
  updated_at: string;
  progress?: string | null;
  current_epoch?: number | null;
  total_epochs?: number | null;
  /** "preparing" | "training" | "uploading" | "done" */
  stage?: string | null;
  images_total?: number | null;
  images_done?: number | null;
  class_counts?: Record<string, number> | null;
  train_count?: number | null;
  val_count?: number | null;
  started_at_ts?: number | null;
  finished_at_ts?: number | null;
}

export interface TrainingJobList {
  items: TrainingJob[];
  total: number;
}

export interface CreateTrainingJobPayload {
  name: string;
  product_ids: string[];
  branch_id?: string | null;
  epochs?: number;
  image_size?: number;
}

export async function uploadTrainingImage(
  productId: string,
  file: File
): Promise<TrainingImage> {
  const form = new FormData();
  form.append("product_id", productId);
  form.append("image", file);
  const { data } = await apiClient.post<TrainingImage>(
    "/ai/training/images",
    form,
    {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: UPLOAD_TIMEOUT_MS,
    }
  );
  return data;
}

export async function listTrainingImages(
  productId?: string
): Promise<TrainingImageList> {
  const { data } = await apiClient.get<TrainingImageList>(
    "/ai/training/images",
    { params: productId ? { product_id: productId } : {} }
  );
  return data;
}

export async function deleteTrainingImage(imageId: string): Promise<void> {
  await apiClient.delete(`/ai/training/images/${imageId}`);
}

export async function createTrainingJob(
  payload: CreateTrainingJobPayload
): Promise<TrainingJob> {
  const { data } = await apiClient.post<TrainingJob>(
    "/ai/training/jobs",
    payload
  );
  return data;
}

export async function listTrainingJobs(): Promise<TrainingJobList> {
  const { data } = await apiClient.get<TrainingJobList>("/ai/training/jobs");
  return data;
}

export async function getTrainingJob(jobId: string): Promise<TrainingJob> {
  const { data } = await apiClient.get<TrainingJob>(
    `/ai/training/jobs/${jobId}`
  );
  return data;
}

/**
 * Result of the regression gate: how this candidate's metrics compare to
 * the weight currently live.
 *
 * `comparable === false` means no verdict was possible (first deploy, or
 * metrics missing) — the UI must say "not verified" rather than implying
 * the model passed a check that never ran.
 */
export interface DeployCheck {
  allowed: boolean;
  reason: string;
  metric_name: string | null;
  candidate_value: number | null;
  baseline_value: number | null;
  delta: number | null;
  comparable: boolean;
  details: Record<string, number>;
}

export async function exportTrainingImages(productId?: string): Promise<void> {
  await downloadApiFile(
    "/ai/training/images/export",
    productId ? { product_id: productId } : undefined,
    "training-images.zip"
  );
}

/** Dry-run the regression gate before committing to a deploy. */
export async function checkDeploy(jobId: string): Promise<DeployCheck> {
  const { data } = await apiClient.get<DeployCheck>(
    `/ai/training/jobs/${jobId}/deploy-check`,
  );
  return data;
}

export async function deployTrainingJob(
  jobId: string,
  force = false,
): Promise<TrainingJob> {
  const { data } = await apiClient.post<TrainingJob>(
    `/ai/training/jobs/${jobId}/deploy`,
    null,
    { params: force ? { force: true } : undefined },
  );
  return data;
}
