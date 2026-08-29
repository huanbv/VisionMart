import { apiClient } from "./client";

export interface SalesByDayRow {
  day: string;
  orders: number;
  revenue: string;
}

export interface SalesByBranchRow {
  branch_id: string;
  branch_name: string;
  orders: number;
  revenue: string;
}

export interface TopProductRow {
  product_id: string;
  sku: string;
  name: string;
  quantity: number;
  revenue: string;
}

export interface InventoryValuationRow {
  sku: string;
  product_name: string;
  branch_name: string;
  quantity: number;
  unit_price: string;
  total_value: string;
}

export interface TopCustomerRow {
  customer_id: string;
  full_name: string | null;
  phone: string | null;
  orders: number;
  revenue: string;
}

export interface DateRangeParams {
  date_from: string;
  date_to: string;
}

export async function fetchSalesByDay(
  params: DateRangeParams & { branch_id?: string },
): Promise<SalesByDayRow[]> {
  const { data } = await apiClient.get("/reports/sales/by-day", { params });
  return data;
}

export async function fetchSalesByBranch(
  params: DateRangeParams,
): Promise<SalesByBranchRow[]> {
  const { data } = await apiClient.get("/reports/sales/by-branch", { params });
  return data;
}

export async function fetchTopProducts(
  params: DateRangeParams & { branch_id?: string; limit?: number },
): Promise<TopProductRow[]> {
  const { data } = await apiClient.get("/reports/sales/top-products", { params });
  return data;
}

export async function fetchInventoryValuation(
  params: { branch_id?: string },
): Promise<InventoryValuationRow[]> {
  const { data } = await apiClient.get("/reports/inventory/valuation", { params });
  return data;
}

export async function fetchTopCustomers(
  params: DateRangeParams & { limit?: number },
): Promise<TopCustomerRow[]> {
  const { data } = await apiClient.get("/reports/customers/top", { params });
  return data;
}

export async function downloadReportCsv(
  path: string,
  params: Record<string, string | number | undefined>,
  filename: string,
): Promise<void> {
  const resp = await apiClient.get(path, {
    params: { ...params, format: "csv" },
    responseType: "blob",
  });
  const url = URL.createObjectURL(resp.data as Blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
