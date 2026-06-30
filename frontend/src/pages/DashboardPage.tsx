import { Avatar, Button, Card, Descriptions, Layout, Space, Tag, Typography } from "antd";
import { LogoutOutlined, UserOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/contexts/AuthContext";

const { Header, Content } = Layout;

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <Layout className="min-h-screen">
      <Header className="!bg-slate-900 flex items-center justify-between px-6">
        <Typography.Title level={4} style={{ color: "white", margin: 0 }}>
          VisionMart
        </Typography.Title>
        <Space>
          <Avatar icon={<UserOutlined />} />
          <Typography.Text style={{ color: "white" }}>{user?.email}</Typography.Text>
          <Button icon={<LogoutOutlined />} onClick={handleLogout}>
            Đăng xuất
          </Button>
        </Space>
      </Header>
      <Content className="p-6 bg-slate-50">
        <Card title="Tài khoản hiện tại" className="max-w-3xl mx-auto">
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
            Module nghiệp vụ (Camera, Catalog, Sales, AI Events, …) sẽ được bổ sung ở
            các sprint tiếp theo. Đây là khung xác thực để các module sau gắn vào.
          </Typography.Paragraph>
        </Card>
      </Content>
    </Layout>
  );
}
