import { useEffect, useState } from "react";
import {
  Button,
  Card,
  DatePicker,
  Drawer,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  message,
} from "antd";
import { CloseCircleOutlined, EyeOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";

import { listBranches, type Branch } from "@/api/tenancy";
import {
  cancelOrder,
  getOrder,
  listOrders,
  type OrderDetail,
  type OrderStatus,
  type OrderSummary,
} from "@/api/sales";
import { useAuth } from "@/contexts/AuthContext";

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);
const PAGE_SIZE = 20;

const STATUS_COLOR: Record<OrderStatus, string> = {
  pending: "orange",
  paid: "green",
  cancelled: "red",
  refunded: "purple",
};

const STATUS_LABEL: Record<OrderStatus, string> = {
  pending: "Chờ",
  paid: "Đã thanh toán",
  cancelled: "Đã hủy",
  refunded: "Hoàn tiền",
};

export default function OrdersPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<OrderSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchFilter, setBranchFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<OrderStatus | undefined>();
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);

  const [detail, setDetail] = useState<OrderDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [cancelling, setCancelling] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await listOrders({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        branch_id: branchFilter,
        status: statusFilter,
        date_from: dateRange?.[0]?.startOf("day").toISOString(),
        date_to: dateRange?.[1]?.endOf("day").toISOString(),
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được đơn hàng");
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
  }, [page, branchFilter, statusFilter, dateRange]);

  const openDetail = async (row: OrderSummary) => {
    setDetailLoading(true);
    try {
      const d = await getOrder(row.id);
      setDetail(d);
    } catch {
      message.error("Không tải được chi tiết đơn");
    } finally {
      setDetailLoading(false);
    }
  };

  const onCancel = async () => {
    if (!detail) return;
    setCancelling(true);
    try {
      const updated = await cancelOrder(detail.id);
      setDetail(updated);
      message.success("Đã hủy đơn và hoàn kho");
      load();
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      message.error(typeof d === "string" ? d : "Hủy thất bại");
    } finally {
      setCancelling(false);
    }
  };

  const columns: ColumnsType<OrderSummary> = [
    { title: "Mã đơn", dataIndex: "code", width: 180 },
    { title: "Chi nhánh", dataIndex: "branch_name", width: 200 },
    {
      title: "Trạng thái",
      dataIndex: "status",
      width: 140,
      render: (v: OrderStatus) => (
        <Tag color={STATUS_COLOR[v]}>{STATUS_LABEL[v]}</Tag>
      ),
    },
    {
      title: "Tổng",
      dataIndex: "total_amount",
      width: 160,
      align: "right",
      render: (v: string, r) =>
        `${Number(v).toLocaleString()} ${r.currency}`,
    },
    {
      title: "Tạo lúc",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: "",
      width: 60,
      fixed: "right",
      render: (_, row) => (
        <Button
          size="small"
          icon={<EyeOutlined />}
          onClick={() => openDetail(row)}
        />
      ),
    },
  ];

  return (
    <Card
      title="Đơn hàng"
      extra={
        <Space>
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
            allowClear
            placeholder="Trạng thái"
            style={{ width: 160 }}
            value={statusFilter}
            onChange={(v) => {
              setPage(1);
              setStatusFilter(v);
            }}
            options={(
              ["pending", "paid", "cancelled", "refunded"] as OrderStatus[]
            ).map((s) => ({ value: s, label: STATUS_LABEL[s] }))}
          />
          <DatePicker.RangePicker
            value={dateRange ?? undefined}
            onChange={(v) => {
              setPage(1);
              setDateRange(v as [Dayjs, Dayjs] | null);
            }}
          />
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
        title={detail ? `Đơn ${detail.code}` : "Chi tiết đơn"}
        open={!!detail}
        onClose={() => setDetail(null)}
        width={680}
        loading={detailLoading}
        extra={
          detail &&
          canEdit &&
          detail.status !== "cancelled" &&
          detail.status !== "refunded" && (
            <Popconfirm
              title="Hủy đơn và hoàn kho?"
              onConfirm={onCancel}
              okButtonProps={{ loading: cancelling }}
            >
              <Button danger icon={<CloseCircleOutlined />}>
                Hủy đơn
              </Button>
            </Popconfirm>
          )
        }
      >
        {detail && (
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <div>
              Trạng thái:{" "}
              <Tag color={STATUS_COLOR[detail.status]}>
                {STATUS_LABEL[detail.status]}
              </Tag>
            </div>
            <div>
              Tổng:{" "}
              <strong>
                {Number(detail.total_amount).toLocaleString()} {detail.currency}
              </strong>
            </div>
            {detail.paid_at && (
              <div>
                Thanh toán: {new Date(detail.paid_at).toLocaleString()}
              </div>
            )}
            {detail.notes && <div>Ghi chú: {detail.notes}</div>}
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={detail.items}
              columns={[
                {
                  title: "Sản phẩm",
                  dataIndex: "product_id",
                  ellipsis: true,
                },
                { title: "SL", dataIndex: "quantity", width: 70, align: "right" },
                {
                  title: "Đơn giá",
                  dataIndex: "unit_price",
                  width: 120,
                  align: "right",
                  render: (v: string) => Number(v).toLocaleString(),
                },
                {
                  title: "Giảm",
                  dataIndex: "discount_amount",
                  width: 100,
                  align: "right",
                  render: (v: string) => Number(v).toLocaleString(),
                },
                {
                  title: "Thành tiền",
                  dataIndex: "subtotal",
                  width: 130,
                  align: "right",
                  render: (v: string) => Number(v).toLocaleString(),
                },
              ]}
            />
          </Space>
        )}
      </Drawer>
    </Card>
  );
}
