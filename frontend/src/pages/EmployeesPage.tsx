import { useEffect, useState } from "react";
import {
  Button,
  Card,
  DatePicker,
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
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  StopOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";

import { listBranches, type Branch } from "@/api/tenancy";
import { listUsers, type ManagedUser } from "@/api/users";
import {
  createEmployee,
  deleteEmployee,
  type Employee,
  listEmployees,
  terminateEmployee,
  updateEmployee,
} from "@/api/employees";
import { useAuth } from "@/contexts/AuthContext";

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);
const PAGE_SIZE = 20;

interface FormValues {
  code: string;
  full_name: string;
  branch_id: string;
  position: string;
  user_id: string | null;
  hired_at: Dayjs | null;
  is_active: boolean;
}

export default function EmployeesPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<Employee[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [branchFilter, setBranchFilter] = useState<string | undefined>();
  const [activeOnly, setActiveOnly] = useState(false);
  const [loading, setLoading] = useState(false);

  const [branches, setBranches] = useState<Branch[]>([]);
  const [users, setUsers] = useState<ManagedUser[]>([]);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Employee | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const [terminateRow, setTerminateRow] = useState<Employee | null>(null);
  const [terminateDate, setTerminateDate] = useState<Dayjs | null>(dayjs());

  const load = async () => {
    setLoading(true);
    try {
      const res = await listEmployees({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
        branch_id: branchFilter,
        is_active: activeOnly ? true : undefined,
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được nhân viên");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    listBranches({ limit: 200 })
      .then((res) => setBranches(res.items))
      .catch(() => message.error("Không tải được chi nhánh"));
    listUsers({ limit: 500 })
      .then((res) => setUsers(res.items))
      .catch(() => message.error("Không tải được người dùng"));
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, branchFilter, activeOnly]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      is_active: true,
      user_id: null,
      hired_at: dayjs(),
    });
    setDrawerOpen(true);
  };

  const openEdit = (e: Employee) => {
    setEditing(e);
    form.setFieldsValue({
      code: e.code,
      full_name: e.full_name,
      branch_id: e.branch_id,
      position: e.position ?? "",
      user_id: e.user_id,
      hired_at: e.hired_at ? dayjs(e.hired_at) : null,
      is_active: e.is_active,
    });
    setDrawerOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    setSaving(true);
    try {
      const position = values.position?.trim() || null;
      const hired = values.hired_at ? values.hired_at.format("YYYY-MM-DD") : null;
      if (editing) {
        await updateEmployee(editing.id, {
          code: values.code,
          full_name: values.full_name,
          branch_id: values.branch_id,
          position,
          position_unset: !position,
          user_id: values.user_id,
          user_unset: values.user_id === null,
          hired_at: hired,
          hired_at_unset: !hired,
          is_active: values.is_active,
        });
        message.success("Đã cập nhật nhân viên");
      } else {
        await createEmployee({
          code: values.code,
          full_name: values.full_name,
          branch_id: values.branch_id,
          position,
          user_id: values.user_id,
          hired_at: hired,
          is_active: values.is_active,
        });
        message.success("Đã tạo nhân viên");
      }
      setDrawerOpen(false);
      load();
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: unknown } } })?.response
        ?.data?.detail;
      message.error(typeof d === "string" ? d : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteEmployee(id);
      message.success("Đã xóa nhân viên");
      load();
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const submitTerminate = async () => {
    if (!terminateRow || !terminateDate) return;
    try {
      await terminateEmployee(
        terminateRow.id,
        terminateDate.format("YYYY-MM-DD"),
      );
      message.success("Đã đánh dấu nghỉ việc");
      setTerminateRow(null);
      load();
    } catch {
      message.error("Cập nhật thất bại");
    }
  };

  const columns: ColumnsType<Employee> = [
    { title: "Mã", dataIndex: "code", width: 120 },
    { title: "Họ tên", dataIndex: "full_name" },
    { title: "Vị trí", dataIndex: "position", render: (v) => v ?? "—" },
    {
      title: "Chi nhánh",
      dataIndex: "branch_name",
      width: 180,
      render: (v: string | null) => v ?? "—",
    },
    {
      title: "Tài khoản",
      dataIndex: "user",
      width: 200,
      render: (u: Employee["user"]) => (u ? u.email : <Tag>Chưa liên kết</Tag>),
    },
    {
      title: "Ngày vào",
      dataIndex: "hired_at",
      width: 110,
      render: (v: string | null) => v ?? "—",
    },
    {
      title: "Nghỉ",
      dataIndex: "terminated_at",
      width: 110,
      render: (v: string | null) => v ?? "—",
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
      width: 170,
      fixed: "right",
      render: (_, row) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            disabled={!canEdit}
            onClick={() => openEdit(row)}
          />
          <Button
            size="small"
            icon={<StopOutlined />}
            disabled={!canEdit || !!row.terminated_at}
            onClick={() => {
              setTerminateRow(row);
              setTerminateDate(dayjs());
            }}
          />
          <Popconfirm
            title="Xóa nhân viên này?"
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
      title="Nhân viên"
      extra={
        <Space>
          <Input.Search
            placeholder="Tìm mã/tên/vị trí"
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
              Thêm nhân viên
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
        scroll={{ x: 1200 }}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          onChange: setPage,
          showSizeChanger: false,
        }}
      />

      <Drawer
        title={editing ? "Sửa nhân viên" : "Thêm nhân viên"}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={480}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item
            label="Mã nhân viên"
            name="code"
            rules={[{ required: true, message: "Bắt buộc" }]}
          >
            <Input maxLength={40} />
          </Form.Item>
          <Form.Item
            label="Họ tên"
            name="full_name"
            rules={[{ required: true, message: "Bắt buộc" }]}
          >
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item
            label="Chi nhánh"
            name="branch_id"
            rules={[{ required: true, message: "Bắt buộc" }]}
          >
            <Select
              placeholder="Chọn chi nhánh"
              options={branches.map((b) => ({
                value: b.id,
                label: `${b.code} — ${b.name}`,
              }))}
            />
          </Form.Item>
          <Form.Item label="Vị trí" name="position">
            <Input maxLength={120} />
          </Form.Item>
          <Form.Item label="Liên kết tài khoản" name="user_id">
            <Select
              showSearch
              allowClear
              optionFilterProp="label"
              placeholder="Không liên kết"
              options={users.map((u) => ({
                value: u.id,
                label: `${u.email}${u.full_name ? ` (${u.full_name})` : ""}`,
              }))}
            />
          </Form.Item>
          <Form.Item label="Ngày vào làm" name="hired_at">
            <DatePicker style={{ width: "100%" }} format="YYYY-MM-DD" />
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
        title={`Đánh dấu nghỉ việc — ${terminateRow?.full_name ?? ""}`}
        open={!!terminateRow}
        onCancel={() => setTerminateRow(null)}
        onOk={submitTerminate}
        okText="Xác nhận"
        cancelText="Hủy"
      >
        <Form.Item label="Ngày nghỉ việc">
          <DatePicker
            style={{ width: "100%" }}
            format="YYYY-MM-DD"
            value={terminateDate}
            onChange={setTerminateDate}
          />
        </Form.Item>
      </Modal>
    </Card>
  );
}
