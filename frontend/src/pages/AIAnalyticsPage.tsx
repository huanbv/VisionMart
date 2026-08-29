import { useEffect, useMemo, useState } from "react";
import {
  Card,
  Col,
  DatePicker,
  Empty,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";

import { listCameras, type Camera } from "@/api/cameras";
import {
  getDetectionStats,
  type DetectionCameraCount,
  type DetectionClassCount,
  type DetectionSeriesPoint,
  type DetectionStatsResponse,
} from "@/api/detections";

function SeriesChart({ points }: { points: DetectionSeriesPoint[] }) {
  if (points.length === 0) return <Empty description="Chưa có dữ liệu" />;
  const width = 720;
  const height = 200;
  const padding = { top: 12, right: 12, bottom: 28, left: 40 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const max = Math.max(1, ...points.map((p) => p.detections));
  const barW = innerW / points.length;
  const labelEvery = Math.ceil(points.length / 12);
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img">
      <line
        x1={padding.left}
        y1={padding.top + innerH}
        x2={padding.left + innerW}
        y2={padding.top + innerH}
        stroke="#d9d9d9"
      />
      {points.map((p, i) => {
        const h = (p.detections / max) * innerH;
        const x = padding.left + i * barW + barW * 0.15;
        const y = padding.top + (innerH - h);
        const w = barW * 0.7;
        const show = i % labelEvery === 0 || i === points.length - 1;
        const label = p.date.slice(5);
        return (
          <g key={p.date}>
            <title>{`${p.date}\n${p.events} events • ${p.detections} objects`}</title>
            <rect x={x} y={y} width={w} height={h} fill="#722ed1" rx={2} />
            {show && (
              <text
                x={x + w / 2}
                y={padding.top + innerH + 16}
                fontSize={10}
                textAnchor="middle"
                fill="#666"
              >
                {label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function HorizontalBars({
  data,
  color,
  labelKey,
  valueKey,
}: {
  data: Array<Record<string, number | string>>;
  color: string;
  labelKey: string;
  valueKey: string;
}) {
  if (data.length === 0) return <Empty description="Chưa có dữ liệu" />;
  const max = Math.max(1, ...data.map((d) => Number(d[valueKey])));
  return (
    <Space direction="vertical" style={{ width: "100%" }} size={6}>
      {data.map((d, i) => {
        const v = Number(d[valueKey]);
        const w = (v / max) * 100;
        return (
          <div key={i}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 12 }}>{String(d[labelKey])}</span>
              <span style={{ fontSize: 12, color: "#888" }}>{v}</span>
            </div>
            <div
              style={{
                height: 10,
                background: "#f0f0f0",
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${w}%`,
                  height: "100%",
                  background: color,
                }}
              />
            </div>
          </div>
        );
      })}
    </Space>
  );
}

export default function AIAnalyticsPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [stats, setStats] = useState<DetectionStatsResponse | null>(null);
  const [loading, setLoading] = useState(false);

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

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const res = await getDetectionStats({
          camera_id: cameraId,
          date_from: dateRange?.[0]?.startOf("day").toISOString(),
          date_to: dateRange?.[1]?.endOf("day").toISOString(),
        });
        setStats(res);
      } catch {
        message.error("Không tải được thống kê");
      } finally {
        setLoading(false);
      }
    })();
  }, [cameraId, dateRange]);

  const cameraRows: ColumnsType<DetectionCameraCount> = [
    {
      title: "Camera",
      dataIndex: "camera_id",
      render: (v: string) => cameraMap.get(v) ?? v.slice(0, 8),
    },
    { title: "Events", dataIndex: "events", align: "right", width: 100 },
    {
      title: "Objects",
      dataIndex: "detections",
      align: "right",
      width: 100,
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card>
        <Space wrap>
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Camera"
            style={{ width: 240 }}
            value={cameraId}
            onChange={setCameraId}
            options={cameras.map((c) => ({ value: c.id, label: c.name }))}
          />
          <DatePicker.RangePicker
            value={dateRange ?? undefined}
            onChange={(v) => setDateRange(v as [Dayjs, Dayjs] | null)}
          />
        </Space>
      </Card>

      <Row gutter={16}>
        <Col span={8}>
          <Card loading={loading}>
            <Statistic
              title="Số lần phân tích"
              value={stats?.total_events ?? 0}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card loading={loading}>
            <Statistic
              title="Tổng số đối tượng"
              value={stats?.total_detections ?? 0}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card loading={loading}>
            <Statistic
              title="Confidence trung bình"
              suffix="%"
              precision={1}
              value={(stats?.avg_max_confidence ?? 0) * 100}
            />
          </Card>
        </Col>
      </Row>

      <Card title="Số lượng phát hiện theo ngày" loading={loading}>
        <SeriesChart points={stats?.series ?? []} />
      </Card>

      <Row gutter={16}>
        <Col span={12}>
          <Card
            title={
              <Space>
                <span>Nhóm đối tượng</span>
                <Tag color="purple">Top {stats?.top_classes.length ?? 0}</Tag>
              </Space>
            }
            loading={loading}
          >
            <HorizontalBars
              data={(stats?.top_classes ?? []).map(
                (c: DetectionClassCount) => ({
                  class_name: c.class_name,
                  count: c.count,
                }),
              )}
              color="#722ed1"
              labelKey="class_name"
              valueKey="count"
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="Camera hoạt động nhiều nhất" loading={loading}>
            <Table<DetectionCameraCount>
              rowKey="camera_id"
              size="small"
              pagination={false}
              columns={cameraRows}
              dataSource={stats?.top_cameras ?? []}
              locale={{ emptyText: "Chưa có dữ liệu" }}
            />
          </Card>
        </Col>
      </Row>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Số liệu tổng hợp từ bảng detection_events, cập nhật mỗi lần bạn thay
        đổi bộ lọc.
      </Typography.Text>
    </Space>
  );
}
