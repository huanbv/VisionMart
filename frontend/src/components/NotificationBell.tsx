import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Empty, List, Popover, Space, Tag, Tooltip, message } from "antd";
import { BellOutlined, CheckOutlined, DeleteOutlined, ReloadOutlined } from "@ant-design/icons";

import {
  type Notification,
  deleteNotification,
  getUnreadCount,
  listNotifications,
  markAllRead,
  markNotificationRead,
} from "@/api/notifications";

const POLL_INTERVAL_MS = 30_000;
const LIST_LIMIT = 10;

const PRIORITY_COLOR: Record<string, string> = {
  low: "default",
  normal: "blue",
  high: "orange",
  critical: "red",
};

export default function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);

  const loadCount = useCallback(async () => {
    try {
      setUnread(await getUnreadCount());
    } catch {
      // silent
    }
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listNotifications({ limit: LIST_LIMIT });
      setItems(res.items);
      setUnread(res.unread);
    } catch {
      message.error("Không tải được thông báo");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCount();
    const id = window.setInterval(loadCount, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [loadCount]);

  useEffect(() => {
    if (open) loadList();
  }, [open, loadList]);

  const onMarkRead = async (n: Notification) => {
    if (n.is_read) return;
    try {
      await markNotificationRead(n.id);
      setItems((prev) =>
        prev.map((it) =>
          it.id === n.id ? { ...it, is_read: true, status: "read" } : it,
        ),
      );
      setUnread((u) => Math.max(0, u - 1));
    } catch {
      message.error("Thao tác thất bại");
    }
  };

  const onMarkAll = async () => {
    try {
      const updated = await markAllRead();
      if (updated > 0) {
        setItems((prev) =>
          prev.map((it) => ({ ...it, is_read: true, status: "read" })),
        );
        setUnread(0);
        message.success(`Đã đánh dấu ${updated} thông báo`);
      }
    } catch {
      message.error("Thao tác thất bại");
    }
  };

  const onDelete = async (n: Notification) => {
    try {
      await deleteNotification(n.id);
      setItems((prev) => prev.filter((it) => it.id !== n.id));
      if (!n.is_read) setUnread((u) => Math.max(0, u - 1));
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const content = (
    <div style={{ width: 380, maxHeight: 480, overflowY: "auto" }}>
      <Space style={{ marginBottom: 8, justifyContent: "space-between", width: "100%" }}>
        <strong>Thông báo</strong>
        <Space size={4}>
          <Tooltip title="Tải lại">
            <Button size="small" icon={<ReloadOutlined />} onClick={loadList} />
          </Tooltip>
          <Button size="small" onClick={onMarkAll} disabled={unread === 0}>
            Đọc tất cả
          </Button>
        </Space>
      </Space>
      {items.length === 0 && !loading ? (
        <Empty description="Không có thông báo" />
      ) : (
        <List
          loading={loading}
          dataSource={items}
          renderItem={(n) => (
            <List.Item
              style={{
                background: n.is_read ? undefined : "#e6f4ff",
                padding: "8px 12px",
                cursor: "pointer",
              }}
              onClick={() => onMarkRead(n)}
              actions={[
                !n.is_read ? (
                  <Tooltip title="Đánh dấu đã đọc" key="r">
                    <Button
                      size="small"
                      type="text"
                      icon={<CheckOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        onMarkRead(n);
                      }}
                    />
                  </Tooltip>
                ) : null,
                <Tooltip title="Xóa" key="d">
                  <Button
                    size="small"
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(n);
                    }}
                  />
                </Tooltip>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={6}>
                    <span style={{ fontWeight: n.is_read ? 400 : 600 }}>
                      {n.title}
                    </span>
                    <Tag color={PRIORITY_COLOR[n.priority] ?? "default"}>
                      {n.priority}
                    </Tag>
                  </Space>
                }
                description={
                  <div>
                    {n.body ? (
                      <div style={{ fontSize: 12 }}>{n.body}</div>
                    ) : null}
                    <div style={{ fontSize: 11, color: "#999", marginTop: 2 }}>
                      {new Date(n.created_at).toLocaleString("vi-VN")}
                    </div>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  );

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomRight"
      content={content}
    >
      <Badge count={unread} size="small" overflowCount={99}>
        <Button shape="circle" icon={<BellOutlined />} />
      </Badge>
    </Popover>
  );
}
