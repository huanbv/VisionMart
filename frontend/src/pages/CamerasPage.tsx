import { useEffect, useRef, useState } from "react";
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
  AppstoreOutlined,
  BorderOuterOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  InboxOutlined,
  PlusOutlined,
  ReloadOutlined,
  VideoCameraAddOutlined,
  VideoCameraOutlined,
  WifiOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { listBranches, type Branch } from "@/api/tenancy";
import {
  type AnalyzeResult,
  type Camera,
  type CameraStats,
  type PreviewResult,
  analyzeCameraFrame,
  createCamera,
  deleteCamera,
  getCameraStats,
  heartbeatCamera,
  listCameras,
  previewCameraStream,
  updateCamera,
  uploadSimulatedStream,
} from "@/api/cameras";
import RoiOverlay from "@/components/RoiOverlay";
import RoiZoneEditor from "@/components/RoiZoneEditor";
import { useAuth } from "@/contexts/AuthContext";
import { openMjpegStream } from "@/utils/mjpegStream";

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
  auto_capture_enabled: boolean;
  is_checkout_zone: boolean;
  alert_classes: string;
  alert_min_confidence: number | null;
}

/**
 * One tile in the multi-camera grid wall (see "Xem dạng lưới" below).
 * Each tile owns its own independent MJPEG connection -- opened on mount
 * / whenever `detect` changes, always stopped on unmount -- so tiles can
 * be added/removed/re-rendered freely by the parent grid without leaking
 * connections. detectEveryN is higher than the single-camera live view's
 * default (5 vs 3): with several tiles running YOLO at once the CPU cost
 * multiplies, so the grid trades a bit of detection freshness for being
 * able to hold more simultaneous streams before the VPS chokes.
 */
function CameraGridTile({
  camera,
  detect,
}: {
  camera: Camera;
  detect: boolean;
}) {
  const [frame, setFrame] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setFrame(null);
    setError(null);
    const handle = openMjpegStream(
      camera.id,
      (url) => setFrame(url),
      (msg) => setError(msg),
      { detect, detectEveryN: 5 },
    );
    return () => handle.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera.id, detect]);

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        aspectRatio: "16 / 9",
        background: "#000",
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      {error ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 8,
            textAlign: "center",
          }}
        >
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            {error}
          </Typography.Text>
        </div>
      ) : frame ? (
        <>
          <img
            src={frame}
            alt={camera.name}
            style={{
              width: "100%",
              height: "100%",
              // "contain" chu khong phai "cover": cover cat bot hai ben
              // cua khung hinh, khien vung nhan dien ve o dung ti le lai
              // hien thi lech khoi vi tri that. Vien den hai ben chap
              // nhan duoc, con vung ve sai cho thi gay hieu nham.
              objectFit: "contain",
              display: "block",
            }}
          />
          <RoiOverlay zones={camera.roi_zones} showLabels={false} />
        </>
      ) : (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Đang kết nối...
          </Typography.Text>
        </div>
      )}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          background: "rgba(0,0,0,0.55)",
          color: "#fff",
          fontSize: 12,
          padding: "2px 8px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {camera.name}
        </span>
        {frame && !error && (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              flexShrink: 0,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "#ff4d4f",
                display: "inline-block",
              }}
            />
            LIVE
          </span>
        )}
      </div>
    </div>
  );
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
    form.setFieldsValue({
      is_active: true,
      auto_capture_enabled: false,
      is_checkout_zone: false,
      fps: 25,
      alert_classes: "",
      alert_min_confidence: null,
    });
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
      auto_capture_enabled: c.auto_capture_enabled,
      is_checkout_zone: c.is_checkout_zone,
      alert_classes: c.alert_classes ?? "",
      alert_min_confidence: c.alert_min_confidence,
    });
    setDrawerOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    setSaving(true);
    try {
      const location = values.location?.trim() || null;
      const resolution = values.resolution?.trim() || null;
      const fps = values.fps ?? null;
      const alertClasses = values.alert_classes?.trim() || null;
      const alertMinConfidence =
        typeof values.alert_min_confidence === "number"
          ? values.alert_min_confidence
          : null;
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
          auto_capture_enabled: values.auto_capture_enabled,
          is_checkout_zone: values.is_checkout_zone,
          alert_classes: alertClasses,
          alert_classes_unset: !alertClasses,
          alert_min_confidence: alertMinConfidence,
          alert_min_confidence_unset: alertMinConfidence === null,
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
          auto_capture_enabled: values.auto_capture_enabled,
          is_checkout_zone: values.is_checkout_zone,
          alert_classes: alertClasses,
          alert_min_confidence: alertMinConfidence,
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

  const [roiFor, setRoiFor] = useState<Camera | null>(null);
  const [previewFor, setPreviewFor] = useState<Camera | null>(null);
  const [previewResult, setPreviewResult] = useState<PreviewResult | null>(
    null,
  );
  const [previewLoading, setPreviewLoading] = useState(false);

  const onPreview = async (row: Camera) => {
    setPreviewFor(row);
    setPreviewResult(null);
    setPreviewLoading(true);
    try {
      const res = await previewCameraStream(row.id);
      setPreviewResult(res);
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      message.error(typeof d === "string" ? d : "Không mở được stream");
    } finally {
      setPreviewLoading(false);
    }
  };

  const closePreview = () => {
    setPreviewFor(null);
    setPreviewResult(null);
  };

  // Course project — no camera thật: cho phép tải video demo lên, backend
  // tự cấu hình luồng RTSP giả lập (camera-sim-runner) và cập nhật
  // stream_url của camera này.
  const [uploadFor, setUploadFor] = useState<Camera | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const onUploadSimulatedStream = async () => {
    if (!uploadFor || !uploadFile) return;
    setUploading(true);
    try {
      await uploadSimulatedStream(uploadFor.id, uploadFile);
      message.success(
        `Đã tải video lên — stream_url của '${uploadFor.name}' đã được cập nhật`,
      );
      setUploadFor(null);
      setUploadFile(null);
      load();
      loadStats();
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      message.error(typeof d === "string" ? d : "Tải video thất bại");
    } finally {
      setUploading(false);
    }
  };

  const closeUpload = () => {
    setUploadFor(null);
    setUploadFile(null);
  };

  // True continuous MJPEG live view (as opposed to /preview's one-shot
  // snapshot). Keeps a single mjpegStream connection open for as long as
  // the modal is visible; liveStopRef lets closeLive() and the effect
  // cleanup both reach the same "stop" function without re-renders
  // racing each other.
  const [liveFor, setLiveFor] = useState<Camera | null>(null);
  const [liveFrame, setLiveFrame] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  // Whether ai-engine should burn YOLO boxes + a HUD (object count,
  // inference ms, fps) into the frames — see live.py. On by default per
  // the "muốn xem như phim viễn tưởng" ask; toggle-able in case a slower
  // VPS makes it stutter, since YOLO inference is real CPU cost.
  const [liveDetect, setLiveDetect] = useState(true);
  const liveStopRef = useRef<(() => void) | null>(null);

  const startLive = (row: Camera, detectOverride?: boolean) => {
    liveStopRef.current?.();
    setLiveFor(row);
    setLiveFrame(null);
    setLiveError(null);
    const handle = openMjpegStream(
      row.id,
      (url) => setLiveFrame(url),
      (msg) => setLiveError(msg),
      { detect: detectOverride ?? liveDetect },
    );
    liveStopRef.current = handle.stop;
  };

  const openLive = (row: Camera) => startLive(row);

  const onToggleLiveDetect = (checked: boolean) => {
    setLiveDetect(checked);
    if (liveFor) startLive(liveFor, checked);
  };

  const closeLive = () => {
    liveStopRef.current?.();
    liveStopRef.current = null;
    setLiveFor(null);
    setLiveFrame(null);
    setLiveError(null);
  };

  // Safety net: if the component unmounts (e.g. user navigates away)
  // while a live view is open, don't leak the fetch connection.
  useEffect(() => {
    return () => {
      liveStopRef.current?.();
    };
  }, []);

  // CCTV-style "camera wall" -- shows every online camera live at once
  // instead of opening them one by one. Each tile (CameraGridTile above)
  // owns its own MJPEG connection, so closing the modal (destroyOnHidden
  // unmounts every tile) is all the cleanup needed.
  const [gridOpen, setGridOpen] = useState(false);
  const [gridCameras, setGridCameras] = useState<Camera[]>([]);
  const [gridLoading, setGridLoading] = useState(false);
  // Off by default: N tiles running YOLO simultaneously multiplies CPU
  // cost, unlike the single-camera live view where it's on by default.
  const [gridDetect, setGridDetect] = useState(false);

  const openGrid = async () => {
    setGridOpen(true);
    setGridLoading(true);
    try {
      const res = await listCameras({ is_online: true, limit: 100 });
      setGridCameras(res.items.filter((c) => c.is_active));
    } catch {
      message.error("Không tải được danh sách camera");
    } finally {
      setGridLoading(false);
    }
  };

  const closeGrid = () => {
    setGridOpen(false);
    setGridCameras([]);
  };

  const gridCols =
    gridCameras.length <= 1
      ? 1
      : gridCameras.length <= 4
        ? 2
        : gridCameras.length <= 9
          ? 3
          : 4;

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
      title: "Auto",
      dataIndex: "auto_capture_enabled",
      width: 80,
      render: (v: boolean) =>
        v ? <Tag color="blue">ON</Tag> : <Tag>OFF</Tag>,
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
      title: "Vùng nhận diện",
      width: 130,
      render: (_, row) =>
        row.roi_zones && row.roi_zones.length ? (
          <Tag color="green">{row.roi_zones.length} vùng</Tag>
        ) : (
          <Tag>Toàn khung</Tag>
        ),
    },
    {
      title: "Hành động",
      width: 330,
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
            icon={<EyeOutlined />}
            onClick={() => onPreview(row)}
            title="Xem thử luồng"
          />
          <Button
            size="small"
            icon={<VideoCameraOutlined />}
            onClick={() => openLive(row)}
            title="Xem trực tiếp"
          />
          <Button
            size="small"
            icon={<VideoCameraAddOutlined />}
            disabled={!canEdit}
            onClick={() => {
              setUploadFor(row);
              setUploadFile(null);
            }}
            title="Tải video demo lên (giả lập luồng camera)"
          />
          <Button
            size="small"
            icon={<BorderOuterOutlined />}
            disabled={!canEdit}
            onClick={() => setRoiFor(row)}
            title="Vẽ vùng nhận diện"
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
            <Button icon={<AppstoreOutlined />} onClick={openGrid}>
              Xem dạng lưới
            </Button>
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
        destroyOnHidden
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
          <Form.Item
            label="Tự động chụp khung hình (RTSP auto-capture)"
            name="auto_capture_enabled"
            valuePropName="checked"
            tooltip="Khi bật, hệ thống sẽ định kỳ kéo frame từ Stream URL của camera này để phân tích AI. Yêu cầu RTSP_CAPTURE_ENABLED=true trên server."
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label="Khu vực thanh toán (checkout zone)"
            name="is_checkout_zone"
            valuePropName="checked"
            tooltip="Khi bật, mỗi lần AI thấy người trong khung hình sẽ tự phát sự kiện checkout_initiated để backend chốt cart thành order."
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label="Class cảnh báo riêng (mặc định dùng cấu hình chung)"
            name="alert_classes"
            tooltip="Danh sách class phân cách bằng dấu phẩy. Ví dụ: person,car. Để trống để dùng DETECTION_ALERT_CLASSES toàn cục."
          >
            <Input maxLength={255} placeholder="person,car,motorcycle" />
          </Form.Item>
          <Form.Item
            label="Ngưỡng confidence cảnh báo riêng"
            name="alert_min_confidence"
            tooltip="Số từ 0.0 đến 1.0. Để trống để dùng DETECTION_ALERT_MIN_CONFIDENCE toàn cục."
          >
            <InputNumber
              min={0}
              max={1}
              step={0.05}
              style={{ width: "100%" }}
              placeholder="0.7"
            />
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
              {analyzeResult.frame_pipeline_error && (
                <Card size="small" type="inner" title="Cart pipeline error">
                  <Typography.Text type="danger">
                    {analyzeResult.frame_pipeline_error}
                  </Typography.Text>
                </Card>
              )}
              {analyzeResult.frame_pipeline && (
                <Card
                  size="small"
                  type="inner"
                  title="Cart pipeline (ByteTrack → SKU → cart events)"
                >
                  <Space direction="vertical" size={6} style={{ width: "100%" }}>
                    <Typography.Text>
                      Persons: <Tag>{analyzeResult.frame_pipeline.persons}</Tag>
                      Products (mapped SKU):{" "}
                      <Tag color={analyzeResult.frame_pipeline.products > 0 ? "green" : "orange"}>
                        {analyzeResult.frame_pipeline.products}
                      </Tag>
                      Checkout zone:{" "}
                      <Tag color={analyzeResult.frame_pipeline.is_checkout_zone ? "purple" : "default"}>
                        {analyzeResult.frame_pipeline.is_checkout_zone ? "YES" : "NO"}
                      </Tag>
                    </Typography.Text>
                    {analyzeResult.frame_pipeline.customer_id && (
                      <Typography.Text type="secondary">
                        Customer nhận diện: {analyzeResult.frame_pipeline.customer_id}
                      </Typography.Text>
                    )}
                    {analyzeResult.frame_pipeline.emitted_events.length === 0 ? (
                      <Typography.Text type="warning">
                        Chưa phát sự kiện nào. Kiểm tra: (1) camera có bật "Khu vực
                        thanh toán" không, (2) ảnh có product được map trong
                        class_to_sku.json không, (3) confidence &ge; ngưỡng.
                      </Typography.Text>
                    ) : (
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
                        {JSON.stringify(analyzeResult.frame_pipeline.emitted_events, null, 2)}
                      </pre>
                    )}
                  </Space>
                </Card>
              )}
            </Space>
          </Card>
        )}
      </Modal>

      <RoiZoneEditor
        camera={roiFor}
        open={!!roiFor}
        onClose={() => setRoiFor(null)}
      />

      <Modal
        title={
          previewFor
            ? `Xem thử luồng — ${previewFor.name}`
            : "Xem thử luồng"
        }
        open={!!previewFor}
        onCancel={closePreview}
        footer={[
          <Button key="close" onClick={closePreview}>
            Đóng
          </Button>,
          <Button
            key="refresh"
            type="primary"
            icon={<ReloadOutlined />}
            loading={previewLoading}
            onClick={() => previewFor && onPreview(previewFor)}
          >
            Chụp lại
          </Button>,
        ]}
        width={720}
      >
        {previewLoading && !previewResult && (
          <Typography.Text type="secondary">
            Đang mở luồng và chụp khung hình...
          </Typography.Text>
        )}
        {previewResult && (
          <Space direction="vertical" style={{ width: "100%" }} size={12}>
            <div
              style={{
                position: "relative",
                width: "100%",
                background: "#000",
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <img
                src={`data:image/jpeg;base64,${previewResult.frame_base64}`}
                alt="preview"
                style={{ width: "100%", display: "block" }}
              />
              {previewResult.detections.map((d, i) => {
                const w = previewResult.image.width || 1;
                const h = previewResult.image.height || 1;
                return (
                  <div
                    key={i}
                    style={{
                      position: "absolute",
                      left: `${(d.bbox.x1 / w) * 100}%`,
                      top: `${(d.bbox.y1 / h) * 100}%`,
                      width: `${((d.bbox.x2 - d.bbox.x1) / w) * 100}%`,
                      height: `${((d.bbox.y2 - d.bbox.y1) / h) * 100}%`,
                      border: "2px solid #52c41a",
                      boxSizing: "border-box",
                    }}
                  >
                    <span
                      style={{
                        position: "absolute",
                        top: -18,
                        left: 0,
                        background: "#52c41a",
                        color: "#fff",
                        fontSize: 11,
                        padding: "0 4px",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {d.class_name} {(d.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                );
              })}
            </div>
            <Typography.Text>
              Model: <Tag color="blue">{previewResult.model}</Tag>
              Kích thước: {previewResult.image.width}×
              {previewResult.image.height} ({previewResult.image.format},{" "}
              {previewResult.image.size_bytes} B)
            </Typography.Text>
            <Typography.Text type="secondary">
              Thời gian chụp + suy luận: {previewResult.elapsed_ms} ms — phát
              hiện {previewResult.detections.length} đối tượng.
            </Typography.Text>
          </Space>
        )}
      </Modal>

      <Modal
        title={liveFor ? `Xem trực tiếp — ${liveFor.name}` : "Xem trực tiếp"}
        open={!!liveFor}
        onCancel={closeLive}
        footer={[
          <Button key="close" onClick={closeLive}>
            Đóng
          </Button>,
        ]}
        width={720}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Space>
            <Switch
              checked={liveDetect}
              onChange={onToggleLiveDetect}
              size="small"
            />
            <Typography.Text>Nhận diện AI trực tiếp (YOLO)</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Khung/nhãn + số liệu (số đối tượng, tốc độ suy luận, fps) được
              vẽ trực tiếp lên hình.
            </Typography.Text>
          </Space>
          {liveError && (
            <Typography.Text type="danger">{liveError}</Typography.Text>
          )}
          {!liveError && !liveFrame && (
            <Typography.Text type="secondary">
              Đang kết nối luồng trực tiếp...
            </Typography.Text>
          )}
          {!liveError && liveFrame && (
            <div
              style={{
                position: "relative",
                width: "100%",
                background: "#000",
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <img
                src={liveFrame}
                alt="live"
                style={{ width: "100%", display: "block" }}
              />
              {/* Anh giu nguyen ti le goc (chi dat width) nen overlay theo
                  phan tram trung khop chinh xac voi noi dung khung hinh. */}
              <RoiOverlay zones={liveFor?.roi_zones} />
            </div>
          )}
        </Space>
      </Modal>

      <Modal
        title={
          <Space>
            <span>Xem dạng lưới — Camera đang online</span>
            <Tag color="blue">{gridCameras.length} camera</Tag>
          </Space>
        }
        open={gridOpen}
        onCancel={closeGrid}
        footer={[
          <Button key="close" onClick={closeGrid}>
            Đóng
          </Button>,
        ]}
        width="90vw"
        style={{ top: 20 }}
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Space wrap>
            <Switch
              checked={gridDetect}
              onChange={setGridDetect}
              size="small"
            />
            <Typography.Text>Nhận diện AI trên toàn bộ lưới</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Bật YOLO cho nhiều luồng cùng lúc tốn CPU hơn nhiều — chỉ bật
              khi thật cần.
            </Typography.Text>
          </Space>
          {gridLoading && (
            <Typography.Text type="secondary">
              Đang tải danh sách camera online...
            </Typography.Text>
          )}
          {!gridLoading && gridCameras.length === 0 && (
            <Typography.Text type="secondary">
              Không có camera nào đang online.
            </Typography.Text>
          )}
          {!gridLoading && gridCameras.length > 0 && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: `repeat(${gridCols}, 1fr)`,
                gap: 8,
                maxHeight: "75vh",
                overflowY: "auto",
              }}
            >
              {gridCameras.map((c) => (
                <CameraGridTile key={c.id} camera={c} detect={gridDetect} />
              ))}
            </div>
          )}
        </Space>
      </Modal>

      <Modal
        title={
          uploadFor
            ? `Tải video demo lên — ${uploadFor.name}`
            : "Tải video demo lên"
        }
        open={!!uploadFor}
        onCancel={closeUpload}
        footer={[
          <Button key="close" onClick={closeUpload}>
            Đóng
          </Button>,
          <Button
            key="upload"
            type="primary"
            disabled={!uploadFile}
            loading={uploading}
            onClick={onUploadSimulatedStream}
          >
            Tải lên & áp dụng
          </Button>,
        ]}
        width={520}
      >
        <Typography.Paragraph type="secondary">
          Chưa có camera vật lý? Tải một video demo lên — hệ thống sẽ tự
          động phát video này thành luồng RTSP giả lập và cập nhật lại
          Stream URL của camera này (ghi đè giá trị hiện tại).
        </Typography.Paragraph>
        <Upload.Dragger
          multiple={false}
          accept="video/*,.mp4,.mov,.mkv,.avi,.webm"
          beforeUpload={(file) => {
            setUploadFile(file as File);
            return false;
          }}
          onRemove={() => setUploadFile(null)}
          fileList={
            uploadFile
              ? [{ uid: "1", name: uploadFile.name, status: "done" }]
              : []
          }
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">Kéo thả hoặc bấm để chọn video</p>
          <p className="ant-upload-hint">
            MP4/MOV/MKV/AVI/WEBM, tối đa 200 MB
          </p>
        </Upload.Dragger>
      </Modal>
    </Space>
  );
}
