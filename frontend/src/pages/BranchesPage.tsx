import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import {
  Branch,
  BranchPayload,
  createBranch,
  deleteBranch,
  listBranches,
  updateBranch,
} from "@/api/tenancy";
import { useAuth } from "@/contexts/AuthContext";

interface FormValues {
  name: string;
  code: string;
  timezone: string;
  is_active: boolean;
  address_json?: string;
}

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);
const PAGE_SIZE = 20;

export default function BranchesPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<Branch[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Branch | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const load = async () => {
    setLoading(true);
    try {
      const res = await listBranches({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được danh sách chi nhánh");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ timezone: "UTC", is_active: true, address_json: "" });
    setDrawerOpen(true);
  };

  const openEdit = (b: Branch) => {
    setEditing(b);
    form.setFieldsValue({
      name: b.name,
      code: b.code,
      timezone: b.timezone,
      is_active: b.is_active,
      address_json: JSON.stringify(b.address ?? {}, null, 2),
    });
    setDrawerOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    let address: Record<string, unknown> | null = null;
    if (values.address_json && values.address_json.trim()) {
      try {
        address = JSON.parse(values.address_json);
      } catch {
        message.error("Address JSON không hợp lệ");
        return;
      }
    }
    const payload: BranchPayload = {
      name: values.name,
      code: values.code,
      timezone: values.timezone,
      is_active: values.is_active,
      address,
    };
    setSaving(true);
    try {
      if (editing) {
        await updateBranch(editing.id, payload);
        message.success("Đã cập nhật chi nhánh");
      } else {
        await createBranch(payload);
        message.success("Đã tạo chi nhánh");
      }
      setDrawerOpen(false);
      load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Lưu thất bại";
      message.error(typeof detail === "string" ? detail : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteBranch(id);
      message.success("Đã xóa chi nhánh");
      load();
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const columns: ColumnsType<Branch> = [
    { title: "Mã", dataIndex: "code", width: 120 },
    { title: "Tên", dataIndex: "name" },
    { title: "Timezone", dataIndex: "timezone", width: 140 },
    {
      title: "Trạng thái",
      dataIndex: "is_active",
      width: 120,
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
            title="Xóa chi nhánh này?"
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
      title="Chi nhánh"
      extra={
        <Space>
          <Input.Search
            placeholder="Tìm theo tên/mã"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setSearch(v);
            }}
            style={{ width: 260 }}
          />
          {canEdit && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              Thêm chi nhánh
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
        title={editing ? "Sửa chi nhánh" : "Thêm chi nhánh"}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={480}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item
            label="Mã chi nhánh"
            name="code"
            rules={[{ required: true, max: 40 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label="Tên"
            name="name"
            rules={[{ required: true, max: 255 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label="Timezone"
            name="timezone"
            rules={[{ required: true, max: 64 }]}
          >
            <Input placeholder="UTC, Asia/Ho_Chi_Minh, …" />
          </Form.Item>
          <Form.Item
            label="Address (JSON)"
            name="address_json"
            tooltip='Ví dụ: {"line1":"123 Lê Lợi","city":"HCM"}'
          >
            <Input.TextArea rows={4} className="font-mono" />
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
