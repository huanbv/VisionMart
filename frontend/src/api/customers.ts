import { apiClient } from "./client";

export interface Customer {
  id: string;
  organization_id: string;
  branch_id: string | null;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  face_embedding_ref: string | null;
  attributes: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CustomerListResponse {
  items: Customer[];
  total: number;
  skip: number;
  limit: number;
}

export interface CustomerPayload {
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  branch_id?: string | null;
  attributes?: Record<string, unknown> | null;
  is_active?: boolean;
}

export interface CustomerUpdatePayload extends CustomerPayload {
  full_name_unset?: boolean;
  email_unset?: boolean;
  phone_unset?: boolean;
  branch_unset?: boolean;
  attributes_unset?: boolean;
}

export interface CustomerStats {
  customer_id: string;
  order_count: number;
  total_spent: string;
}

export async function listCustomers(params: {
  skip?: number;
  limit?: number;
  search?: string;
  branch_id?: string;
  is_active?: boolean;
}): Promise<CustomerListResponse> {
  const { data } = await apiClient.get<CustomerListResponse>("/customers", {
    params,
  });
  return data;
}

export async function exportCustomersCsv(params: {
  search?: string;
  branch_id?: string;
  is_active?: boolean;
  max_rows?: number;
}): Promise<Blob> {
  const { data } = await apiClient.get<Blob>("/customers/export.csv", {
    params,
    responseType: "blob",
  });
  return data;
}

export async function getCustomer(id: string): Promise<Customer> {
  const { data } = await apiClient.get<Customer>(`/customers/${id}`);
  return data;
}

export async function getCustomerStats(id: string): Promise<CustomerStats> {
  const { data } = await apiClient.get<CustomerStats>(`/customers/${id}/stats`);
  return data;
}

export async function createCustomer(
  payload: CustomerPayload,
): Promise<Customer> {
  const { data } = await apiClient.post<Customer>("/customers", payload);
  return data;
}

export async function updateCustomer(
  id: string,
  payload: CustomerUpdatePayload,
): Promise<Customer> {
  const { data } = await apiClient.patch<Customer>(`/customers/${id}`, payload);
  return data;
}

export async function deleteCustomer(id: string): Promise<void> {
  await apiClient.delete(`/customers/${id}`);
}
