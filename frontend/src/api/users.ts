import { apiClient } from "./client";

export interface ManagedUser {
  id: string;
  organization_id: string;
  email: string;
  username: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserListResponse {
  items: ManagedUser[];
  total: number;
  skip: number;
  limit: number;
}

export interface UserCreatePayload {
  email: string;
  username: string;
  password: string;
  full_name?: string | null;
  is_active?: boolean;
  role_codes?: string[];
}

export interface UserUpdatePayload {
  full_name?: string | null;
  is_active?: boolean;
  password?: string;
  role_codes?: string[];
}

export async function listUsers(params: {
  skip?: number;
  limit?: number;
  search?: string;
}): Promise<UserListResponse> {
  const { data } = await apiClient.get<UserListResponse>("/users", { params });
  return data;
}

export async function createUser(payload: UserCreatePayload): Promise<ManagedUser> {
  const { data } = await apiClient.post<ManagedUser>("/users", payload);
  return data;
}

export async function updateUser(
  id: string,
  payload: UserUpdatePayload,
): Promise<ManagedUser> {
  const { data } = await apiClient.patch<ManagedUser>(`/users/${id}`, payload);
  return data;
}

export async function deactivateUser(id: string): Promise<void> {
  await apiClient.delete(`/users/${id}`);
}
