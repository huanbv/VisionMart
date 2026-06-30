import { apiClient } from "./client";

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in: number;
}

export interface CurrentUser {
  id: string;
  organization_id: string;
  email: string;
  username: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
  last_login_at: string | null;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/login", {
    email,
    password,
  });
  return data;
}

export async function refresh(refreshToken: string): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>("/auth/refresh", {
    refresh_token: refreshToken,
  });
  return data;
}

export async function logout(refreshToken: string): Promise<void> {
  await apiClient.post("/auth/logout", { refresh_token: refreshToken });
}

export async function me(): Promise<CurrentUser> {
  const { data } = await apiClient.get<CurrentUser>("/auth/me");
  return data;
}
