import { useMemo, useState } from "react";
import { Avatar, Button, Layout, Menu, Popconfirm, Space, Typography, message } from "antd";
import {
  ApartmentOutlined,
  AppstoreOutlined,
  AuditOutlined,
  BankOutlined,
  BarChartOutlined,
  BellOutlined,
  ContactsOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  EyeOutlined,
  FileTextOutlined,
  KeyOutlined,
  LogoutOutlined,
  SafetyOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  TagsOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/contexts/AuthContext";
import ChangePasswordModal from "@/components/ChangePasswordModal";
import NotificationBell from "@/components/NotificationBell";
import ProfileModal from "@/components/ProfileModal";
import { logoutAll } from "@/api/auth";

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
    key: "catalog",
    icon: <AppstoreOutlined />,
    label: "Catalog",
    children: [
      {
        key: "/categories",
        icon: <TagsOutlined />,
        label: <Link to="/categories">Danh mục</Link>,
      },
      {
        key: "/products",
        icon: <ShoppingOutlined />,
        label: <Link to="/products">Sản phẩm</Link>,
      },
    ],
  },
  {
    key: "/inventory",
    icon: <DatabaseOutlined />,
    label: <Link to="/inventory">Tồn kho</Link>,
  },
  {
    key: "sales",
    icon: <ShoppingCartOutlined />,
    label: "Bán hàng",
    children: [
      {
        key: "/pos",
        icon: <ShoppingCartOutlined />,
        label: <Link to="/pos">Bán hàng (POS)</Link>,
      },
      {
        key: "/orders",
        icon: <FileTextOutlined />,
        label: <Link to="/orders">Đơn hàng</Link>,
      },
      {
        key: "/live-cart",
        icon: <ThunderboltOutlined />,
        label: <Link to="/live-cart">Giỏ hàng AI (Live)</Link>,
      },
    ],
  },
  {
    key: "/customers",
    icon: <ContactsOutlined />,
    label: <Link to="/customers">Khách hàng</Link>,
  },
  {
    key: "/employees",
    icon: <TeamOutlined />,
    label: <Link to="/employees">Nhân viên</Link>,
  },
  {
    key: "/cameras",
    icon: <VideoCameraOutlined />,
    label: <Link to="/cameras">Camera</Link>,
  },
  {
    key: "/detections",
    icon: <EyeOutlined />,
    label: <Link to="/detections">Phát hiện AI</Link>,
  },
  {
    key: "/ai-analytics",
    icon: <BarChartOutlined />,
    label: <Link to="/ai-analytics">Thống kê AI</Link>,
  },
  {
    key: "/ai-training",
    icon: <ExperimentOutlined />,
    label: <Link to="/ai-training">Train AI</Link>,
  },
  {
    key: "/notifications",
    icon: <BellOutlined />,
    label: <Link to="/notifications">Thông báo</Link>,
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
  {
    key: "/audit-logs",
    icon: <AuditOutlined />,
    label: <Link to="/audit-logs">Nhật ký</Link>,
  },
  {
    key: "/reports",
    icon: <BarChartOutlined />,
    label: <Link to="/reports">Báo cáo</Link>,
  },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const location = useLocation();

  const selectedKey = useMemo(() => {
    const keys: string[] = [];
    for (const item of MENU_ITEMS) {
      if (typeof item.key === "string" && item.key.startsWith("/")) keys.push(item.key);
      if ("children" in item && item.children) {
        for (const child of item.children) {
          if (typeof child.key === "string" && child.key.startsWith("/")) keys.push(child.key);
        }
      }
    }
    const match = keys
      .filter((k) => (k === "/" ? location.pathname === "/" : location.pathname.startsWith(k)))
      .sort((a, b) => b.length - a.length)[0];
    return match ?? "/";
  }, [location.pathname]);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const handleLogoutAll = async () => {
    try {
      await logoutAll();
      message.success("Đã đăng xuất khỏi mọi thiết bị");
    } catch {
      message.error("Không thể đăng xuất mọi thiết bị");
    }
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
            <NotificationBell />
            <Avatar icon={<UserOutlined />} />
            <Typography.Link
              strong
              onClick={() => setProfileModalOpen(true)}
            >
              {user?.full_name || user?.email}
            </Typography.Link>
            <Button
              icon={<KeyOutlined />}
              onClick={() => setPasswordModalOpen(true)}
            >
              Đổi mật khẩu
            </Button>
            <Popconfirm
              title="Đăng xuất mọi thiết bị?"
              description="Thu hồi tất cả phiên đăng nhập đang hoạt động, bao gồm thiết bị hiện tại."
              okText="Đồng ý"
              cancelText="Hủy"
              okButtonProps={{ danger: true }}
              onConfirm={handleLogoutAll}
            >
              <Button danger icon={<LogoutOutlined />}>
                Thiết bị khác
              </Button>
            </Popconfirm>
            <Button icon={<LogoutOutlined />} onClick={handleLogout}>
              Đăng xuất
            </Button>
          </Space>
        </Header>
        <Content className="p-6 bg-slate-50">
          <Outlet />
        </Content>
      </Layout>
      <ChangePasswordModal
        open={passwordModalOpen}
        onClose={() => setPasswordModalOpen(false)}
      />
      <ProfileModal
        open={profileModalOpen}
        onClose={() => setProfileModalOpen(false)}
      />
    </Layout>
  );
}
