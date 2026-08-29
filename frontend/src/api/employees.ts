import { apiClient } from "./client";

export interface EmployeeUserRef {
  id: string;
  email: string;
  full_name: string | null;
}

export interface Employee {
  id: string;
  organization_id: string;
  branch_id: string;
  branch_name: string | null;
  user_id: string | null;
  user: EmployeeUserRef | null;
  code: string;
  full_name: string;
  position: string | null;
  hired_at: string | null;
  terminated_at: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface EmployeeListResponse {
  items: Employee[];
  total: number;
  skip: number;
  limit: number;
}

export interface EmployeeCreatePayload {
  code: string;
  full_name: string;
  branch_id: string;
  position?: string | null;
  user_id?: string | null;
  hired_at?: string | null;
  is_active?: boolean;
}

export interface EmployeeUpdatePayload {
  code?: string;
  full_name?: string;
  branch_id?: string;
  position?: string | null;
  user_id?: string | null;
  hired_at?: string | null;
  is_active?: boolean;
  position_unset?: boolean;
  user_unset?: boolean;
  hired_at_unset?: boolean;
}

export async function listEmployees(params: {
  skip?: number;
  limit?: number;
  search?: string;
  branch_id?: string;
  position?: string;
  is_active?: boolean;
}): Promise<EmployeeListResponse> {
  const { data } = await apiClient.get<EmployeeListResponse>("/employees", {
    params,
  });
  return data;
}

export async function getEmployee(id: string): Promise<Employee> {
  const { data } = await apiClient.get<Employee>(`/employees/${id}`);
  return data;
}

export async function createEmployee(
  payload: EmployeeCreatePayload,
): Promise<Employee> {
  const { data } = await apiClient.post<Employee>("/employees", payload);
  return data;
}

export async function updateEmployee(
  id: string,
  payload: EmployeeUpdatePayload,
): Promise<Employee> {
  const { data } = await apiClient.patch<Employee>(`/employees/${id}`, payload);
  return data;
}

export async function terminateEmployee(
  id: string,
  terminated_at: string,
): Promise<Employee> {
  const { data } = await apiClient.post<Employee>(
    `/employees/${id}/terminate`,
    { terminated_at },
  );
  return data;
}

export async function deleteEmployee(id: string): Promise<void> {
  await apiClient.delete(`/employees/${id}`);
}
