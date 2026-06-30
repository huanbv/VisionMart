import { useEffect, useMemo, useState } from "react";
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

import {
  Category,
  CategoryPayload,
  createCategory,
  deleteCategory,
  listCategories,
  updateCategory,
} from "@/api/catalog";
import { useAuth } from "@/contexts/AuthContext";

interface FormValues {
  name: string;
  slug: string;
  parent_id: string | null;
  is_active: boolean;
}

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);

export default function CategoriesPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<Category[]>([]);
  const [loading, setLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const load = async () => {
    setLoading(true);
    try {
      const res = await listCategories();
      setData(res);
    } catch {
      message.error("Không tải được danh mục");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const nameById = useMemo(() => {
    const m = new Map<string, string>();
    data.forEach((c) => m.set(c.id, c.name));
    return m;
  }, [data]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true, parent_id: null });
    setDrawerOpen(true);
  };

  const openEdit = (c: Category) => {
    setEditing(c);
    form.setFieldsValue({
      name: c.name,
      slug: c.slug,
      parent_id: c.parent_id,
      is_active: c.is_active,
    });
    setDrawerOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    setSaving(true);
    try {
      if (editing) {
        await updateCategory(editing.id, {
          name: values.name,
          slug: values.slug,
          parent_id: values.parent_id ?? undefined,
          parent_unset: values.parent_id === null,
          is_active: values.is_active,
        });
        message.success("Đã cập nhật danh mục");
      } else {
        const payload: CategoryPayload = {
          name: values.name,
          slug: values.slug,
          parent_id: values.parent_id ?? undefined,
          is_active: values.is_active,
        };
        await createCategory(payload);
        message.success("Đã tạo danh mục");
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

  const onDelete = async (id: string) => {
    try {
      await deleteCategory(id);
      message.success("Đã xóa danh mục");
      load();
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const columns: ColumnsType<Category> = [
    { title: "Tên", dataIndex: "name" },
    { title: "Slug", dataIndex: "slug", width: 200 },
    {
      title: "Cha",
      dataIndex: "parent_id",
      width: 200,
      render: (v: string | null) => (v ? nameById.get(v) ?? v : "—"),
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
      width: 140,
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
            title="Xóa danh mục này?"
            onConfirm={() => onDelete(record.id)}
            disabled={!canEdit}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={!canEdit}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="Danh mục sản phẩm"
      extra={
        canEdit && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            Thêm danh mục
          </Button>
        )
      }
    >
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={false}
      />
      <Drawer
        title={editing ? "Sửa danh mục" : "Thêm danh mục"}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={460}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item
            label="Tên"
            name="name"
            rules={[{ required: true, max: 255 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label="Slug"
            name="slug"
            rules={[{ required: true, max: 120 }]}
          >
            <Input placeholder="vd: do-uong" />
          </Form.Item>
          <Form.Item label="Danh mục cha" name="parent_id">
            <Select
              allowClear
              placeholder="Không có"
              options={data
                .filter((c) => !editing || c.id !== editing.id)
                .map((c) => ({ value: c.id, label: c.name }))}
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
