import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import {
  BarChartOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { listBranches, type Branch } from "@/api/tenancy";
import {
  createCustomer,
  type Customer,
  type CustomerStats,
  deleteCustomer,
  getCustomerStats,
  listCustomers,
  updateCustomer,
} from "@/api/customers";
import { useAuth } from "@/contexts/AuthContext";

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);
const PAGE_SIZE = 20;

interface FormValues {
  full_name: string;
  email: string;
  phone: string;
  branch_id: string | null;
  is_active: boolean;
}

export default function CustomersPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<Customer[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [branchFilter, setBranchFilter] = useState<string | undefined>();
  const [activeOnly, setActiveOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [branches, setBranches] = useState<Branch[]>([]);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const [statsRow, setStatsRow] = useState<Customer | null>(null);
  const [stats, setStats] = useState<CustomerStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await listCustomers({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
        branch_id: branchFilter,
        is_active: activeOnly ? true : undefined,
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được khách hàng");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    listBranches({ limit: 200 })
      .then((res) => setBranches(res.items))
      .catch(() => message.error("Không tải được chi nhánh"));
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, branchFilter, activeOnly]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true, branch_id: null });
    setDrawerOpen(true);
  };

  const openEdit = (c: Customer) => {
    setEditing(c);
    form.setFieldsValue({
      full_name: c.full_name ?? "",
      email: c.email ?? "",
      phone: c.phone ?? "",
      branch_id: c.branch_id,
      is_active: c.is_active,
    });
    setDrawerOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    setSaving(true);
    try {
      const fullName = values.full_name?.trim() || null;
      const email = values.email?.trim() || null;
      const phone = values.phone?.trim() || null;
      if (editing) {
        await updateCustomer(editing.id, {
          full_name: fullName,
          full_name_unset: !fullName,
          email,
          email_unset: !email,
          phone,
          phone_unset: !phone,
          branch_id: values.branch_id,
          branch_unset: values.branch_id === null,
          is_active: values.is_active,
        });
        message.success("Đã cập nhật khách hàng");
      } else {
        await createCustomer({
          full_name: fullName,
          email,
          phone,
          branch_id: values.branch_id,
          is_active: values.is_active,
        });
        message.success("Đã tạo khách hàng");
      }
      setDrawerOpen(false);
      load();
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      message.error(typeof d === "string" ? d : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteCustomer(id);
      message.success("Đã xóa khách hàng");
      load();
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const openStats = async (row: Customer) => {
    setStatsRow(row);
    setStats(null);
    setStatsLoading(true);
    try {
      const s = await getCustomerStats(row.id);
      setStats(s);
    } catch {
      message.error("Không tải được thống kê");
    } finally {
      setStatsLoading(false);
    }
  };

  const branchName = (id: string | null) =>
    id ? branches.find((b) => b.id === id)?.name ?? id : "—";

  const columns: ColumnsType<Customer> = [
    { title: "Họ tên", dataIndex: "full_name", render: (v) => v ?? "—" },
    { title: "Email", dataIndex: "email", render: (v) => v ?? "—" },
    { title: "SĐT", dataIndex: "phone", width: 140, render: (v) => v ?? "—" },
    {
      title: "Chi nhánh",
      dataIndex: "branch_id",
      width: 180,
      render: (v: string | null) => branchName(v),
    },
    {
      title: "Trạng thái",
      dataIndex: "is_active",
      width: 110,
      render: (v: boolean) =>
        v ? <Tag color="green">Active</Tag> : <Tag>Inactive</Tag>,
    },
    {
      title: "Hành động",
      width: 160,
      fixed: "right",
      render: (_, row) => (
        <Space>
          <Button
            size="small"
            icon={<BarChartOutlined />}
            onClick={() => openStats(row)}
          />
          <Button
            size="small"
            icon={<EditOutlined />}
            disabled={!canEdit}
            onClick={() => openEdit(row)}
          />
          <Popconfirm
            title="Xóa khách hàng này?"
            onConfirm={() => onDelete(row.id)}
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
      title="Khách hàng"
      extra={
        <Space>
          <Input.Search
            placeholder="Tìm tên/email/SĐT"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setSearch(v);
            }}
            style={{ width: 240 }}
          />
          <Select
            allowClear
            placeholder="Chi nhánh"
            style={{ width: 200 }}
            value={branchFilter}
            onChange={(v) => {
              setPage(1);
              setBranchFilter(v);
            }}
            options={branches.map((b) => ({
              value: b.id,
              label: `${b.code} — ${b.name}`,
            }))}
          />
          <Space size={4}>
            <Switch
              checked={activeOnly}
              onChange={(v) => {
                setPage(1);
                setActiveOnly(v);
              }}
            />
            <span>Chỉ Active</span>
          </Space>
          {canEdit && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              Thêm khách
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
        title={editing ? "Sửa khách hàng" : "Thêm khách hàng"}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={460}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item label="Họ tên" name="full_name">
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item label="Email" name="email">
            <Input maxLength={320} />
          </Form.Item>
          <Form.Item label="Số điện thoại" name="phone">
            <Input maxLength={40} />
          </Form.Item>
          <Form.Item label="Chi nhánh" name="branch_id">
            <Select
              allowClear
              placeholder="Không gán"
              options={branches.map((b) => ({
                value: b.id,
                label: `${b.code} — ${b.name}`,
              }))}
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

      <Modal
        title="Thống kê khách hàng"
        open={!!statsRow}
        footer={null}
        onCancel={() => setStatsRow(null)}
      >
        {statsLoading ? (
          "Đang tải..."
        ) : stats ? (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Khách">
              {statsRow?.full_name ?? statsRow?.phone ?? statsRow?.email ?? "—"}
            </Descriptions.Item>
            <Descriptions.Item label="Số đơn đã thanh toán">
              {stats.order_count}
            </Descriptions.Item>
            <Descriptions.Item label="Tổng chi tiêu">
              {Number(stats.total_spent).toLocaleString()} VND
            </Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>
    </Card>
  );
}
