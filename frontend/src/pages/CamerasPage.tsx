import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Col,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { listBranches, type Branch } from "@/api/tenancy";
import {
  type AnalyzeResult,
  type Camera,
  type CameraStats,
  analyzeCameraFrame,
  createCamera,
  deleteCamera,
  getCameraStats,
  heartbeatCamera,
  listCameras,
  updateCamera,
} from "@/api/cameras";
import { useAuth } from "@/contexts/AuthContext";

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);
const PAGE_SIZE = 20;

interface FormValues {
  code: string;
  name: string;
  branch_id: string;
  stream_url: string;
  location: string;
  resolution: string;
  fps: number | null;
  is_active: boolean;
}

export default function CamerasPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<Camera[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [branchFilter, setBranchFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<
    "all" | "online" | "offline"
  >("all");
  const [loading, setLoading] = useState(false);

  const [branches, setBranches] = useState<Branch[]>([]);
  const [stats, setStats] = useState<CameraStats | null>(null);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Camera | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const load = async () => {
    setLoading(true);
    try {
      const res = await listCameras({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
        branch_id: branchFilter,
        is_online:
          statusFilter === "online"
            ? true
            : statusFilter === "offline"
              ? false
              : undefined,
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được camera");
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      setStats(await getCameraStats());
    } catch {
      // silent
    }
  };

  useEffect(() => {
    listBranches({ limit: 200 })
      .then((res) => setBranches(res.items))
      .catch(() => message.error("Không tải được chi nhánh"));
    loadStats();
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, branchFilter, statusFilter]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ is_active: true, fps: 25 });
    setDrawerOpen(true);
  };

  const openEdit = (c: Camera) => {
    setEditing(c);
    form.setFieldsValue({
      code: c.code,
      name: c.name,
      branch_id: c.branch_id,
      stream_url: c.stream_url,
      location: c.location ?? "",
      resolution: c.resolution ?? "",
      fps: c.fps,
      is_active: c.is_active,
    });
    setDrawerOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    setSaving(true);
    try {
      const location = values.location?.trim() || null;
      const resolution = values.resolution?.trim() || null;
      const fps = values.fps ?? null;
      if (editing) {
        await updateCamera(editing.id, {
          code: values.code,
          name: values.name,
          branch_id: values.branch_id,
          stream_url: values.stream_url,
          location,
          location_unset: !location,
          resolution,
          resolution_unset: !resolution,
          fps,
          fps_unset: fps === null,
          is_active: values.is_active,
        });
        message.success("Đã cập nhật camera");
      } else {
        await createCamera({
          code: values.code,
          name: values.name,
          branch_id: values.branch_id,
          stream_url: values.stream_url,
          location,
          resolution,
          fps,
          is_active: values.is_active,
        });
        message.success("Đã tạo camera");
      }
      setDrawerOpen(false);
      load();
      loadStats();
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
      await deleteCamera(id);
      message.success("Đã xóa camera");
      load();
      loadStats();
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const onPing = async (row: Camera) => {
    try {
      await heartbeatCamera(row.id, true);
      message.success(`Đã đánh dấu '${row.name}' online`);
      load();
      loadStats();
    } catch {
      message.error("Heartbeat thất bại");
    }
  };

  const [analyzeFor, setAnalyzeFor] = useState<Camera | null>(null);
  const [analyzeFile, setAnalyzeFile] = useState<File | null>(null);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const onAnalyze = async () => {
    if (!analyzeFor || !analyzeFile) return;
    setAnalyzing(true);
    setAnalyzeResult(null);
    try {
      const res = await analyzeCameraFrame(analyzeFor.id, analyzeFile);
      setAnalyzeResult(res);
    } catch {
      message.error("Phân tích thất bại");
    } finally {
      setAnalyzing(false);
    }
  };

  const closeAnalyze = () => {
    setAnalyzeFor(null);
    setAnalyzeFile(null);
    setAnalyzeResult(null);
  };

  const columns: ColumnsType<Camera> = [
    {
      title: "Trạng thái",
      dataIndex: "is_online",
      width: 110,
      render: (online: boolean, row) =>
        !row.is_active ? (
          <Tag>Disabled</Tag>
        ) : online ? (
          <Badge status="success" text="Online" />
        ) : (
          <Badge status="default" text="Offline" />
        ),
    },
    { title: "Mã", dataIndex: "code", width: 120 },
    { title: "Tên", dataIndex: "name" },
    {
      title: "Chi nhánh",
      dataIndex: "branch_name",
      width: 180,
      render: (v: string | null) => v ?? "—",
    },
    {
      title: "Vị trí",
      dataIndex: "location",
      width: 160,
      render: (v: string | null) => v ?? "—",
    },
    {
      title: "Stream",
      dataIndex: "stream_url",
      ellipsis: true,
      render: (v: string) => <code style={{ fontSize: 12 }}>{v}</code>,
    },
    {
      title: "FPS",
      dataIndex: "fps",
      width: 70,
      render: (v: number | null) => v ?? "—",
    },
    {
      title: "Lần cuối",
      dataIndex: "last_seen_at",
      width: 170,
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : "—"),
    },
    {
      title: "Hành động",
      width: 210,
      fixed: "right",
      render: (_, row) => (
        <Space>
          <Button
            size="small"
            icon={<WifiOutlined />}
            onClick={() => onPing(row)}
            title="Heartbeat (online)"
          />
          <Button
            size="small"
            icon={<ExperimentOutlined />}
            onClick={() => {
              setAnalyzeFor(row);
              setAnalyzeFile(null);
              setAnalyzeResult(null);
            }}
            title="Phân tích khung hình"
          />
          <Button
            size="small"
            icon={<EditOutlined />}
            disabled={!canEdit}
            onClick={() => openEdit(row)}
          />
          <Popconfirm
            title="Xóa camera này?"
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
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Row gutter={16}>
        <Col span={8}>
          <Card>
            <Statistic title="Tổng số camera" value={stats?.total ?? 0} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Đang online"
              value={stats?.online ?? 0}
              valueStyle={{ color: "#52c41a" }}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="Active" value={stats?.active ?? 0} />
          </Card>
        </Col>
      </Row>

      <Card
        title="Camera"
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
            <Select
              style={{ width: 140 }}
              value={statusFilter}
              onChange={(v) => {
                setPage(1);
                setStatusFilter(v);
              }}
              options={[
                { value: "all", label: "Tất cả" },
                { value: "online", label: "Online" },
                { value: "offline", label: "Offline" },
              ]}
            />
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                load();
                loadStats();
              }}
            />
            {canEdit && (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={openCreate}
              >
                Thêm camera
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
          scroll={{ x: 1400 }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            onChange: setPage,
            showSizeChanger: false,
          }}
        />
      </Card>

      <Drawer
        title={editing ? "Sửa camera" : "Thêm camera"}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={520}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item
            label="Mã"
            name="code"
            rules={[{ required: true, message: "Bắt buộc" }]}
          >
            <Input maxLength={40} />
          </Form.Item>
          <Form.Item
            label="Tên"
            name="name"
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
          <Form.Item
            label="Stream URL (RTSP / HLS / HTTP)"
            name="stream_url"
            rules={[{ required: true, message: "Bắt buộc" }]}
          >
            <Input maxLength={1024} placeholder="rtsp://user:pass@host/stream" />
          </Form.Item>
          <Form.Item label="Vị trí" name="location">
            <Input maxLength={255} placeholder="Quầy thu ngân, kệ A1..." />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="Độ phân giải" name="resolution">
                <Input maxLength={20} placeholder="1920x1080" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="FPS" name="fps">
                <InputNumber min={1} max={240} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="Active" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>
            {editing ? "Cập nhật" : "Tạo mới"}
          </Button>
        </Form>
      </Drawer>

      <Modal
        title={
          analyzeFor ? `Phân tích khung hình — ${analyzeFor.name}` : "Phân tích"
        }
        open={!!analyzeFor}
        onCancel={closeAnalyze}
        footer={[
          <Button key="close" onClick={closeAnalyze}>
            Đóng
          </Button>,
          <Button
            key="run"
            type="primary"
            disabled={!analyzeFile}
            loading={analyzing}
            onClick={onAnalyze}
          >
            Chạy phân tích
          </Button>,
        ]}
        width={640}
      >
        <Upload.Dragger
          multiple={false}
          accept="image/*"
          beforeUpload={(file) => {
            setAnalyzeFile(file as File);
            setAnalyzeResult(null);
            return false;
          }}
          onRemove={() => {
            setAnalyzeFile(null);
            setAnalyzeResult(null);
          }}
          fileList={
            analyzeFile
              ? [
                  {
                    uid: "1",
                    name: analyzeFile.name,
                    status: "done",
                  },
                ]
              : []
          }
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">Kéo thả hoặc bấm để chọn ảnh</p>
          <p className="ant-upload-hint">JPG/PNG, tối đa 10 MB</p>
        </Upload.Dragger>

        {analyzeResult && (
          <Card size="small" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: "100%" }}>
              <Typography.Text>
                Model: <Tag color="blue">{analyzeResult.model}</Tag>
                Kích thước: {analyzeResult.image.width}×{analyzeResult.image.height}{" "}
                ({analyzeResult.image.format}, {analyzeResult.image.size_bytes} B)
              </Typography.Text>
              <Typography.Text type="secondary">
                Thời gian xử lý: {analyzeResult.elapsed_ms} ms — phát hiện{" "}
                {analyzeResult.detections.length} đối tượng.
              </Typography.Text>
              <pre
                style={{
                  margin: 0,
                  padding: 12,
                  background: "#fafafa",
                  borderRadius: 4,
                  fontSize: 12,
                  maxHeight: 240,
                  overflow: "auto",
                }}
              >
                {JSON.stringify(analyzeResult.detections, null, 2)}
              </pre>
            </Space>
          </Card>
        )}
      </Modal>
    </Space>
  );
}
