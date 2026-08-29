import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Badge,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  AppstoreOutlined,
  ContactsOutlined,
  DollarOutlined,
  ShoppingCartOutlined,
  TeamOutlined,
  VideoCameraOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { listBranches, type Branch } from "@/api/tenancy";
import { listCameras, type Camera } from "@/api/cameras";
import {
  listDetections,
  type DetectionEventSummary,
} from "@/api/detections";
import {
  type DashboardSummary,
  type LowStockItem,
  type RecentOrder,
  type SalesTrendPoint,
  type TopProduct,
  getDashboardSummary,
  getLowStockItems,
  getRecentOrders,
  getSalesTrend,
  getTopProducts,
} from "@/api/dashboard";

const fmtVnd = (v: string | number) =>
  `${Number(v).toLocaleString("vi-VN")} ₫`;

function SalesTrendChart({ points }: { points: SalesTrendPoint[] }) {
  if (points.length === 0) {
    return <Empty description="Chưa có đơn hàng" />;
  }
  const width = 720;
  const height = 200;
  const padding = { top: 12, right: 12, bottom: 28, left: 56 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const max = Math.max(1, ...points.map((p) => Number(p.revenue)));
  const barW = innerW / points.length;
  const labelEvery = Math.ceil(points.length / 10);
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
        const rev = Number(p.revenue);
        const h = (rev / max) * innerH;
        const x = padding.left + i * barW + barW * 0.15;
        const y = padding.top + (innerH - h);
        const w = barW * 0.7;
        const dateLabel = p.date.slice(5);
        const showLabel = i % labelEvery === 0 || i === points.length - 1;
        return (
          <g key={p.date}>
            <title>{`${p.date}\n${p.orders} đơn — ${fmtVnd(rev)}`}</title>
            <rect x={x} y={y} width={w} height={h} fill="#1677ff" rx={2} />
            {showLabel && (
              <text
                x={x + w / 2}
                y={padding.top + innerH + 16}
                fontSize={10}
                textAnchor="middle"
                fill="#666"
              >
                {dateLabel}
              </text>
            )}
          </g>
        );
      })}
      <text x={4} y={padding.top + 10} fontSize={10} fill="#666">
        {fmtVnd(max)}
      </text>
      <text x={4} y={padding.top + innerH} fontSize={10} fill="#666">
        0
      </text>
    </svg>
  );
}

const STATUS_COLOR: Record<string, string> = {
  paid: "green",
  pending: "blue",
  cancelled: "default",
  refunded: "orange",
};

export default function DashboardPage() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchId] = useState<string | undefined>();
  const [trendDays, setTrendDays] = useState(14);

  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [trend, setTrend] = useState<SalesTrendPoint[]>([]);
  const [top, setTop] = useState<TopProduct[]>([]);
  const [low, setLow] = useState<LowStockItem[]>([]);
  const [recent, setRecent] = useState<RecentOrder[]>([]);
  const [alerts, setAlerts] = useState<DetectionEventSummary[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(false);

  const cameraMap = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of cameras) m.set(c.id, c.name);
    return m;
  }, [cameras]);

  useEffect(() => {
    listBranches({ limit: 200 })
      .then((res) => setBranches(res.items))
      .catch(() => message.error("Không tải được chi nhánh"));
    listCameras({ limit: 200 })
      .then((res) => setCameras(res.items))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [s, tr, tp, ls, ro, al] = await Promise.all([
          getDashboardSummary(branchId),
          getSalesTrend(trendDays, branchId),
          getTopProducts(30, 10, branchId),
          getLowStockItems(10, branchId),
          getRecentOrders(10, branchId),
          listDetections({ limit: 5 }),
        ]);
        setSummary(s);
        setTrend(tr.points);
        setTop(tp.items);
        setLow(ls.items);
        setRecent(ro.items);
        setAlerts(al.items);
      } catch {
        message.error("Không tải được dashboard");
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [branchId, trendDays]);

  const topColumns: ColumnsType<TopProduct> = useMemo(
    () => [
      { title: "SKU", dataIndex: "sku", width: 110 },
      { title: "Sản phẩm", dataIndex: "name" },
      { title: "SL bán", dataIndex: "quantity", width: 90, align: "right" },
      {
        title: "Doanh thu",
        dataIndex: "revenue",
        width: 140,
        align: "right",
        render: (v: string) => fmtVnd(v),
      },
    ],
    [],
  );

  const lowColumns: ColumnsType<LowStockItem> = useMemo(
    () => [
      { title: "SKU", dataIndex: "sku", width: 110 },
      { title: "Sản phẩm", dataIndex: "product_name" },
      { title: "Chi nhánh", dataIndex: "branch_name", width: 160 },
      {
        title: "Tồn / Ngưỡng",
        width: 200,
        render: (_, row) => {
          const pct = row.reorder_level
            ? Math.min(100, (row.quantity / row.reorder_level) * 100)
            : 0;
          return (
            <Tooltip
              title={`Khả dụng ${row.quantity - row.reserved_quantity} / Tồn ${row.quantity} / Ngưỡng ${row.reorder_level}`}
            >
              <Progress
                percent={pct}
                size="small"
                status={row.quantity === 0 ? "exception" : "active"}
                format={() => `${row.quantity}/${row.reorder_level}`}
              />
            </Tooltip>
          );
        },
      },
    ],
    [],
  );

  const recentColumns: ColumnsType<RecentOrder> = useMemo(
    () => [
      { title: "Mã đơn", dataIndex: "code", width: 160 },
      { title: "Chi nhánh", dataIndex: "branch_name", width: 160 },
      {
        title: "Trạng thái",
        dataIndex: "status",
        width: 110,
        render: (v: string) => (
          <Tag color={STATUS_COLOR[v] ?? "default"}>{v.toUpperCase()}</Tag>
        ),
      },
      {
        title: "Tổng tiền",
        dataIndex: "total_amount",
        width: 140,
        align: "right",
        render: (v: string) => fmtVnd(v),
      },
      {
        title: "Tạo lúc",
        dataIndex: "created_at",
        width: 170,
        render: (v: string) => new Date(v).toLocaleString("vi-VN"),
      },
    ],
    [],
  );

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Card>
        <Space wrap>
          <Typography.Text strong>Bộ lọc:</Typography.Text>
          <Select
            allowClear
            placeholder="Tất cả chi nhánh"
            style={{ width: 240 }}
            value={branchId}
            onChange={setBranchId}
            options={branches.map((b) => ({
              value: b.id,
              label: `${b.code} — ${b.name}`,
            }))}
          />
          <Select
            value={trendDays}
            onChange={setTrendDays}
            style={{ width: 140 }}
            options={[
              { value: 7, label: "7 ngày" },
              { value: 14, label: "14 ngày" },
              { value: 30, label: "30 ngày" },
              { value: 60, label: "60 ngày" },
              { value: 90, label: "90 ngày" },
            ]}
          />
        </Space>
      </Card>

      <Row gutter={16}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Doanh thu hôm nay"
              prefix={<DollarOutlined />}
              value={Number(summary?.today.revenue ?? 0)}
              formatter={(v) => fmtVnd(v as number)}
            />
            <Typography.Text type="secondary">
              {summary?.today.orders ?? 0} đơn
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Doanh thu 7 ngày"
              prefix={<ShoppingCartOutlined />}
              value={Number(summary?.last_7_days.revenue ?? 0)}
              formatter={(v) => fmtVnd(v as number)}
            />
            <Typography.Text type="secondary">
              {summary?.last_7_days.orders ?? 0} đơn
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Doanh thu 30 ngày"
              prefix={<ShoppingCartOutlined />}
              value={Number(summary?.last_30_days.revenue ?? 0)}
              formatter={(v) => fmtVnd(v as number)}
            />
            <Typography.Text type="secondary">
              {summary?.last_30_days.orders ?? 0} đơn
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Cảnh báo tồn kho"
              prefix={<WarningOutlined />}
              value={summary?.low_stock_count ?? 0}
              valueStyle={{
                color:
                  (summary?.low_stock_count ?? 0) > 0 ? "#cf1322" : undefined,
              }}
            />
            <Typography.Text type="secondary">SKU dưới ngưỡng</Typography.Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Khách hàng"
              prefix={<ContactsOutlined />}
              value={summary?.customers_total ?? 0}
            />
            <Typography.Text type="secondary">
              +{summary?.customers_new_7d ?? 0} trong 7 ngày
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Sản phẩm"
              prefix={<AppstoreOutlined />}
              value={summary?.products_total ?? 0}
            />
            <Typography.Text type="secondary">
              {summary?.branches_count ?? 0} chi nhánh
            </Typography.Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="Nhân viên active"
              prefix={<TeamOutlined />}
              value={summary?.employees_active ?? 0}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Space direction="vertical" size={4} style={{ width: "100%" }}>
              <Typography.Text type="secondary">Camera</Typography.Text>
              <Space size="large">
                <Statistic
                  title="Tổng"
                  value={summary?.cameras.total ?? 0}
                  prefix={<VideoCameraOutlined />}
                  valueStyle={{ fontSize: 20 }}
                />
                <Statistic
                  title="Online"
                  value={summary?.cameras.online ?? 0}
                  valueStyle={{ fontSize: 20, color: "#52c41a" }}
                />
              </Space>
              <Badge
                status={
                  (summary?.cameras.online ?? 0) ===
                  (summary?.cameras.active ?? 0)
                    ? "success"
                    : "warning"
                }
                text={`${summary?.cameras.active ?? 0} active`}
              />
            </Space>
          </Card>
        </Col>
      </Row>

      <Card title={`Doanh thu ${trendDays} ngày gần nhất`} loading={loading}>
        <SalesTrendChart points={trend} />
      </Card>

      <Row gutter={16}>
        <Col xs={24} lg={12}>
          <Card title="Top sản phẩm bán chạy (30 ngày)" loading={loading}>
            <Table
              rowKey="product_id"
              dataSource={top}
              columns={topColumns}
              pagination={false}
              size="small"
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="Tồn kho dưới ngưỡng" loading={loading}>
            <Table
              rowKey="inventory_id"
              dataSource={low}
              columns={lowColumns}
              pagination={false}
              size="small"
              locale={{ emptyText: "Không có cảnh báo" }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <Card title="Đơn hàng gần nhất" loading={loading}>
            <Table
              rowKey="id"
              dataSource={recent}
              columns={recentColumns}
              pagination={false}
              size="small"
            />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card
            title="Cảnh báo AI gần đây"
            loading={loading}
            extra={<Link to="/detections">Xem tất cả</Link>}
          >
            {alerts.length === 0 ? (
              <Empty description="Chưa có phát hiện" />
            ) : (
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                {alerts.map((a) => {
                  const confPct = Math.round(a.max_confidence * 100);
                  const color =
                    confPct >= 80 ? "red" : confPct >= 60 ? "orange" : "blue";
                  return (
                    <Link
                      key={a.id}
                      to="/detections"
                      style={{ color: "inherit" }}
                    >
                      <Space
                        style={{ width: "100%", justifyContent: "space-between" }}
                        wrap
                      >
                        <Space direction="vertical" size={0}>
                          <Typography.Text strong>
                            <VideoCameraOutlined />{" "}
                            {cameraMap.get(a.camera_id) ?? a.camera_id.slice(0, 8)}
                          </Typography.Text>
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {new Date(a.created_at).toLocaleString("vi-VN")} —{" "}
                            {a.detection_count} đối tượng
                          </Typography.Text>
                        </Space>
                        <Tag color={color}>{confPct}%</Tag>
                      </Space>
                    </Link>
                  );
                })}
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
