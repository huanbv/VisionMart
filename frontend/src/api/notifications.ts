import { apiClient } from "./client";

export type NotificationChannel = "in_app" | "email" | "sms" | "webhook" | "push";
export type NotificationPriority = "low" | "normal" | "high" | "critical";
export type NotificationStatus = "pending" | "sent" | "failed" | "read";

export interface Notification {
  id: string;
  organization_id: string;
  recipient_user_id: string | null;
  recipient_role_id: string | null;
  channel: NotificationChannel;
  type: string;
  title: string;
  body: string | null;
  payload: Record<string, unknown> | null;
  priority: NotificationPriority;
  status: NotificationStatus;
  sent_at: string | null;
  read_at: string | null;
  is_read: boolean;
  created_at: string;
  updated_at: string;
}

export interface NotificationListResponse {
  items: Notification[];
  total: number;
  skip: number;
  limit: number;
  unread: number;
}

export interface UnreadCountResponse {
  unread: number;
}

export interface NotificationCreatePayload {
  type: string;
  title: string;
  body?: string | null;
  recipient_user_id?: string | null;
  recipient_role_id?: string | null;
  channel?: NotificationChannel;
  priority?: NotificationPriority;
  payload?: Record<string, unknown> | null;
}

export async function listNotifications(params: {
  skip?: number;
  limit?: number;
  unread_only?: boolean;
}): Promise<NotificationListResponse> {
  const { data } = await apiClient.get<NotificationListResponse>(
    "/notifications",
    { params },
  );
  return data;
}

export async function getUnreadCount(): Promise<number> {
  const { data } = await apiClient.get<UnreadCountResponse>(
    "/notifications/unread-count",
  );
  return data.unread;
}

export async function markNotificationRead(id: string): Promise<Notification> {
  const { data } = await apiClient.post<Notification>(
    `/notifications/${id}/read`,
  );
  return data;
}

export async function markAllRead(): Promise<number> {
  const { data } = await apiClient.post<{ updated: number }>(
    "/notifications/read-all",
  );
  return data.updated;
}

export async function deleteNotification(id: string): Promise<void> {
  await apiClient.delete(`/notifications/${id}`);
}

export async function createNotification(
  payload: NotificationCreatePayload,
): Promise<Notification> {
  const { data } = await apiClient.post<Notification>(
    "/notifications",
    payload,
  );
  return data;
}
