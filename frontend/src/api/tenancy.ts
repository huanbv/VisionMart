import { apiClient } from "./client";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  settings: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface Branch {
  id: string;
  organization_id: string;
  name: string;
  code: string;
  address: Record<string, unknown> | null;
  timezone: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BranchListResponse {
  items: Branch[];
  total: number;
  skip: number;
  limit: number;
}

export interface BranchPayload {
  name: string;
  code: string;
  address?: Record<string, unknown> | null;
  timezone?: string;
  is_active?: boolean;
}

export async function getOrganization(): Promise<Organization> {
  const { data } = await apiClient.get<Organization>("/organization");
  return data;
}

export async function updateOrganization(
  patch: Partial<Pick<Organization, "name" | "settings">>,
): Promise<Organization> {
  const { data } = await apiClient.patch<Organization>("/organization", patch);
  return data;
}

export async function listBranches(params: {
  skip?: number;
  limit?: number;
  search?: string;
}): Promise<BranchListResponse> {
  const { data } = await apiClient.get<BranchListResponse>("/branches", { params });
  return data;
}

export async function createBranch(payload: BranchPayload): Promise<Branch> {
  const { data } = await apiClient.post<Branch>("/branches", payload);
  return data;
}

export async function updateBranch(
  id: string,
  payload: Partial<BranchPayload>,
): Promise<Branch> {
  const { data } = await apiClient.patch<Branch>(`/branches/${id}`, payload);
  return data;
}

export async function deleteBranch(id: string): Promise<void> {
  await apiClient.delete(`/branches/${id}`);
}
