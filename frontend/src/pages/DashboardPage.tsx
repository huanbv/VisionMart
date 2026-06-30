import { Card, Descriptions, Space, Tag, Typography } from "antd";

import { useAuth } from "@/contexts/AuthContext";

export default function DashboardPage() {
  const { user } = useAuth();
  return (
    <Card title="Tài khoản hiện tại" className="max-w-3xl">
      <Descriptions column={1} bordered size="small">
        <Descriptions.Item label="Email">{user?.email}</Descriptions.Item>
        <Descriptions.Item label="Username">{user?.username}</Descriptions.Item>
        <Descriptions.Item label="Họ tên">{user?.full_name ?? "—"}</Descriptions.Item>
        <Descriptions.Item label="Organization ID">{user?.organization_id}</Descriptions.Item>
        <Descriptions.Item label="Vai trò">
          <Space wrap>
            {user?.roles.length ? (
              user.roles.map((r) => <Tag color="blue" key={r}>{r}</Tag>)
            ) : (
              <Tag>none</Tag>
            )}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="Superuser">
          {user?.is_superuser ? <Tag color="gold">YES</Tag> : <Tag>no</Tag>}
        </Descriptions.Item>
        <Descriptions.Item label="Lần đăng nhập gần nhất">
          {user?.last_login_at ?? "—"}
        </Descriptions.Item>
      </Descriptions>
      <Typography.Paragraph type="secondary" className="!mt-6 !mb-0">
        Dùng menu bên trái để quản lý Tổ chức, Chi nhánh, Người dùng, Vai trò.
      </Typography.Paragraph>
    </Card>
  );
}

