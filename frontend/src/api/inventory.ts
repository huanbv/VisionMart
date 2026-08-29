import { apiClient } from "./client";

export type MovementType =
  | "in"
  | "out"
  | "adjust"
  | "transfer_in"
  | "transfer_out";

export interface InventoryRow {
  id: string;
  product_id: string;
  product_sku: string;
  product_name: string;
  branch_id: string;
  branch_name: string;
  quantity: number;
  reserved_quantity: number;
  available_quantity: number;
  reorder_level: number;
  low_stock: boolean;
  last_stock_check_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryListResponse {
  items: InventoryRow[];
  total: number;
  skip: number;
  limit: number;
}

export interface AdjustPayload {
  product_id: string;
  branch_id: string;
  delta: number;
  movement_type: MovementType;
  reason?: string | null;
  reference?: string | null;
}

export interface TransferPayload {
  product_id: string;
  from_branch_id: string;
  to_branch_id: string;
  quantity: number;
  reason?: string | null;
  reference?: string | null;
}

export interface StockMovement {
  id: string;
  product_id: string;
  branch_id: string;
  movement_type: MovementType;
  delta: number;
  quantity_after: number;
  reason: string | null;
  reference: string | null;
  performed_by: string | null;
  created_at: string;
}

export interface StockMovementListResponse {
  items: StockMovement[];
  total: number;
  skip: number;
  limit: number;
}

export async function listInventory(params: {
  skip?: number;
  limit?: number;
  search?: string;
  branch_id?: string;
  low_stock?: boolean;
}): Promise<InventoryListResponse> {
  const { data } = await apiClient.get<InventoryListResponse>("/inventory", {
    params,
  });
  return data;
}

export async function adjustInventory(
  payload: AdjustPayload,
): Promise<InventoryRow> {
  const { data } = await apiClient.post<InventoryRow>(
    "/inventory/adjust",
    payload,
  );
  return data;
}

export async function transferInventory(
  payload: TransferPayload,
): Promise<InventoryRow[]> {
  const { data } = await apiClient.post<InventoryRow[]>(
    "/inventory/transfer",
    payload,
  );
  return data;
}

export async function updateReorderLevel(
  id: string,
  reorder_level: number,
): Promise<InventoryRow> {
  const { data } = await apiClient.patch<InventoryRow>(`/inventory/${id}`, {
    reorder_level,
  });
  return data;
}

export async function listMovements(
  inventoryId: string,
  params: { skip?: number; limit?: number },
): Promise<StockMovementListResponse> {
  const { data } = await apiClient.get<StockMovementListResponse>(
    `/inventory/${inventoryId}/movements`,
    { params },
  );
  return data;
}

export async function exportMovementsCsv(params: {
  branch_id?: string;
  product_id?: string;
  movement_type?: MovementType;
  date_from?: string;
  date_to?: string;
  max_rows?: number;
}): Promise<Blob> {
  const { data } = await apiClient.get<Blob>("/inventory/movements/export.csv", {
    params,
    responseType: "blob",
  });
  return data;
}
