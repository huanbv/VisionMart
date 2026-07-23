import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Image,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadProps } from "antd";
import { CloudUploadOutlined, RightOutlined } from "@ant-design/icons";

import {
  getTraceStageImageBlob,
  listCameras,
  tracePipeline,
  type Camera,
  type PipelineTraceResult,
  type TraceStage,
} from "@/api/cameras";

const { Title, Paragraph, Text } = Typography;

/**
 * "See every preprocessing step" view.
 *
 * The existing camera pages answer *what the model detected*. This one
 * answers *what the model was given* — it renders the OpenCV chain
 * (decode → ROI → each enabled enhancement → final) with the image and the
 * measured brightness/contrast/sharpness after every stage, so an operator
 * can see which step actually changed the frame instead of only the end
 * result.
 */
export default function PipelineTracePage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<string | undefined>();
  const [trace, setTrace] = useState<PipelineTraceResult | null>(null);
  const [images, setImages] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCameras({ limit: 200 })
      .then((res) => {
        setCameras(res.items);
        if (res.items.length && !cameraId) setCameraId(res.items[0].id);
      })
      .catch(() => message.error("Không tải được danh sách camera"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Stage images need an authenticated fetch, so they arrive as blobs and
  // get turned into object URLs here. Revoked on unmount / new trace to
  // avoid leaking them.
  useEffect(() => {
    if (!trace || !cameraId) return;
    let cancelled = false;
    const created: string[] = [];

    (async () => {
      const next: Record<number, string> = {};
      for (const stage of trace.stages) {
        if (!stage.image_key) continue;
        try {
          const blob = await getTraceStageImageBlob(
            cameraId,
            trace.trace_id,
            stage.image_key,
          );
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          created.push(url);
          next[stage.order] = url;
        } catch {
          // A missing stage image shouldn't blank the whole view.
        }
      }
      if (!cancelled) setImages(next);
    })();

    return () => {
      cancelled = true;
      created.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [trace, cameraId]);

  const uploadProps: UploadProps = {
    accept: "image/*",
    showUploadList: false,
    beforeUpload: async (file) => {
      if (!cameraId) {
        message.warning("Chọn camera trước");
        return Upload.LIST_IGNORE;
      }
      setLoading(true);
      setError(null);
      setImages({});
      setTrace(null);
      try {
        const result = await tracePipeline(cameraId, file as File);
        setTrace(result);
        if (!result.stages.length) {
          message.info("Không có bước tiền xử lý nào đang bật.");
        }
      } catch (err: unknown) {
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? "Không chạy được pipeline trace";
        setError(detail);
      } finally {
        setLoading(false);
      }
      return Upload.LIST_IGNORE;
    },
  };

  /** Deltas vs. the previous stage — the "what did this step change" column. */
  const rows = useMemo(() => {
    if (!trace) return [];
    return trace.stages.map((s, i) => {
      const prev = i > 0 ? trace.stages[i - 1] : null;
      return {
        ...s,
        key: s.order,
        dBrightness: prev ? s.metrics.brightness - prev.metrics.brightness : null,
        dContrast: prev ? s.metrics.contrast - prev.metrics.contrast : null,
        dBlur: prev ? s.metrics.blur_score - prev.metrics.blur_score : null,
      };
    });
  }, [trace]);

  const delta = (v: number | null, digits = 1) => {
    if (v === null) return <Text type="secondary">—</Text>;
    if (Math.abs(v) < 0.05) return <Text type="secondary">≈0</Text>;
    return (
      <Text type={v > 0 ? "success" : "danger"}>
        {v > 0 ? "+" : ""}
        {v.toFixed(digits)}
      </Text>
    );
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          Pipeline xử lý ảnh — xem từng bước
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Tải lên một khung hình để xem toàn bộ chuỗi tiền xử lý OpenCV trước
          khi ảnh được đưa vào AI: đầu vào → ROI → từng bước tăng cường → ảnh
          cuối. Mỗi bước hiển thị ảnh, tham số và các chỉ số đo được.
        </Paragraph>
      </div>

      <Card>
        <Space wrap>
          <Select
            style={{ minWidth: 260 }}
            placeholder="Chọn camera"
            value={cameraId}
            onChange={setCameraId}
            options={cameras.map((c) => ({ label: c.name, value: c.id }))}
          />
          <Upload {...uploadProps}>
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              loading={loading}
              disabled={!cameraId}
            >
              {loading ? "Đang xử lý…" : "Tải khung hình"}
            </Button>
          </Upload>
        </Space>
      </Card>

      {error && (
        <Alert
          type="error"
          showIcon
          message="Không chạy được pipeline trace"
          description={error}
        />
      )}

      {trace && (
        <>
          <Card size="small">
            <Row gutter={16}>
              <Col xs={12} md={5}>
                <Statistic
                  title="Tổng thời gian OpenCV"
                  value={trace.opencv_ms}
                  suffix="ms"
                  precision={1}
                />
              </Col>
              <Col xs={12} md={5}>
                <Statistic title="Số bước" value={trace.stages.length} />
              </Col>
              {trace.quality && (
                <>
                  <Col xs={12} md={5}>
                    <Statistic
                      title="Điểm chất lượng"
                      value={trace.quality.quality_score}
                      precision={2}
                      suffix="/ 1.00"
                      valueStyle={{
                        color: trace.quality.is_low_quality ? "#cf1322" : "#3f8600",
                      }}
                    />
                  </Col>
                  <Col xs={12} md={9}>
                    <Space direction="vertical" size={2}>
                      <Text type="secondary">Trạng thái khung hình</Text>
                      <Space wrap>
                        <Tag color={trace.quality.is_blurry ? "red" : "green"}>
                          {trace.quality.is_blurry ? "Mờ" : "Đủ nét"}
                        </Tag>
                        <Tag color={trace.quality.is_low_quality ? "red" : "green"}>
                          {trace.quality.is_low_quality
                            ? "Chất lượng thấp"
                            : "Đạt ngưỡng"}
                        </Tag>
                        {trace.quality.reason && (
                          <Text type="secondary">{trace.quality.reason}</Text>
                        )}
                      </Space>
                    </Space>
                  </Col>
                </>
              )}
            </Row>
          </Card>

          {/* Chuỗi ảnh theo chiều ngang — nhìn là thấy ngay bước nào đổi gì */}
          <Card title="Chuỗi xử lý">
            {trace.stages.length === 0 ? (
              <Empty description="Không có bước tiền xử lý nào đang bật" />
            ) : (
              <div style={{ display: "flex", overflowX: "auto", gap: 8, paddingBottom: 8 }}>
                {trace.stages.map((s, i) => (
                  <div key={s.order} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Card
                      size="small"
                      style={{ width: 230, flex: "0 0 auto" }}
                      title={
                        <Space size={4}>
                          <Tag color={s.stage === "final" ? "green" : "blue"}>
                            {s.order}
                          </Tag>
                          <Text style={{ fontSize: 13 }}>{s.label}</Text>
                        </Space>
                      }
                    >
                      {images[s.order] ? (
                        <Image
                          src={images[s.order]}
                          alt={s.label}
                          style={{ width: "100%", objectFit: "contain" }}
                        />
                      ) : (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description="Đang tải…"
                        />
                      )}
                      <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
                        <Descriptions.Item label="Sáng">
                          {s.metrics.brightness.toFixed(1)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Tương phản">
                          {s.metrics.contrast.toFixed(1)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Độ nét">
                          {s.metrics.blur_score.toFixed(0)}
                        </Descriptions.Item>
                      </Descriptions>
                    </Card>
                    {i < trace.stages.length - 1 && (
                      <RightOutlined style={{ color: "#bbb" }} />
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="Chi tiết từng bước">
            <Table
              size="small"
              dataSource={rows}
              pagination={false}
              scroll={{ x: 900 }}
              columns={[
                { title: "#", dataIndex: "order", width: 50 },
                {
                  title: "Bước",
                  dataIndex: "label",
                  render: (v: string, r: TraceStage) => (
                    <Space direction="vertical" size={0}>
                      <Text strong>{v}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {r.stage}
                      </Text>
                    </Space>
                  ),
                },
                {
                  title: "Tham số",
                  dataIndex: "params",
                  render: (p: Record<string, unknown>) => {
                    const entries = Object.entries(p ?? {});
                    if (!entries.length) return <Text type="secondary">—</Text>;
                    return (
                      <Space wrap size={4}>
                        {entries.map(([k, v]) => (
                          <Tag key={k}>{`${k}=${String(v)}`}</Tag>
                        ))}
                      </Space>
                    );
                  },
                },
                {
                  title: "Sáng",
                  render: (_: unknown, r: (typeof rows)[number]) => (
                    <Space size={4}>
                      {r.metrics.brightness.toFixed(1)}
                      {delta(r.dBrightness)}
                    </Space>
                  ),
                },
                {
                  title: "Tương phản",
                  render: (_: unknown, r: (typeof rows)[number]) => (
                    <Space size={4}>
                      {r.metrics.contrast.toFixed(1)}
                      {delta(r.dContrast)}
                    </Space>
                  ),
                },
                {
                  title: "Độ nét",
                  render: (_: unknown, r: (typeof rows)[number]) => (
                    <Space size={4}>
                      {r.metrics.blur_score.toFixed(0)}
                      {delta(r.dBlur, 0)}
                    </Space>
                  ),
                },
                {
                  title: "Thời gian",
                  dataIndex: "elapsed_ms",
                  render: (v: number) => `${v.toFixed(1)} ms`,
                },
              ]}
            />
            <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              Cột chênh lệch cho biết mỗi bước thực sự thay đổi gì so với bước
              trước. Ví dụ bộ lọc song phương thường làm <Text code>Độ nét</Text>{" "}
              giảm (khử nhiễu), còn unsharp masking kéo chỉ số này tăng trở lại.
            </Paragraph>
          </Card>
        </>
      )}

      {!trace && !error && !loading && (
        <Card>
          <Empty description="Chọn camera và tải lên một khung hình để xem chuỗi xử lý" />
        </Card>
      )}
    </Space>
  );
}
