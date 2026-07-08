import { apiClient } from "./client";

export interface Camera {
  id: string;
  organization_id: string;
  branch_id: string;
  branch_name: string | null;
  code: string;
  name: string;
  stream_url: string;
  location: string | null;
  resolution: string | null;
  fps: number | null;
  config: Record<string, unknown> | null;
  is_online: boolean;
  is_active: boolean;
  auto_capture_enabled: boolean;
  is_checkout_zone: boolean;
  alert_classes: string | null;
  alert_min_confidence: number | null;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CameraListResponse {
  items: Camera[];
  total: number;
  skip: number;
  limit: number;
}

export interface CameraCreatePayload {
  code: string;
  name: string;
  branch_id: string;
  stream_url: string;
  location?: string | null;
  resolution?: string | null;
  fps?: number | null;
  config?: Record<string, unknown> | null;
  is_active?: boolean;
  auto_capture_enabled?: boolean;
  is_checkout_zone?: boolean;
  alert_classes?: string | null;
  alert_min_confidence?: number | null;
}

export interface CameraUpdatePayload {
  code?: string;
  name?: string;
  branch_id?: string;
  stream_url?: string;
  location?: string | null;
  resolution?: string | null;
  fps?: number | null;
  config?: Record<string, unknown> | null;
  is_active?: boolean;
  auto_capture_enabled?: boolean;
  is_checkout_zone?: boolean;
  alert_classes?: string | null;
  alert_min_confidence?: number | null;
  location_unset?: boolean;
  resolution_unset?: boolean;
  fps_unset?: boolean;
  config_unset?: boolean;
  alert_classes_unset?: boolean;
  alert_min_confidence_unset?: boolean;
}

export interface CameraStats {
  total: number;
  online: number;
  active: number;
}

export async function listCameras(params: {
  skip?: number;
  limit?: number;
  search?: string;
  branch_id?: string;
  is_active?: boolean;
  is_online?: boolean;
}): Promise<CameraListResponse> {
  const { data } = await apiClient.get<CameraListResponse>("/cameras", {
    params,
  });
  return data;
}

export async function getCameraStats(): Promise<CameraStats> {
  const { data } = await apiClient.get<CameraStats>("/cameras/stats");
  return data;
}

export async function getCamera(id: string): Promise<Camera> {
  const { data } = await apiClient.get<Camera>(`/cameras/${id}`);
  return data;
}

export async function createCamera(
  payload: CameraCreatePayload,
): Promise<Camera> {
  const { data } = await apiClient.post<Camera>("/cameras", payload);
  return data;
}

export async function updateCamera(
  id: string,
  payload: CameraUpdatePayload,
): Promise<Camera> {
  const { data } = await apiClient.patch<Camera>(`/cameras/${id}`, payload);
  return data;
}

export async function heartbeatCamera(
  id: string,
  online: boolean,
): Promise<Camera> {
  const { data } = await apiClient.post<Camera>(`/cameras/${id}/heartbeat`, {
    online,
  });
  return data;
}

export async function deleteCamera(id: string): Promise<void> {
  await apiClient.delete(`/cameras/${id}`);
}

export interface DetectionBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface Detection {
  class_name: string;
  confidence: number;
  bbox: DetectionBox;
  stub?: boolean;
}

export interface FramePipelineEvent {
  event: {
    event_type: string;
    product_sku: string | null;
    track_id: string;
    confidence: number;
    customer_id: string | null;
  };
  backend: { status: number; body: unknown };
}

export interface FramePipelineResult {
  detections: Array<{
    track_id: number;
    class_name: string;
    confidence: number;
    bbox: { x1: number; y1: number; x2: number; y2: number };
  }>;
  persons: number;
  products: number;
  is_checkout_zone: boolean;
  customer_id: string | null;
  emitted_events: FramePipelineEvent[];
}

export interface AnalyzeResult {
  camera_id: string;
  detection_event_id: string;
  model: string;
  image: { width: number; height: number; format: string; size_bytes: number };
  detections: Detection[];
  elapsed_ms: number;
  frame_pipeline?: FramePipelineResult | null;
  frame_pipeline_error?: string | null;
}

export async function analyzeCameraFrame(
  id: string,
  file: File,
  model?: string,
): Promise<AnalyzeResult> {
  const form = new FormData();
  form.append("image", file);
  const { data } = await apiClient.post<AnalyzeResult>(
    `/cameras/${id}/analyze`,
    form,
    {
      params: model ? { model } : undefined,
      headers: { "Content-Type": "multipart/form-data" },
    },
  );
  return data;
}

export interface PreviewResult {
  camera_id: string;
  camera_name: string;
  model: string;
  image: { width: number; height: number; format: string; size_bytes: number };
  elapsed_ms: number;
  detections: Detection[];
  frame_base64: string;
}

export async function previewCameraStream(id: string): Promise<PreviewResult> {
  const { data } = await apiClient.post<PreviewResult>(
    `/cameras/${id}/preview`,
  );
  return data;
}

// Course project — no physical cameras yet. Uploads a demo video that a
// standalone camera-sim-runner service loops as an RTSP stream, and the
// backend auto-updates this camera's stream_url to match. See
// docs/21_CAMERA_MANAGER.md and docker-compose.yml's "camera-sim" block.
export async function uploadSimulatedStream(
  id: string,
  file: File,
): Promise<Camera> {
  const form = new FormData();
  form.append("video", file);
  const { data } = await apiClient.post<Camera>(
    `/cameras/${id}/simulated-stream`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}
