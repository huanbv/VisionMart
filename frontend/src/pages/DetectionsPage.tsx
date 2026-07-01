import { useEffect, useMemo, useState } from "react";
import {
  Card,
  DatePicker,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";

import { listCameras, type Camera } from "@/api/cameras";
import {
  getDetection,
  getDetectionImageBlob,
  listDetections,
  type DetectionEvent,
  type DetectionEventSummary,
} from "@/api/detections";

const PAGE_SIZE = 50;

export default function DetectionsPage() {
  const [data, setData] = useState<DetectionEventSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<string | undefined>();
  const [model, setModel] = useState<string | undefined>();
  const [minConfidence, setMinConfidence] = useState<number | null>(null);
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [detail, setDetail] = useState<DetectionEvent | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  const cameraMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of cameras) m.set(c.id, c.name);
    return m;
  }, [cameras]);

  useEffect(() => {
    void (async () => {
      try {
        const res = await listCameras({ limit: 200 });
        setCameras(res.items);
      } catch {
        // optional
      }
    })();
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const res = await listDetections({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        camera_id: cameraId,
        model: model || undefined,
        min_confidence: minConfidence ?? undefined,
        date_from: dateRange?.[0]?.startOf("day").toISOString(),
        date_to: dateRange?.[1]?.endOf("day").toISOString(),
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được danh sách phát hiện");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, cameraId, model, minConfidence, dateRange]);

  const openDetail = async (id: string) => {
    setDetailLoading(true);
    try {
      const ev = await getDetection(id);
      setDetail(ev);
      if (ev.image_key) {
        try {
          const blob = await getDetectionImageBlob(ev.id);
          setImageUrl(URL.createObjectURL(blob));
        } catch {
          setImageUrl(null);
        }
      } else {
        setImageUrl(null);
      }
    } catch {
      message.error("Không tải được chi tiết");
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    setImageUrl(null);
    setDetail(null);
  };

  useEffect(() => {
    return () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [imageUrl]);

  const columns: ColumnsType<DetectionEventSummary> = [
    {
      title: "Thời điểm",
      dataIndex: "created_at",
      width: 180,
      render: (v: string) => new Date(v).toLocaleString("vi-VN"),
    },
    {
      title: "Camera",
      dataIndex: "camera_id",
      width: 200,
      render: (v: string) => cameraMap.get(v) ?? v.slice(0, 8),
    },
    {
      title: "Model",
      dataIndex: "model",
      width: 140,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: "Số đối tượng",
      dataIndex: "detection_count",
      width: 120,
      align: "right",
    },
    {
      title: "Confidence cao nhất",
      dataIndex: "max_confidence",
      width: 160,
      align: "right",
      render: (v: number) => `${(v * 100).toFixed(1)}%`,
    },
    {
      title: "Ảnh",
      key: "image",
      width: 140,
      render: (_, row) => `${row.image_width}×${row.image_height}`,
    },
    {
      title: "Thời gian",
      dataIndex: "elapsed_ms",
      width: 100,
      align: "right",
      render: (v: number) => `${v} ms`,
    },
  ];

  return (
    <Card title="Phát hiện AI">
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="Camera"
          style={{ width: 220 }}
          value={cameraId}
          onChange={(v) => {
            setPage(1);
            setCameraId(v);
          }}
          options={cameras.map((c) => ({ value: c.id, label: c.name }))}
        />
        <Select
          allowClear
          placeholder="Model"
          style={{ width: 180 }}
          value={model}
          onChange={(v) => {
            setPage(1);
            setModel(v);
          }}
          options={[
            { value: "yolov8n.pt", label: "yolov8n" },
            { value: "stub-v0", label: "stub-v0" },
          ]}
        />
        <InputNumber
          placeholder="Confidence ≥"
          min={0}
          max={1}
          step={0.05}
          value={minConfidence}
          onChange={(v) => {
            setPage(1);
            setMinConfidence(typeof v === "number" ? v : null);
          }}
        />
        <DatePicker.RangePicker
          value={dateRange ?? undefined}
          onChange={(v) => {
            setPage(1);
            setDateRange(v as [Dayjs, Dayjs] | null);
          }}
        />
      </Space>

      <Table<DetectionEventSummary>
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        onRow={(row) => ({
          onClick: () => void openDetail(row.id),
          style: { cursor: "pointer" },
        })}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          onChange: (p) => setPage(p),
        }}
        scroll={{ x: 1100 }}
      />

      <Modal
        title="Chi tiết phát hiện"
        open={!!detail || detailLoading}
        onCancel={closeDetail}
        footer={null}
        width={820}
        confirmLoading={detailLoading}
      >
        {detail && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Typography.Paragraph>
              <strong>Camera:</strong>{" "}
              {cameraMap.get(detail.camera_id) ?? detail.camera_id}
              <br />
              <strong>Model:</strong> {detail.model} —{" "}
              {detail.image_width}×{detail.image_height} ({detail.image_format},{" "}
              {detail.image_size_bytes} B) — {detail.elapsed_ms} ms
              <br />
              <strong>Thời điểm:</strong>{" "}
              {new Date(detail.created_at).toLocaleString("vi-VN")}
            </Typography.Paragraph>
            {imageUrl && (
              <div
                style={{
                  position: "relative",
                  width: "100%",
                  maxWidth: 780,
                  aspectRatio: `${detail.image_width} / ${detail.image_height}`,
                  background: "#000",
                  overflow: "hidden",
                }}
              >
                <img
                  src={imageUrl}
                  alt="detection frame"
                  style={{
                    width: "100%",
                    height: "100%",
                    display: "block",
                    objectFit: "contain",
                  }}
                />
                {detail.detections.map((d, i) => {
                  const b = d.bbox;
                  if (!b) return null;
                  const left = (b.x1 / detail.image_width) * 100;
                  const top = (b.y1 / detail.image_height) * 100;
                  const width = ((b.x2 - b.x1) / detail.image_width) * 100;
                  const height = ((b.y2 - b.y1) / detail.image_height) * 100;
                  return (
                    <div
                      key={i}
                      style={{
                        position: "absolute",
                        left: `${left}%`,
                        top: `${top}%`,
                        width: `${width}%`,
                        height: `${height}%`,
                        border: "2px solid #52c41a",
                        boxSizing: "border-box",
                        pointerEvents: "none",
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
                          padding: "1px 4px",
                          borderRadius: 2,
                          whiteSpace: "nowrap",
                        }}
                      >
                        {d.class_name} {(d.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
            <Typography.Title level={5}>
              Detections ({detail.detections.length})
            </Typography.Title>
            <pre
              style={{
                margin: 0,
                padding: 12,
                background: "#fafafa",
                borderRadius: 4,
                fontSize: 12,
                maxHeight: 300,
                overflow: "auto",
              }}
            >
              {JSON.stringify(detail.detections, null, 2)}
            </pre>
          </Space>
        )}
      </Modal>
    </Card>
  );
}
