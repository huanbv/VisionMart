import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { listRoles, Role } from "@/api/roles";
import {
  createUser,
  deactivateUser,
  listUsers,
  ManagedUser,
  updateUser,
  UserCreatePayload,
} from "@/api/users";
import { useAuth } from "@/contexts/AuthContext";

interface FormValues {
  email: string;
  username: string;
  password?: string;
  full_name?: string;
  is_active: boolean;
  role_codes: string[];
}

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);
const PAGE_SIZE = 20;

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const canEdit = !!currentUser?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<ManagedUser[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [roles, setRoles] = useState<Role[]>([]);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<ManagedUser | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const load = async () => {
    setLoading(true);
    try {
      const res = await listUsers({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được danh sách người dùng");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    listRoles()
      .then(setRoles)
      .catch(() => message.error("Không tải được danh sách vai trò"));
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true, role_codes: [] });
    setDrawerOpen(true);
  };

  const openEdit = (u: ManagedUser) => {
    setEditing(u);
    form.setFieldsValue({
      email: u.email,
      username: u.username,
      full_name: u.full_name ?? "",
      is_active: u.is_active,
      role_codes: u.roles,
      password: "",
    });
    setDrawerOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    setSaving(true);
    try {
      if (editing) {
        await updateUser(editing.id, {
          full_name: values.full_name || null,
          is_active: values.is_active,
          password: values.password ? values.password : undefined,
          role_codes: values.role_codes,
        });
        message.success("Đã cập nhật người dùng");
      } else {
        const payload: UserCreatePayload = {
          email: values.email,
          username: values.username,
          password: values.password ?? "",
          full_name: values.full_name || null,
          is_active: values.is_active,
          role_codes: values.role_codes,
        };
        await createUser(payload);
        message.success("Đã tạo người dùng");
      }
      setDrawerOpen(false);
      load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      message.error(typeof detail === "string" ? detail : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const onDeactivate = async (id: string) => {
    try {
      await deactivateUser(id);
      message.success("Đã vô hiệu hóa người dùng");
      load();
    } catch {
      message.error("Vô hiệu hóa thất bại");
    }
  };

  const columns: ColumnsType<ManagedUser> = [
    { title: "Email", dataIndex: "email" },
    { title: "Username", dataIndex: "username", width: 140 },
    { title: "Họ tên", dataIndex: "full_name", render: (v) => v ?? "—" },
    {
      title: "Vai trò",
      dataIndex: "roles",
      render: (rs: string[]) => (
        <Space wrap>
          {rs.length ? rs.map((r) => <Tag key={r} color="blue">{r}</Tag>) : "—"}
        </Space>
      ),
    },
    {
      title: "Active",
      dataIndex: "is_active",
      width: 100,
      render: (v: boolean) =>
        v ? <Tag color="green">Active</Tag> : <Tag>Inactive</Tag>,
    },
    {
      title: "Hành động",
      width: 160,
      fixed: "right",
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            disabled={!canEdit}
            onClick={() => openEdit(record)}
          />
          <Popconfirm
            title="Vô hiệu hóa người dùng này?"
            onConfirm={() => onDeactivate(record.id)}
            disabled={!canEdit || record.id === currentUser?.id}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={!canEdit || record.id === currentUser?.id}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="Người dùng"
      extra={
        <Space>
          <Input.Search
            placeholder="Tìm theo email/username"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setSearch(v);
            }}
            style={{ width: 280 }}
          />
          {canEdit && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              Thêm người dùng
            </Button>
          )}
        </Space>
      }
    >
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          onChange: setPage,
          showSizeChanger: false,
        }}
      />
      <Drawer
        title={editing ? "Sửa người dùng" : "Thêm người dùng"}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={520}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item
            label="Email"
            name="email"
            rules={[{ required: true, max: 320 }]}
          >
            <Input disabled={!!editing} />
          </Form.Item>
          <Form.Item
            label="Username"
            name="username"
            rules={[{ required: true, min: 3, max: 120 }]}
          >
            <Input disabled={!!editing} />
          </Form.Item>
          <Form.Item label="Họ tên" name="full_name" rules={[{ max: 255 }]}>
            <Input />
          </Form.Item>
          <Form.Item
            label={editing ? "Mật khẩu mới (để trống nếu giữ nguyên)" : "Mật khẩu"}
            name="password"
            rules={
              editing
                ? [{ min: 8, max: 255 }]
                : [{ required: true, min: 8, max: 255 }]
            }
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item label="Vai trò" name="role_codes">
            <Select
              mode="multiple"
              options={roles.map((r) => ({ value: r.code, label: r.name }))}
              placeholder="Chọn vai trò"
            />
          </Form.Item>
          <Form.Item label="Active" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>
            {editing ? "Cập nhật" : "Tạo mới"}
          </Button>
        </Form>
      </Drawer>
    </Card>
  );
}
