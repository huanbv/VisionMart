import { apiClient } from "./client";

export interface AuditLog {
  id: string;
  organization_id: string | null;
  user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  old_values: Record<string, unknown> | null;
  new_values: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLog[];
  total: number;
  skip: number;
  limit: number;
}

export interface ListAuditLogsParams {
  action?: string;
  resource_type?: string;
  resource_id?: string;
  user_id?: string;
  date_from?: string;
  date_to?: string;
  skip?: number;
  limit?: number;
}

export async function listAuditLogs(
  params: ListAuditLogsParams = {},
): Promise<AuditLogListResponse> {
  const { data } = await apiClient.get<AuditLogListResponse>("/audit-logs", {
    params,
  });
  return data;
}

export async function exportAuditLogsCsv(
  params: Omit<ListAuditLogsParams, "skip" | "limit"> & { max_rows?: number } = {},
): Promise<Blob> {
  const { data } = await apiClient.get<Blob>("/audit-logs/export.csv", {
    params,
    responseType: "blob",
  });
  return data;
}
