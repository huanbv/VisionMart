import { apiClient } from "./client";

export interface Role {
  id: string;
  code: string;
  name: string;
  description: string | null;
}

export async function listRoles(): Promise<Role[]> {
  const { data } = await apiClient.get<Role[]>("/roles");
  return data;
}
