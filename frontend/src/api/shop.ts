import { apiClient } from "./client";
import type { CartStatus } from "./carts";

export interface PublicBillLine {
  product_name: string;
  sku: string;
  quantity: number;
  unit_price: string;
  subtotal: string;
}

export interface PublicBillResponse {
  status: CartStatus;
  lines: PublicBillLine[];
  total_amount: string;
  currency: string;
  checkout_requested_at: string | null;
  expires_at: string | null;
  order_code: string | null;
  paid_at: string | null;
}

export interface PublicConfirmResponse {
  order_code: string;
  total_amount: string;
  currency: string;
  paid_at: string | null;
}

// Public, unauthenticated — a customer opens these from their own phone
// after scanning the checkout QR. No Authorization header is sent (the
// shared apiClient only attaches one if a staff token happens to be
// present in this browser's localStorage, which is never the case here).
export async function getPublicBill(token: string): Promise<PublicBillResponse> {
  const { data } = await apiClient.get<PublicBillResponse>(`/shop/checkout/${token}`);
  return data;
}

export async function confirmPublicCheckout(
  token: string,
): Promise<PublicConfirmResponse> {
  const { data } = await apiClient.post<PublicConfirmResponse>(
    `/shop/checkout/${token}/confirm`,
    {},
  );
  return data;
}

export async function cancelPublicCheckout(
  token: string,
): Promise<PublicBillResponse> {
  const { data } = await apiClient.post<PublicBillResponse>(
    `/shop/checkout/${token}/cancel`,
    {},
  );
  return data;
}
