import { apiClient } from "./client";

import type { Detection } from "./cameras";

export interface DetectionEventSummary {
  id: string;
  organization_id: string;
  camera_id: string;
  user_id: string | null;
  model: string;
  image_width: number;
  image_height: number;
  image_format: string | null;
  image_size_bytes: number;
  elapsed_ms: number;
  detection_count: number;
  max_confidence: number;
  created_at: string;
  image_key: string | null;
}

export interface DetectionEvent extends DetectionEventSummary {
  detections: Detection[];
}

export interface DetectionEventListResponse {
  items: DetectionEventSummary[];
  total: number;
  skip: number;
  limit: number;
}

export interface ListDetectionsParams {
  camera_id?: string;
  model?: string;
  min_confidence?: number;
  date_from?: string;
  date_to?: string;
  skip?: number;
  limit?: number;
}

export async function listDetections(
  params: ListDetectionsParams = {},
): Promise<DetectionEventListResponse> {
  const { data } = await apiClient.get<DetectionEventListResponse>(
    "/detections",
    { params },
  );
  return data;
}

export async function getDetection(id: string): Promise<DetectionEvent> {
  const { data } = await apiClient.get<DetectionEvent>(`/detections/${id}`);
  return data;
}

export async function getDetectionImageBlob(id: string): Promise<Blob> {
  const { data } = await apiClient.get<Blob>(`/detections/${id}/image`, {
    responseType: "blob",
  });
  return data;
}

export async function exportDetectionsCsv(
  params: ListDetectionsParams & { max_rows?: number } = {},
): Promise<Blob> {
  const { data } = await apiClient.get<Blob>("/detections/export.csv", {
    params,
    responseType: "blob",
  });
  return data;
}

export interface DetectionSeriesPoint {
  date: string;
  events: number;
  detections: number;
}

export interface DetectionClassCount {
  class_name: string;
  count: number;
}

export interface DetectionCameraCount {
  camera_id: string;
  events: number;
  detections: number;
}

export interface DetectionStatsResponse {
  total_events: number;
  total_detections: number;
  avg_max_confidence: number;
  series: DetectionSeriesPoint[];
  top_classes: DetectionClassCount[];
  top_cameras: DetectionCameraCount[];
}

export interface DetectionStatsParams {
  camera_id?: string;
  date_from?: string;
  date_to?: string;
}

export async function getDetectionStats(
  params: DetectionStatsParams = {},
): Promise<DetectionStatsResponse> {
  const { data } = await apiClient.get<DetectionStatsResponse>(
    "/detections/stats",
    { params },
  );
  return data;
}
