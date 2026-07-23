import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Image,
  List,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  LeftOutlined,
  RightOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import {
  getFrameDetail,
  getFrameSteps,
  getSessionStats,
  listFrames,
  listSessions,
  listTracks,
  type FrameDetail,
  type FrameStep,
  type PipelineFrame,
  type PipelineSession,
  type PipelineTrack,
  type SessionStats,
} from "@/api/aiPipeline";

const { Title, Text, Paragraph } = Typography;

/**
 * AI pipeline dashboard — the "see every step" replacement for the old
 * "click and get one result image" view.
 *
 * Three panels, left to right: pick a session (one camera's run), page
 * through its frames on a timeline, then open one frame to see every
 * pipeline step, the detections, the classifier's verdict, and the log
 * lines. The per-step images only exist for frames captured while DEBUG_AI
 * was on; a frame without them still shows its metrics and detections, and
 * says why the images are absent rather than showing broken thumbnails.
 */
export default function AiPipelineDashboardPage() {
  const [sessions, setSessions] = useState<PipelineSession[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [stats, setStats] = useState<SessionStats | null>(null);
  const [tracks, setTracks] = useState<PipelineTrack[]>([]);
  const [frames, setFrames] = useState<PipelineFrame[]>([]);
  const [onlyRejected, setOnlyRejected] = useState(false);
  const [frameId, setFrameId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FrameDetail | null>(null);
  const [steps, setSteps] = useState<FrameStep[]>([]);
  const [stepsReason, setStepsReason] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadSessions = useCallback(() => {
    listSessions({ limit: 100 })
      .then((res) => setSessions(res.items))
      .catch(() => message.error("Không tải được danh sách phiên"));
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // When a session is picked, load its header stats, its tracks, and the
  // first page of frames together.
  useEffect(() => {
    if (!sessionId) return;
    setFrameId(null);
    setDetail(null);
    getSessionStats(sessionId).then(setStats).catch(() => setStats(null));
    listTracks(sessionId).then(setTracks).catch(() => setTracks([]));
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    listFrames(sessionId, { limit: 200, only_rejected: onlyRejected })
      .then((res) => setFrames(res.items))
      .catch(() => message.error("Không tải được danh sách khung hình"));
  }, [sessionId, onlyRejected]);

  // When a frame is picked, load its detail and its step images in parallel.
  useEffect(() => {
    if (!frameId) return;
    setLoading(true);
    Promise.all([getFrameDetail(frameId), getFrameSteps(frameId)])
      .then(([d, s]) => {
        setDetail(d);
        setSteps(s.steps);
        setStepsReason(s.reason ?? null);
      })
      .catch(() => message.error("Không tải được chi tiết khung hình"))
      .finally(() => setLoading(false));
  }, [frameId]);

  const fmtMs = (v: number | null | undefined) =>
    v == null ? "—" : `${v.toFixed(1)} ms`;
  const fmtPct = (v: number | null | undefined) =>
    v == null ? "—" : `${(v * 100).toFixed(1)}%`;

  return (
    <div style={{ padding: 16 }}>
      <Space
        align="center"
        style={{ width: "100%", justifyContent: "space-between", marginBottom: 12 }}
      >
        <Title level={3} style={{ margin: 0 }}>
          Bảng điều khiển pipeline AI
        </Title>
        <Button icon={<ReloadOutlined />} onClick={loadSessions}>
          Làm mới
        </Button>
      </Space>
      <Paragraph type="secondary" style={{ marginTop: 0 }}>
        Xem lại toàn bộ hành trình một khung hình đi qua AI: tiền xử lý → phát
        hiện → cắt → phân loại → kết quả. Ảnh từng bước chỉ có với khung hình
        được ghi khi bật <Text code>DEBUG_AI</Text>.
      </Paragraph>

      <Row gutter={16}>
        {/* Panel 1 — sessions */}
        <Col xs={24} md={6}>
          <Card size="small" title="Phiên (theo camera)">
            {sessions.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="Chưa có phiên nào được ghi"
              />
            ) : (
              <List
                size="small"
                dataSource={sessions}
                style={{ maxHeight: 520, overflowY: "auto" }}
                renderItem={(s) => (
                  <List.Item
                    onClick={() => setSessionId(s.id)}
                    style={{
                      cursor: "pointer",
                      background:
                        s.id === sessionId ? "rgba(24,144,255,0.12)" : undefined,
                      borderRadius: 6,
                      paddingLeft: 8,
                    }}
                  >
                    <Space direction="vertical" size={0}>
                      <Text strong>{s.camera_key}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {new Date(s.started_at).toLocaleString()}
                      </Text>
                      <Space size={4}>
                        <Tag color={s.status === "active" ? "green" : "default"}>
                          {s.status}
                        </Tag>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {s.frame_count} khung · {s.detection_count} nhận diện
                        </Text>
                      </Space>
                    </Space>
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>

        {/* Panel 2 — stats + frame timeline */}
        <Col xs={24} md={7}>
          {stats && (
            <Card size="small" title="Tổng quan phiên" style={{ marginBottom: 12 }}>
              <Row gutter={8}>
                <Col span={12}>
                  <Statistic title="Số khung" value={stats.frame_count} />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="Tỉ lệ loại (chất lượng)"
                    value={fmtPct(stats.reject_rate)}
                    valueStyle={{
                      color: stats.reject_rate > 0.2 ? "#cf1322" : undefined,
                    }}
                  />
                </Col>
                <Col span={12}>
                  <Statistic title="Trễ TB" value={fmtMs(stats.avg_total_ms)} />
                </Col>
                <Col span={12}>
                  <Statistic
                    title="Tin cậy TB"
                    value={fmtPct(stats.avg_confidence)}
                  />
                </Col>
              </Row>
              {tracks.length > 0 && (
                <>
                  <Text strong style={{ display: "block", marginTop: 8 }}>
                    Đối tượng theo dõi
                  </Text>
                  <Space wrap size={4} style={{ marginTop: 4 }}>
                    {tracks.map((t) => (
                      <Tag key={t.id} color={t.resolved_sku ? "blue" : "default"}>
                        #{t.track_id} {t.resolved_sku ?? t.class_name ?? "?"}
                        {t.resolved_confidence != null &&
                          ` ${fmtPct(t.resolved_confidence)}`}
                      </Tag>
                    ))}
                  </Space>
                </>
              )}
            </Card>
          )}

          {sessionId && (
            <Card
              size="small"
              title="Khung hình"
              extra={
                <Button
                  size="small"
                  type={onlyRejected ? "primary" : "default"}
                  danger={onlyRejected}
                  onClick={() => setOnlyRejected((v) => !v)}
                >
                  {onlyRejected ? "Đang lọc: bị loại" : "Chỉ khung bị loại"}
                </Button>
              }
            >
              {frames.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="Không có khung hình"
                />
              ) : (
                <List
                  size="small"
                  dataSource={frames}
                  style={{ maxHeight: 460, overflowY: "auto" }}
                  renderItem={(f) => (
                    <List.Item
                      onClick={() => setFrameId(f.id)}
                      style={{
                        cursor: "pointer",
                        background:
                          f.id === frameId ? "rgba(24,144,255,0.12)" : undefined,
                        borderRadius: 6,
                        paddingLeft: 8,
                      }}
                    >
                      <Space
                        style={{ width: "100%", justifyContent: "space-between" }}
                      >
                        <Space size={6}>
                          {!f.gate_passed && <Badge status="error" />}
                          <Text>#{f.seq}</Text>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {fmtMs(f.total_ms)}
                          </Text>
                        </Space>
                        {!f.gate_passed ? (
                          <Tag color="red">{f.reject_reason ?? "loại"}</Tag>
                        ) : f.storage_prefix ? (
                          <Tag color="green">có ảnh bước</Tag>
                        ) : null}
                      </Space>
                    </List.Item>
                  )}
                />
              )}
            </Card>
          )}
        </Col>

        {/* Panel 3 — frame detail */}
        <Col xs={24} md={11}>
          {!frameId ? (
            <Card size="small">
              <Empty description="Chọn một khung hình để xem từng bước" />
            </Card>
          ) : (
            <Card
              size="small"
              loading={loading}
              title={detail ? `Khung #${detail.frame.seq}` : "Khung hình"}
              extra={
                <Space>
                  <Button
                    size="small"
                    icon={<LeftOutlined />}
                    disabled={!detail?.previous_frame_id}
                    onClick={() =>
                      detail?.previous_frame_id &&
                      setFrameId(detail.previous_frame_id)
                    }
                  >
                    Trước
                  </Button>
                  <Button
                    size="small"
                    disabled={!detail?.next_frame_id}
                    onClick={() =>
                      detail?.next_frame_id && setFrameId(detail.next_frame_id)
                    }
                  >
                    Sau <RightOutlined />
                  </Button>
                </Space>
              }
            >
              {detail && (
                <Space direction="vertical" style={{ width: "100%" }} size={12}>
                  {/* quality / timing */}
                  <Descriptions size="small" column={2} bordered>
                    <Descriptions.Item label="Độ sáng">
                      {detail.frame.brightness?.toFixed(1) ?? "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Tương phản">
                      {detail.frame.contrast?.toFixed(1) ?? "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Độ nét (blur)">
                      {detail.frame.blur_score?.toFixed(1) ?? "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Điểm chất lượng">
                      {detail.frame.quality_score?.toFixed(2) ?? "—"}
                    </Descriptions.Item>
                    <Descriptions.Item label="Tiền xử lý">
                      {fmtMs(detail.frame.preprocess_ms)}
                    </Descriptions.Item>
                    <Descriptions.Item label="Phát hiện">
                      {fmtMs(detail.frame.detect_ms)}
                    </Descriptions.Item>
                  </Descriptions>

                  {!detail.frame.gate_passed && (
                    <Alert
                      type="error"
                      showIcon
                      message={`Bị loại ở cổng chất lượng: ${
                        detail.frame.reject_reason ?? "không rõ"
                      }`}
                    />
                  )}

                  {/* per-step images */}
                  <div>
                    <Text strong>Ảnh từng bước</Text>
                    {steps.length === 0 ? (
                      <Alert
                        style={{ marginTop: 4 }}
                        type="info"
                        showIcon
                        message={
                          stepsReason ??
                          "Khung này không có ảnh bước (DEBUG_AI tắt)."
                        }
                      />
                    ) : (
                      <Image.PreviewGroup>
                        <Row gutter={[8, 8]} style={{ marginTop: 8 }}>
                          {steps.map((s) => (
                            <Col span={8} key={s.key}>
                              <Card
                                size="small"
                                styles={{ body: { padding: 4 } }}
                                cover={
                                  s.url ? (
                                    <Image
                                      src={s.url}
                                      alt={s.step}
                                      style={{ objectFit: "cover" }}
                                    />
                                  ) : (
                                    <div
                                      style={{
                                        height: 80,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        color: "#999",
                                      }}
                                    >
                                      không tải được
                                    </div>
                                  )
                                }
                              >
                                <Text style={{ fontSize: 12 }}>
                                  {s.order}. {s.step}
                                </Text>
                              </Card>
                            </Col>
                          ))}
                        </Row>
                      </Image.PreviewGroup>
                    )}
                  </div>

                  {/* detections + classifier verdict */}
                  <div>
                    <Text strong>Nhận diện & phân loại</Text>
                    <Table
                      size="small"
                      style={{ marginTop: 8 }}
                      rowKey={(r) => r.detection.id}
                      pagination={false}
                      dataSource={detail.detections}
                      columns={[
                        {
                          title: "Lớp",
                          dataIndex: ["detection", "class_name"],
                          render: (_: unknown, r: FrameDetail["detections"][number]) => (
                            <Space size={4}>
                              {r.detection.track_id != null && (
                                <Tag>#{r.detection.track_id}</Tag>
                              )}
                              {r.detection.class_name}
                            </Space>
                          ),
                        },
                        {
                          title: "YOLO",
                          dataIndex: ["detection", "confidence"],
                          render: (v: number) => fmtPct(v),
                        },
                        {
                          title: "SKU (phân loại)",
                          render: (_: unknown, r: FrameDetail["detections"][number]) =>
                            r.classification ? (
                              <Space direction="vertical" size={0}>
                                <Text strong>{r.classification.sku}</Text>
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {fmtPct(r.classification.confidence)}
                                  {r.classification.runner_up_sku &&
                                    ` · nhì: ${r.classification.runner_up_sku}`}
                                  {r.classification.margin != null &&
                                    ` · biên ${fmtPct(r.classification.margin)}`}
                                </Text>
                              </Space>
                            ) : (
                              <Text type="secondary">—</Text>
                            ),
                        },
                        {
                          title: "Kết hợp",
                          dataIndex: ["detection", "combined_confidence"],
                          render: (v: number | null) => fmtPct(v),
                        },
                      ]}
                    />
                  </div>

                  {/* logs */}
                  {detail.logs.length > 0 && (
                    <div>
                      <Text strong>Nhật ký xử lý</Text>
                      <List
                        size="small"
                        style={{ marginTop: 4 }}
                        dataSource={detail.logs}
                        renderItem={(l) => (
                          <List.Item style={{ padding: "4px 0" }}>
                            <Space size={6}>
                              <Tag
                                color={
                                  l.level === "ERROR"
                                    ? "red"
                                    : l.level === "WARNING"
                                      ? "orange"
                                      : "default"
                                }
                              >
                                {l.stage}
                              </Tag>
                              <Text style={{ fontSize: 12 }}>{l.message}</Text>
                              {l.elapsed_ms != null && (
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {fmtMs(l.elapsed_ms)}
                                </Text>
                              )}
                            </Space>
                          </List.Item>
                        )}
                      />
                    </div>
                  )}
                </Space>
              )}
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}
