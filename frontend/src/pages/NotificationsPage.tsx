import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  CheckOutlined,
  DeleteOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import {
  deleteNotification,
  listNotifications,
  markAllRead,
  markNotificationRead,
  type Notification,
  type NotificationPriority,
} from "@/api/notifications";

const PRIORITY_COLOR: Record<NotificationPriority, string> = {
  low: "default",
  normal: "blue",
  high: "orange",
  critical: "red",
};

const PRIORITY_LABEL: Record<NotificationPriority, string> = {
  low: "Thấp",
  normal: "Bình thường",
  high: "Cao",
  critical: "Khẩn cấp",
};

export default function NotificationsPage() {
  const [items, setItems] = useState<Notification[]>([]);
  const [total, setTotal] = useState(0);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listNotifications({
        skip: (page - 1) * pageSize,
        limit: pageSize,
        unread_only: unreadOnly,
      });
      setItems(data.items);
      setTotal(data.total);
      setUnread(data.unread);
    } catch (err) {
      console.error(err);
      message.error("Không tải được danh sách thông báo");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, unreadOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  const onMarkRead = async (id: string) => {
    try {
      await markNotificationRead(id);
      await load();
    } catch (err) {
      console.error(err);
      message.error("Không đánh dấu đã đọc được");
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteNotification(id);
      await load();
    } catch (err) {
      console.error(err);
      message.error("Không xóa được thông báo");
    }
  };

  const onMarkAllRead = async () => {
    try {
      const updated = await markAllRead();
      message.success(`Đã đánh dấu ${updated} thông báo`);
      await load();
    } catch (err) {
      console.error(err);
      message.error("Không đánh dấu tất cả được");
    }
  };

  const columns = useMemo<ColumnsType<Notification>>(
    () => [
      {
        title: "Thời gian",
        dataIndex: "created_at",
        width: 170,
        render: (v: string) => new Date(v).toLocaleString("vi-VN"),
      },
      {
        title: "Loại",
        dataIndex: "type",
        width: 160,
      },
      {
        title: "Tiêu đề",
        dataIndex: "title",
        render: (v: string, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text strong={!row.is_read}>{v}</Typography.Text>
            {row.body && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {row.body}
              </Typography.Text>
            )}
          </Space>
        ),
      },
      {
        title: "Mức",
        dataIndex: "priority",
        width: 110,
        render: (v: NotificationPriority) => (
          <Tag color={PRIORITY_COLOR[v]}>{PRIORITY_LABEL[v]}</Tag>
        ),
      },
      {
        title: "Trạng thái",
        dataIndex: "is_read",
        width: 110,
        render: (v: boolean) =>
          v ? <Tag>Đã đọc</Tag> : <Tag color="blue">Chưa đọc</Tag>,
      },
      {
        title: "Thao tác",
        width: 140,
        render: (_: unknown, row) => (
          <Space>
            {!row.is_read && (
              <Button
                size="small"
                icon={<CheckOutlined />}
                onClick={() => void onMarkRead(row.id)}
              >
                Đọc
              </Button>
            )}
            <Popconfirm
              title="Xóa thông báo này?"
              onConfirm={() => void onDelete(row.id)}
              okText="Xóa"
              cancelText="Hủy"
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [],
  );

  return (
    <Card
      title={`Thông báo (${unread} chưa đọc)`}
      extra={
        <Space>
          <span>Chỉ chưa đọc</span>
          <Switch
            checked={unreadOnly}
            onChange={(v) => {
              setPage(1);
              setUnreadOnly(v);
            }}
          />
          <Button
            icon={<CheckOutlined />}
            onClick={() => void onMarkAllRead()}
            disabled={unread === 0}
          >
            Đọc tất cả
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            Làm mới
          </Button>
        </Space>
      }
    >
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: [20, 50, 100],
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
    </Card>
  );
}
