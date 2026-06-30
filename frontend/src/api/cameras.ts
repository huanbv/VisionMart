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
  location_unset?: boolean;
  resolution_unset?: boolean;
  fps_unset?: boolean;
  config_unset?: boolean;
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
