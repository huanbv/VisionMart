import { apiClient } from "./client";

export type OrderStatus = "pending" | "paid" | "cancelled" | "refunded";

export interface OrderLineCreate {
  product_id: string;
  quantity: number;
  unit_price?: number | string | null;
  discount_amount?: number | string;
}

export interface OrderCreatePayload {
  branch_id: string;
  customer_id?: string | null;
  notes?: string | null;
  lines: OrderLineCreate[];
}

export interface OrderItem {
  id: string;
  product_id: string;
  quantity: number;
  unit_price: string;
  discount_amount: string;
  subtotal: string;
}

export interface OrderSummary {
  id: string;
  code: string;
  branch_id: string;
  branch_name: string;
  customer_id: string | null;
  status: OrderStatus;
  total_amount: string;
  currency: string;
  paid_at: string | null;
  created_at: string;
}

export interface OrderListResponse {
  items: OrderSummary[];
  total: number;
  skip: number;
  limit: number;
}

export interface OrderDetail {
  id: string;
  code: string;
  organization_id: string;
  branch_id: string;
  customer_id: string | null;
  employee_id: string | null;
  cart_id: string | null;
  status: OrderStatus;
  total_amount: string;
  currency: string;
  paid_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
}

export async function listOrders(params: {
  skip?: number;
  limit?: number;
  branch_id?: string;
  status?: OrderStatus;
  date_from?: string;
  date_to?: string;
  search?: string;
}): Promise<OrderListResponse> {
  const { data } = await apiClient.get<OrderListResponse>("/orders", {
    params,
  });
  return data;
}

export async function exportOrdersCsv(params: {
  branch_id?: string;
  status?: OrderStatus;
  date_from?: string;
  date_to?: string;
  search?: string;
  max_rows?: number;
}): Promise<Blob> {
  const { data } = await apiClient.get<Blob>("/orders/export.csv", {
    params,
    responseType: "blob",
  });
  return data;
}

export async function getOrder(id: string): Promise<OrderDetail> {
  const { data } = await apiClient.get<OrderDetail>(`/orders/${id}`);
  return data;
}

export async function createOrder(
  payload: OrderCreatePayload,
): Promise<OrderDetail> {
  const { data } = await apiClient.post<OrderDetail>("/orders", payload);
  return data;
}

export async function cancelOrder(id: string): Promise<OrderDetail> {
  const { data } = await apiClient.post<OrderDetail>(`/orders/${id}/cancel`);
  return data;
}
