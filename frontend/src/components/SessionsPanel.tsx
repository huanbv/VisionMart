import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Empty,
  List,
  Popconfirm,
  Space,
  Spin,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, ReloadOutlined } from "@ant-design/icons";

import {
  type AuthSession,
  listSessions,
  revokeSession,
} from "@/api/auth";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("vi-VN");
}

export default function SessionsPanel() {
  const [sessions, setSessions] = useState<AuthSession[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSessions(await listSessions());
    } catch {
      message.error("Không tải được danh sách phiên");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRevoke = async (id: string) => {
    try {
      await revokeSession(id);
      message.success("Đã thu hồi phiên");
      await load();
    } catch {
      message.error("Không thu hồi được phiên");
    }
  };

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Space style={{ width: "100%", justifyContent: "space-between" }}>
        <Typography.Text strong>Phiên đang hoạt động</Typography.Text>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => void load()}
        >
          Làm mới
        </Button>
      </Space>
      {loading ? (
        <Spin />
      ) : sessions.length === 0 ? (
        <Empty description="Không có phiên nào" />
      ) : (
        <List
          size="small"
          bordered
          dataSource={sessions}
          renderItem={(s) => (
            <List.Item
              actions={[
                <Popconfirm
                  key="revoke"
                  title="Thu hồi phiên này?"
                  okText="Đồng ý"
                  cancelText="Hủy"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => void handleRevoke(s.id)}
                >
                  <Button size="small" danger icon={<DeleteOutlined />}>
                    Thu hồi
                  </Button>
                </Popconfirm>,
              ]}
            >
              <Space direction="vertical" size={0}>
                <Typography.Text>
                  {s.user_agent || "Thiết bị không xác định"}
                </Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  IP {s.ip_address ?? "—"} · đăng nhập {formatDate(s.issued_at)}{" "}
                  · hết hạn {formatDate(s.expires_at)}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      )}
    </Space>
  );
}
