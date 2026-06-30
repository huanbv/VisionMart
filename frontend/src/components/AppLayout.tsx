import { useMemo } from "react";
import { Avatar, Button, Layout, Menu, Space, Typography } from "antd";
import {
  ApartmentOutlined,
  BankOutlined,
  DashboardOutlined,
  LogoutOutlined,
  SafetyOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/contexts/AuthContext";

const { Header, Sider, Content } = Layout;

const MENU_ITEMS = [
  { key: "/", icon: <DashboardOutlined />, label: <Link to="/">Tổng quan</Link> },
  {
    key: "/organization",
    icon: <BankOutlined />,
    label: <Link to="/organization">Tổ chức</Link>,
  },
  {
    key: "/branches",
    icon: <ApartmentOutlined />,
    label: <Link to="/branches">Chi nhánh</Link>,
  },
  {
    key: "/users",
    icon: <TeamOutlined />,
    label: <Link to="/users">Người dùng</Link>,
  },
  {
    key: "/roles",
    icon: <SafetyOutlined />,
    label: <Link to="/roles">Vai trò</Link>,
  },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const selectedKey = useMemo(() => {
    const match = MENU_ITEMS.map((m) => m.key)
      .filter((k) => k === "/" ? location.pathname === "/" : location.pathname.startsWith(k))
      .sort((a, b) => b.length - a.length)[0];
    return match ?? "/";
  }, [location.pathname]);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <Layout className="min-h-screen">
      <Sider breakpoint="lg" collapsedWidth={64} theme="dark">
        <div className="h-16 flex items-center justify-center text-white font-semibold text-lg">
          VisionMart
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={MENU_ITEMS}
        />
      </Sider>
      <Layout>
        <Header className="!bg-white !px-6 flex items-center justify-end shadow-sm">
          <Space>
            <Avatar icon={<UserOutlined />} />
            <Typography.Text strong>{user?.email}</Typography.Text>
            <Button icon={<LogoutOutlined />} onClick={handleLogout}>
              Đăng xuất
            </Button>
          </Space>
        </Header>
        <Content className="p-6 bg-slate-50">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
