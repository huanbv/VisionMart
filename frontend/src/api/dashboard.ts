import { apiClient } from "./client";

export interface SalesBucket {
  orders: number;
  revenue: string;
}

export interface CameraSummary {
  total: number;
  online: number;
  active: number;
}

export interface DashboardSummary {
  today: SalesBucket;
  last_7_days: SalesBucket;
  last_30_days: SalesBucket;
  customers_total: number;
  customers_new_7d: number;
  products_total: number;
  low_stock_count: number;
  cameras: CameraSummary;
  employees_active: number;
  branches_count: number;
}

export interface SalesTrendPoint {
  date: string;
  orders: number;
  revenue: string;
}

export interface SalesTrendResponse {
  days: number;
  points: SalesTrendPoint[];
}

export interface TopProduct {
  product_id: string;
  sku: string;
  name: string;
  quantity: number;
  revenue: string;
}

export interface TopProductsResponse {
  days: number;
  items: TopProduct[];
}

export interface LowStockItem {
  inventory_id: string;
  sku: string;
  product_name: string;
  branch_name: string;
  quantity: number;
  reserved_quantity: number;
  reorder_level: number;
}

export interface LowStockResponse {
  items: LowStockItem[];
}

export interface RecentOrder {
  id: string;
  code: string;
  branch_name: string;
  status: string;
  total_amount: string;
  created_at: string;
}

export interface RecentOrdersResponse {
  items: RecentOrder[];
}

export async function getDashboardSummary(
  branch_id?: string,
): Promise<DashboardSummary> {
  const { data } = await apiClient.get<DashboardSummary>("/dashboard/summary", {
    params: { branch_id },
  });
  return data;
}

export async function getSalesTrend(
  days: number,
  branch_id?: string,
): Promise<SalesTrendResponse> {
  const { data } = await apiClient.get<SalesTrendResponse>(
    "/dashboard/sales-trend",
    { params: { days, branch_id } },
  );
  return data;
}

export async function getTopProducts(
  days: number,
  limit: number,
  branch_id?: string,
): Promise<TopProductsResponse> {
  const { data } = await apiClient.get<TopProductsResponse>(
    "/dashboard/top-products",
    { params: { days, limit, branch_id } },
  );
  return data;
}

export async function getLowStockItems(
  limit: number,
  branch_id?: string,
): Promise<LowStockResponse> {
  const { data } = await apiClient.get<LowStockResponse>(
    "/dashboard/low-stock",
    { params: { limit, branch_id } },
  );
  return data;
}

export async function getRecentOrders(
  limit: number,
  branch_id?: string,
): Promise<RecentOrdersResponse> {
  const { data } = await apiClient.get<RecentOrdersResponse>(
    "/dashboard/recent-orders",
    { params: { limit, branch_id } },
  );
  return data;
}
