import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Card,
  Col,
  Collapse,
  Descriptions,
  Progress,
  Row,
  Space,
  Statistic,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  ClockCircleOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  DesktopOutlined,
  HeartOutlined,
  InfoCircleOutlined,
  ThunderboltOutlined,
  VideoCameraOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import {
  type AlertRecord,
  type CameraStatus,
  type HealthScoreResponse,
  type OverviewResponse,
  type ReleaseInfoResponse,
  type SessionLifecycleView,
  getCameraHealth,
  getHealthScore,
  getOverview,
  getReleaseInfo,
  getSessionLifecycle,
} from "@/api/opsMonitoring";

const REFRESH_MS = 15000;

function fmtPct(v: number | null | undefined) {
  return v === null || v === undefined ? "n/a" : `${v.toFixed(1)}%`;
}
function fmtMs(v: number | null | undefined) {
  return v === null || v === undefined ? "n/a" : `${v.toFixed(1)} ms`;
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: "red",
  warning: "orange",
  info: "blue",
};

const STAGE_COLOR: Record<string, string> = {
  tracking: "default",
  cart_active: "blue",
  pending_checkout: "orange",
  completed: "green",
  abandoned: "default",
  unknown: "default",
};

const HEALTH_STATUS_COLOR: Record<string, string> = {
  Healthy: "#3f8600",
  Warning: "#d48806",
  Degraded: "#d4380d",
  Critical: "#cf1322",
  Offline: "#5c0011",
};

const HEALTH_STATUS_LABEL_VI: Record<string, string> = {
  Healthy: "Khỏe mạnh",
  Warning: "Cảnh báo",
  Degraded: "Suy giảm",
  Critical: "Nghiêm trọng",
  Offline: "Ngừng hoạt động",
};

function componentTagColor(v: string): string {
  if (v === "OK" || v === "Healthy") return "green";
  if (v === "WARNING") return "orange";
  if (v === "CRITICAL") return "red";
  if (v === "NOT_CONFIGURED") return "default";
  return "blue";
}

export default function SystemHealthPage() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [cameras, setCameras] = useState<CameraStatus[]>([]);
  const [sessions, setSessions] = useState<SessionLifecycleView[]>([]);
  const [sessionsReachable, setSessionsReachable] = useState(true);
  const [sessionsReason, setSessionsReason] = useState<string | null>(null);
  const [healthScore, setHealthScore] = useState<HealthScoreResponse | null>(null);
  const [releaseInfo, setReleaseInfo] = useState<ReleaseInfoResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [lastError, setLastError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, cam, sess, hs] = await Promise.all([
        getOverview(),
        getCameraHealth(),
        getSessionLifecycle(24, 100),
        getHealthScore(),
      ]);
      setOverview(ov);
      setCameras(cam.cameras);
      setSessions(sess.sessions);
      setSessionsReachable(sess.reachable);
      setSessionsReason(sess.reason);
      setHealthScore(hs);
      setLastError(null);
    } catch (e) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Không tải được dữ liệu giám sát";
      setLastError(msg);
      message.error(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [autoRefresh, load]);

  // Release info (git commit / build time / versions) is effectively
  // static for the lifetime of a running deployment — fetched once on
  // mount rather than on every 15s refresh cycle to avoid spamming the
  // monitoring service for data that cannot change without a redeploy.
  useEffect(() => {
    getReleaseInfo()
      .then(setReleaseInfo)
      .catch(() => setReleaseInfo(null));
  }, []);

  const cameraColumns: ColumnsType<CameraStatus> = [
    { title: "Camera", render: (_, r) => `${r.name} (${r.code})` },
    {
      title: "Trạng thái",
      dataIndex: "is_online_db",
      width: 110,
      render: (v: boolean) => (
        <Badge status={v ? "success" : "error"} text={v ? "Online" : "Offline"} />
      ),
    },
    {
      title: "FPS",
      dataIndex: "fps",
      width: 90,
      render: (v: number | null, r) =>
        v !== null ? (
          v.toFixed(1)
        ) : (
          <Tooltip title={r.fps_reason ?? undefined}>
            <Typography.Text type="secondary">n/a</Typography.Text>
          </Tooltip>
        ),
    },
    { title: "Dropped", dataIndex: "dropped_frames_total", width: 90, render: (v) => v ?? "n/a" },
    {
      title: "Độ trễ pipeline",
      dataIndex: "avg_pipeline_latency_ms",
      width: 130,
      render: (v: number | null) => fmtMs(v),
    },
    {
      title: "Reconnect*",
      dataIndex: "reconnect_count_since_monitoring_start",
      width: 100,
    },
  ];

  const alertColumns: ColumnsType<AlertRecord> = [
    {
      title: "Mức độ",
      dataIndex: "severity",
      width: 100,
      render: (v: string) => <Tag color={SEVERITY_COLOR[v] ?? "default"}>{v.toUpperCase()}</Tag>,
    },
    { title: "Quy tắc", dataIndex: "rule_id", width: 200 },
    { title: "Đối tượng", dataIndex: "subject", width: 160 },
    { title: "Thông báo", dataIndex: "message" },
    {
      title: "Từ lúc",
      dataIndex: "first_seen",
      width: 170,
      render: (v: number) => new Date(v * 1000).toLocaleString("vi-VN"),
    },
  ];

  const sessionColumns: ColumnsType<SessionLifecycleView> = [
    { title: "Cart ID", dataIndex: "cart_id", width: 120, render: (v: string) => v.slice(0, 8) },
    { title: "Nguồn", dataIndex: "source", width: 100 },
    {
      title: "Giai đoạn hiện tại",
      dataIndex: "current_stage",
      width: 150,
      render: (v: string) => <Tag color={STAGE_COLOR[v] ?? "default"}>{v}</Tag>,
    },
    { title: "Số món", dataIndex: "item_count", width: 80, align: "right" },
    {
      title: "Tổng tiền",
      dataIndex: "total_amount",
      width: 130,
      align: "right",
      render: (v: string) => `${Number(v).toLocaleString("vi-VN")} ₫`,
    },
    {
      title: "Ghi chú quan sát",
      dataIndex: "observation_note",
      render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v}</Typography.Text>,
    },
  ];

  const system = overview?.system ?? {};
  const host = system.host ?? {};
  const pipe = overview?.ai_pipeline ?? {};
  const svc = overview?.service_health ?? {};

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card>
        <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
          <Space wrap>
            <Typography.Text strong>
              <ClockCircleOutlined /> Cập nhật lần cuối:{" "}
              {overview ? new Date(overview.generated_at * 1000).toLocaleTimeString("vi-VN") : "—"}
            </Typography.Text>
            {overview?.poller.last_error && (
              <Tag color="red">Lỗi poll gần nhất: {overview.poller.last_error}</Tag>
            )}
          </Space>
          <Space>
            <Typography.Text type="secondary">Tự động làm mới (15s)</Typography.Text>
            <Switch checked={autoRefresh} onChange={setAutoRefresh} />
          </Space>
        </Space>
        {lastError && (
          <Alert style={{ marginTop: 12 }} type="error" showIcon message={lastError} />
        )}
      </Card>

      <Card loading={loading && !healthScore}>
        <Row gutter={24} align="middle">
          <Col xs={24} md={6}>
            <Statistic
              title={<><HeartOutlined /> Điểm sức khỏe hệ thống</>}
              value={healthScore?.score ?? "—"}
              suffix="/ 100"
              valueStyle={{
                color: healthScore ? HEALTH_STATUS_COLOR[healthScore.status] : undefined,
                fontSize: 40,
              }}
            />
            {healthScore && (
              <Tag
                color={componentTagColor(healthScore.status === "Healthy" ? "OK" : healthScore.status === "Warning" ? "WARNING" : "CRITICAL")}
                style={{ marginTop: 8, fontSize: 13, padding: "2px 10px" }}
              >
                {HEALTH_STATUS_LABEL_VI[healthScore.status] ?? healthScore.status} ({healthScore.status})
              </Tag>
            )}
          </Col>
          <Col xs={24} md={18}>
            <Space wrap size={[8, 8]}>
              {healthScore &&
                Object.entries(healthScore.components).map(([name, val]) => (
                  <Tag key={name} color={componentTagColor(val)}>
                    {name}: {val}
                  </Tag>
                ))}
            </Space>
            {healthScore && healthScore.reasoning.length > 0 && (
              <Collapse
                ghost
                size="small"
                style={{ marginTop: 8 }}
                items={[
                  {
                    key: "reasoning",
                    label: "Chi tiết tính điểm",
                    children: (
                      <ul style={{ margin: 0, paddingLeft: 20 }}>
                        {healthScore.reasoning.map((r, i) => (
                          <li key={i}>
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{r}</Typography.Text>
                          </li>
                        ))}
                      </ul>
                    ),
                  },
                ]}
              />
            )}
          </Col>
        </Row>
      </Card>

      <Row gutter={16}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Backend"
              prefix={<CloudServerOutlined />}
              value={svc.backend?.ok ? "OK" : "DOWN"}
              valueStyle={{ color: svc.backend?.ok ? "#3f8600" : "#cf1322" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="AI Engine"
              prefix={<ThunderboltOutlined />}
              value={svc.ai_engine?.ok ? "OK" : "DOWN"}
              valueStyle={{ color: svc.ai_engine?.ok ? "#3f8600" : "#cf1322" }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Camera online"
              prefix={<VideoCameraOutlined />}
              value={overview?.camera_summary.online ?? 0}
              suffix={`/ ${overview?.camera_summary.total ?? 0}`}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Cảnh báo đang hoạt động"
              prefix={<WarningOutlined />}
              value={overview?.active_alert_count ?? 0}
              valueStyle={{ color: (overview?.active_alert_count ?? 0) > 0 ? "#cf1322" : undefined }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} lg={12}>
          <Card title={<><DesktopOutlined /> Tài nguyên hệ thống</>} loading={loading}>
            <Space direction="vertical" style={{ width: "100%" }} size={12}>
              <div>
                <Typography.Text>CPU</Typography.Text>
                <Progress percent={host.cpu_percent ?? 0} size="small" status={(host.cpu_percent ?? 0) > 90 ? "exception" : "active"} format={() => fmtPct(host.cpu_percent)} />
              </div>
              <div>
                <Typography.Text>RAM</Typography.Text>
                <Progress percent={host.ram_percent ?? 0} size="small" status={(host.ram_percent ?? 0) > 90 ? "exception" : "active"} format={() => fmtPct(host.ram_percent)} />
              </div>
              <div>
                <Typography.Text>Disk</Typography.Text>
                <Progress percent={host.disk_percent ?? 0} size="small" status={(host.disk_percent ?? 0) > 85 ? "exception" : "active"} format={() => fmtPct(host.disk_percent)} />
              </div>
              <Space wrap>
                <Tag icon={<DatabaseOutlined />} color={system.postgres?.reachable ? "green" : "red"}>
                  PostgreSQL {system.postgres?.reachable ? "OK" : "DOWN"}
                </Tag>
                <Tag color={system.redis?.reachable ? "green" : "red"}>
                  Redis {system.redis?.reachable ? "OK" : "DOWN"}
                </Tag>
                <Tag color={(system.celery?.worker_count ?? 0) > 0 ? "green" : "red"}>
                  Celery workers: {system.celery?.worker_count ?? 0}
                </Tag>
                <Tag color={host.gpu_available ? "green" : "default"}>
                  GPU: {host.gpu_available ? fmtPct(host.gpu_util_percent) : "không có"}
                </Tag>
              </Space>
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="AI Pipeline" loading={loading}>
            <Space direction="vertical" size={4} style={{ width: "100%" }}>
              <div>Inference: <b>{fmtMs(pipe.inference_latency_ms)}</b></div>
              <div>OpenCV stage: <b>{fmtMs(pipe.opencv_stage_ms)}</b></div>
              <div>YOLO+ByteTrack stage: <b>{fmtMs(pipe.yolo_bytetrack_stage_ms)}</b></div>
              <div>Tổng pipeline: <b>{fmtMs(pipe.pipeline_total_ms)}</b></div>
              <div>
                Active tracks:{" "}
                <Tooltip title={pipe.active_tracks_reason}>
                  <Typography.Text type="secondary">{pipe.active_tracks ?? "not_available"}</Typography.Text>
                </Tooltip>
              </div>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card title="Camera" loading={loading}>
        <Table
          rowKey="camera_id"
          dataSource={cameras}
          columns={cameraColumns}
          pagination={false}
          size="small"
          locale={{ emptyText: "Chưa có dữ liệu camera" }}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          *Số lần kết nối lại được ghi nhận kể từ khi dịch vụ giám sát bắt đầu chạy — xem docs/MONITORING.md.
        </Typography.Text>
      </Card>

      <Card title="Cảnh báo đang hoạt động" loading={loading}>
        <Table
          rowKey="id"
          dataSource={overview?.active_alerts ?? []}
          columns={alertColumns}
          pagination={false}
          size="small"
          locale={{ emptyText: "Không có cảnh báo" }}
        />
      </Card>

      <Card title="Vòng đời phiên mua sắm (24 giờ gần nhất)" loading={loading}>
        {!sessionsReachable && (
          <Alert
            style={{ marginBottom: 12 }}
            type="warning"
            showIcon
            message="Không đọc được dữ liệu phiên mua sắm"
            description={sessionsReason}
          />
        )}
        <Table
          rowKey="cart_id"
          dataSource={sessions}
          columns={sessionColumns}
          pagination={{ pageSize: 10 }}
          size="small"
          locale={{ emptyText: "Không có phiên nào" }}
        />
      </Card>

      <Card title={<><InfoCircleOutlined /> Thông tin phiên bản (Release Information)</>}>
        {!releaseInfo ? (
          <Typography.Text type="secondary">Không tải được thông tin phiên bản.</Typography.Text>
        ) : (
          <>
            {releaseInfo._error && (
              <Alert style={{ marginBottom: 12 }} type="warning" showIcon message={releaseInfo._error} />
            )}
            <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }} bordered>
              <Descriptions.Item label="Phiên bản ứng dụng">{releaseInfo.application_version}</Descriptions.Item>
              <Descriptions.Item label="Git commit">
                <Tooltip title={releaseInfo.git?.commit}>{releaseInfo.git?.commit_short}</Tooltip>
                {releaseInfo.git?.dirty ? <Tag color="orange" style={{ marginLeft: 6 }}>dirty</Tag> : null}
              </Descriptions.Item>
              <Descriptions.Item label="Git branch">{releaseInfo.git?.branch}</Descriptions.Item>
              <Descriptions.Item label="Build time (UTC)">{releaseInfo.build_time_utc ?? "unknown"}</Descriptions.Item>
              <Descriptions.Item label="Docker image tag">{releaseInfo.docker_image_tag}</Descriptions.Item>
              <Descriptions.Item label="Environment">{releaseInfo.environment}</Descriptions.Item>
              <Descriptions.Item label="Backend version">{releaseInfo.component_versions?.backend}</Descriptions.Item>
              <Descriptions.Item label="AI Engine version">{releaseInfo.component_versions?.ai_engine}</Descriptions.Item>
              <Descriptions.Item label="Python (runtime)">{releaseInfo.runtime?.monitoring_python_version}</Descriptions.Item>
              <Descriptions.Item label="Node (pinned image)">{releaseInfo.pinned_runtimes?.frontend_node_image}</Descriptions.Item>
              <Descriptions.Item label="Database version">{releaseInfo.runtime?.database_version}</Descriptions.Item>
              <Descriptions.Item label="Operating System">
                {releaseInfo.runtime?.os} {releaseInfo.runtime?.os_release}
              </Descriptions.Item>
              <Descriptions.Item label="Kernel version" span={2}>
                {releaseInfo.runtime?.os_version}
              </Descriptions.Item>
            </Descriptions>
            {releaseInfo.honesty_note && (
              <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 8 }}>
                {releaseInfo.honesty_note}
              </Typography.Text>
            )}
          </>
        )}
      </Card>
    </Space>
  );
}
