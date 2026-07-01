import { apiClient } from "./client";

export type CartStatus = "active" | "abandoned" | "converted";
export type CartSource = "ai_vision" | "manual" | "mobile_app";

export interface CartLine {
  line_id: string;
  product_id: string;
  sku: string;
  product_name: string;
  quantity: number;
  unit_price: string;
  subtotal: string;
  added_via: string;
  source_event_id: string | null;
  added_at: string;
}

export interface Cart {
  id: string;
  organization_id: string;
  branch_id: string;
  customer_id: string | null;
  session_id: string | null;
  status: CartStatus;
  source: CartSource;
  total_amount: string;
  currency: string;
  lines: CartLine[];
  expires_at: string | null;
  converted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CartListResponse {
  items: Cart[];
  total: number;
  skip: number;
  limit: number;
}

export interface CartCheckoutResponse {
  cart_id: string;
  order_id: string;
  order_code: string;
  total_amount: string;
  currency: string;
}

export async function listCarts(params: {
  branch_id?: string;
  status?: CartStatus;
  skip?: number;
  limit?: number;
}): Promise<CartListResponse> {
  const { data } = await apiClient.get<CartListResponse>("/carts", { params });
  return data;
}

export async function getCart(cartId: string): Promise<Cart> {
  const { data } = await apiClient.get<Cart>(`/carts/${cartId}`);
  return data;
}

export async function createCart(payload: {
  branch_id: string;
  customer_id?: string | null;
  session_id?: string | null;
  source?: CartSource;
}): Promise<Cart> {
  const { data } = await apiClient.post<Cart>("/carts", payload);
  return data;
}

export async function addCartLine(
  cartId: string,
  payload: {
    product_id: string;
    quantity?: number;
    unit_price?: number | string | null;
    added_via?: string;
    source_event_id?: string | null;
  },
): Promise<Cart> {
  const { data } = await apiClient.post<Cart>(`/carts/${cartId}/lines`, payload);
  return data;
}

export async function removeCartLine(
  cartId: string,
  lineId: string,
): Promise<Cart> {
  const { data } = await apiClient.delete<Cart>(
    `/carts/${cartId}/lines/${lineId}`,
  );
  return data;
}

export async function checkoutCart(cartId: string): Promise<CartCheckoutResponse> {
  const { data } = await apiClient.post<CartCheckoutResponse>(
    `/carts/${cartId}/checkout`,
    {},
  );
  return data;
}

export async function abandonCart(cartId: string): Promise<Cart> {
  const { data } = await apiClient.post<Cart>(`/carts/${cartId}/abandon`, {});
  return data;
}
