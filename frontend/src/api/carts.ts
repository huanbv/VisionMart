import { apiClient } from "./client";

export type CartStatus =
  | "active"
  | "abandoned"
  | "converted"
  | "pending_checkout";
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
  // AI's detection confidence for this pickup (1.0 for manually-added
  // lines). Every AI prediction is probabilistic — never treat as ground
  // truth without a way to review it.
  confidence: number;
  added_at: string;
  // true khi ai-engine đã crop cận cảnh lúc detect — gọi
  // GET /carts/{id}/lines/{line_id}/photo (JWT blob, như ảnh khách).
  has_photo?: boolean;
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
  overall_confidence: number;
  // true nếu ai-engine đã chụp được ảnh chủ giỏ hàng — gọi
  // GET /carts/{id}/customer-photo để lấy ảnh khi cần (không có sẵn URL
  // ngay trong response, tránh ký sẵn hàng loạt link không dùng tới).
  has_customer_photo: boolean;
  // true khi Tải ảnh / Chụp & Quét đã lưu still có nhãn sản phẩm —
  // GET /carts/{id}/scan-photo (JWT blob, như ảnh khách).
  has_scan_photo?: boolean;
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

export async function retagCartLine(
  cartId: string,
  lineId: string,
  productId: string,
): Promise<{ cart: Cart; added_to_training: boolean }> {
  const { data } = await apiClient.post<{ cart: Cart; added_to_training: boolean }>(
    `/carts/${cartId}/lines/${lineId}/sku`,
    { product_id: productId },
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

export interface CartCheckoutQrResponse {
  cart_id: string;
  checkout_token: string;
  confirm_url: string;
  qr_svg: string;
  expires_at: string | null;
}

/**
 * Ảnh chủ giỏ hàng dưới dạng blob URL — cùng khuôn với getProductImageUrl
 * (catalog.ts): đi qua backend thay vì gắn thẳng vào `<img src>` vì endpoint
 * có xác thực JWT, thẻ `<img>` không tự gửi kèm bearer token được.
 *
 * Người gọi phải `URL.revokeObjectURL` khi component unmount, nếu không
 * mỗi lần danh sách giỏ hàng làm mới sẽ giữ thêm một blob trong bộ nhớ.
 */
export async function getCartCustomerPhotoUrl(cartId: string): Promise<string> {
  const { data } = await apiClient.get(`/carts/${cartId}/customer-photo`, {
    responseType: "blob",
  });
  return URL.createObjectURL(data as Blob);
}

export async function getCartScanPhotoUrl(cartId: string): Promise<string> {
  const { data } = await apiClient.get(`/carts/${cartId}/scan-photo`, {
    responseType: "blob",
  });
  return URL.createObjectURL(data as Blob);
}

export async function getCartLinePhotoUrl(
  cartId: string,
  lineId: string,
): Promise<string> {
  const { data } = await apiClient.get(
    `/carts/${cartId}/lines/${lineId}/photo`,
    { responseType: "blob" },
  );
  return URL.createObjectURL(data as Blob);
}

export async function getCheckoutQr(cartId: string): Promise<CartCheckoutQrResponse> {
  const { data } = await apiClient.get<CartCheckoutQrResponse>(
    `/carts/${cartId}/checkout-qr`,
  );
  return data;
}

export async function confirmCheckoutStaff(
  cartId: string,
): Promise<CartCheckoutResponse> {
  const { data } = await apiClient.post<CartCheckoutResponse>(
    `/carts/${cartId}/confirm-checkout`,
    {},
  );
  return data;
}

export async function cancelCheckout(cartId: string): Promise<Cart> {
  const { data } = await apiClient.post<Cart>(
    `/carts/${cartId}/cancel-checkout`,
    {},
  );
  return data;
}

export async function bulkAbandonCarts(cartIds?: string[], branchId?: string): Promise<{ status: string; abandoned: number }> {
  const { data } = await apiClient.post<{ status: string; abandoned: number }>(
    "/carts/bulk-abandon",
    { cart_ids: cartIds || [], branch_id: branchId },
  );
  return data;
}
