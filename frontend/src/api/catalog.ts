import { apiClient } from "./client";

export interface Category {
  id: string;
  organization_id: string;
  parent_id: string | null;
  name: string;
  slug: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CategoryPayload {
  name: string;
  slug: string;
  parent_id?: string | null;
  is_active?: boolean;
}

export interface CategoryUpdatePayload extends Partial<CategoryPayload> {
  parent_unset?: boolean;
}

export interface Product {
  id: string;
  organization_id: string;
  category_id: string | null;
  sku: string;
  barcode: string | null;
  name: string;
  description: string | null;
  unit_price: string;
  currency: string;
  attributes: Record<string, unknown> | null;
  image_url: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductListResponse {
  items: Product[];
  total: number;
  skip: number;
  limit: number;
}

export interface ProductPayload {
  sku: string;
  name: string;
  category_id?: string | null;
  barcode?: string | null;
  description?: string | null;
  unit_price?: number | string;
  currency?: string;
  attributes?: Record<string, unknown> | null;
  image_url?: string | null;
  is_active?: boolean;
}

export interface ProductUpdatePayload extends Partial<ProductPayload> {
  category_unset?: boolean;
  barcode_unset?: boolean;
  description_unset?: boolean;
  attributes_unset?: boolean;
  image_url_unset?: boolean;
}

export async function listCategories(): Promise<Category[]> {
  const { data } = await apiClient.get<Category[]>("/categories");
  return data;
}

export async function createCategory(payload: CategoryPayload): Promise<Category> {
  const { data } = await apiClient.post<Category>("/categories", payload);
  return data;
}

export async function updateCategory(
  id: string,
  payload: CategoryUpdatePayload,
): Promise<Category> {
  const { data } = await apiClient.patch<Category>(`/categories/${id}`, payload);
  return data;
}

export async function deleteCategory(id: string): Promise<void> {
  await apiClient.delete(`/categories/${id}`);
}

export async function listProducts(params: {
  skip?: number;
  limit?: number;
  search?: string;
  category_id?: string;
  is_active?: boolean;
}): Promise<ProductListResponse> {
  const { data } = await apiClient.get<ProductListResponse>("/products", { params });
  return data;
}

export async function createProduct(payload: ProductPayload): Promise<Product> {
  const { data } = await apiClient.post<Product>("/products", payload);
  return data;
}

export async function updateProduct(
  id: string,
  payload: ProductUpdatePayload,
): Promise<Product> {
  const { data } = await apiClient.patch<Product>(`/products/${id}`, payload);
  return data;
}

export async function deleteProduct(id: string): Promise<void> {
  await apiClient.delete(`/products/${id}`);
}

/**
 * Tải ảnh sản phẩm lên MinIO của hệ thống.
 *
 * Có endpoint này thì không còn phải tự host ảnh ở đâu đó rồi dán URL —
 * vốn vừa phiền vừa tạo phụ thuộc vào một nơi lưu trữ ngoài tầm kiểm
 * soát (link chết thì sản phẩm mất ảnh, không có cách nào biết trước).
 *
 * Trường `image_url` vẫn nhận URL ngoài như cũ, nên cách dán link không
 * bị bỏ; đây là thêm một lựa chọn.
 */
export async function uploadProductImage(
  productId: string,
  file: File,
): Promise<Product> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await apiClient.post<Product>(
    `/products/${productId}/image`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

/**
 * Ảnh sản phẩm dưới dạng blob URL.
 *
 * Đi qua backend chứ không gắn thẳng `image_url` vào `<img src>`: khoá
 * lưu trong MinIO không phải URL công khai, và thẻ `<img>` không gửi kèm
 * bearer token nên endpoint có xác thực sẽ trả 401. Đây cũng là khuôn
 * mà AiReviewPage đang dùng.
 *
 * Người gọi phải `URL.revokeObjectURL` khi không dùng nữa, nếu không mỗi
 * lần render lại sẽ giữ thêm một blob trong bộ nhớ.
 */
export async function getProductImageUrl(productId: string): Promise<string> {
  const { data } = await apiClient.get(`/products/${productId}/image`, {
    responseType: "blob",
  });
  return URL.createObjectURL(data as Blob);
}

/**
 * Lấy TẤT CẢ sản phẩm, tự động phân trang.
 *
 * Backend chặn `limit` ở 200 (`Query(le=200)`), nên gọi thẳng với số lớn
 * hơn sẽ nhận 422 chứ không phải danh sách bị cắt bớt — nghĩa là hỏng
 * toàn bộ, không phải hỏng một phần. Hàm này lặp qua từng trang để người
 * gọi không phải nhớ trần đó.
 *
 * Dùng cho các ô chọn cần đủ danh mục (ví dụ duyệt nhãn AI): thiếu một
 * sản phẩm ở đây không phải bất tiện nhỏ mà là KHÔNG THỂ gán đúng nhãn
 * cho sản phẩm đó, và nhãn sai còn tệ hơn không có nhãn.
 *
 * `maxItems` là chốt chặn để một danh mục lớn bất thường không kéo hàng
 * chục nghìn dòng vào một ô select vốn không dùng nổi ở kích thước đó.
 */
export async function listAllProducts(
  params: { is_active?: boolean; maxItems?: number } = {},
): Promise<Product[]> {
  const pageSize = 200; // trần của backend
  const maxItems = params.maxItems ?? 2000;
  const out: Product[] = [];
  let skip = 0;
  for (;;) {
    const page = await listProducts({
      skip,
      limit: pageSize,
      is_active: params.is_active,
    });
    out.push(...page.items);
    skip += pageSize;
    if (out.length >= page.total || page.items.length < pageSize) break;
    if (out.length >= maxItems) {
      console.warn(
        `listAllProducts: dừng ở ${maxItems} sản phẩm (tổng ${page.total}).`,
      );
      break;
    }
  }
  return out;
}
