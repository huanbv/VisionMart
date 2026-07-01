import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Col,
  Empty,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  PlusOutlined,
  ShoppingCartOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { listBranches, type Branch } from "@/api/tenancy";
import { listProducts, type Product } from "@/api/catalog";
import { listCustomers, type Customer } from "@/api/customers";
import { createOrder, type OrderDetail } from "@/api/sales";
import { useAuth } from "@/contexts/AuthContext";

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);

interface Line {
  key: string;
  product_id: string;
  product_label: string;
  quantity: number;
  unit_price: number;
  discount_amount: number;
}

export default function PosPage() {
  const { user } = useAuth();
  const canSell = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [branches, setBranches] = useState<Branch[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [branchId, setBranchId] = useState<string | undefined>(undefined);
  const [customerId, setCustomerId] = useState<string | undefined>(undefined);
  const [pickProductId, setPickProductId] = useState<string | undefined>();
  const [lines, setLines] = useState<Line[]>([]);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [successOrder, setSuccessOrder] = useState<OrderDetail | null>(null);

  useEffect(() => {
    listBranches({ limit: 200 })
      .then((res) => {
        setBranches(res.items);
        if (res.items.length === 1) setBranchId(res.items[0].id);
      })
      .catch(() => message.error("Không tải được chi nhánh"));
    listProducts({ limit: 200, is_active: true })
      .then((res) => setProducts(res.items))
      .catch(() => message.error("Không tải được sản phẩm"));
    listCustomers({ limit: 500, is_active: true })
      .then((res) => setCustomers(res.items))
      .catch(() => message.error("Không tải được khách hàng"));
  }, []);

  const productMap = useMemo(() => {
    const m = new Map<string, Product>();
    products.forEach((p) => m.set(p.id, p));
    return m;
  }, [products]);

  const addLine = () => {
    if (!pickProductId) return;
    const product = productMap.get(pickProductId);
    if (!product) return;
    const existing = lines.find((l) => l.product_id === pickProductId);
    if (existing) {
      setLines((prev) =>
        prev.map((l) =>
          l.product_id === pickProductId
            ? { ...l, quantity: l.quantity + 1 }
            : l,
        ),
      );
    } else {
      setLines((prev) => [
        ...prev,
        {
          key: `${pickProductId}-${Date.now()}`,
          product_id: pickProductId,
          product_label: `${product.sku} — ${product.name}`,
          quantity: 1,
          unit_price: Number(product.unit_price),
          discount_amount: 0,
        },
      ]);
    }
    setPickProductId(undefined);
  };

  const updateLine = (key: string, patch: Partial<Line>) => {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  };

  const removeLine = (key: string) => {
    setLines((prev) => prev.filter((l) => l.key !== key));
  };

  const total = useMemo(
    () =>
      lines.reduce(
        (sum, l) => sum + Math.max(0, l.unit_price * l.quantity - l.discount_amount),
        0,
      ),
    [lines],
  );

  const checkout = async () => {
    if (!branchId) {
      message.error("Vui lòng chọn chi nhánh");
      return;
    }
    if (lines.length === 0) {
      message.error("Vui lòng thêm sản phẩm");
      return;
    }
    setSaving(true);
    try {
      const order = await createOrder({
        branch_id: branchId,
        customer_id: customerId ?? null,
        notes: notes || null,
        lines: lines.map((l) => ({
          product_id: l.product_id,
          quantity: l.quantity,
          unit_price: l.unit_price,
          discount_amount: l.discount_amount,
        })),
      });
      setSuccessOrder(order);
      setLines([]);
      setNotes("");
      setCustomerId(undefined);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      message.error(typeof detail === "string" ? detail : "Tạo đơn thất bại");
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<Line> = [
    { title: "Sản phẩm", dataIndex: "product_label" },
    {
      title: "SL",
      dataIndex: "quantity",
      width: 100,
      render: (_, line) => (
        <InputNumber
          min={1}
          value={line.quantity}
          onChange={(v) => updateLine(line.key, { quantity: Number(v ?? 1) })}
        />
      ),
    },
    {
      title: "Đơn giá",
      dataIndex: "unit_price",
      width: 140,
      render: (_, line) => (
        <InputNumber
          min={0}
          value={line.unit_price}
          onChange={(v) =>
            updateLine(line.key, { unit_price: Number(v ?? 0) })
          }
        />
      ),
    },
    {
      title: "Giảm giá",
      dataIndex: "discount_amount",
      width: 130,
      render: (_, line) => (
        <InputNumber
          min={0}
          value={line.discount_amount}
          onChange={(v) =>
            updateLine(line.key, { discount_amount: Number(v ?? 0) })
          }
        />
      ),
    },
    {
      title: "Thành tiền",
      width: 130,
      align: "right",
      render: (_, line) =>
        Math.max(
          0,
          line.unit_price * line.quantity - line.discount_amount,
        ).toLocaleString(),
    },
    {
      title: "",
      width: 50,
      render: (_, line) => (
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          onClick={() => removeLine(line.key)}
        />
      ),
    },
  ];

  if (!canSell) {
    return <Card title="Bán hàng">Bạn không có quyền tạo đơn hàng.</Card>;
  }

  return (
    <Row gutter={16}>
      <Col span={16}>
        <Card title="Giỏ hàng">
          <Space style={{ marginBottom: 16, width: "100%" }}>
            <Select
              showSearch
              placeholder="Chọn sản phẩm để thêm"
              optionFilterProp="label"
              style={{ width: 480 }}
              value={pickProductId}
              onChange={setPickProductId}
              options={products.map((p) => ({
                value: p.id,
                label: `${p.sku} — ${p.name} (${Number(p.unit_price).toLocaleString()} ${p.currency})`,
              }))}
            />
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={addLine}
              disabled={!pickProductId}
            >
              Thêm
            </Button>
          </Space>
          {lines.length === 0 ? (
            <Empty description="Chưa có sản phẩm" />
          ) : (
            <Table
              rowKey="key"
              dataSource={lines}
              columns={columns}
              pagination={false}
              size="small"
            />
          )}
        </Card>
      </Col>
      <Col span={8}>
        <Card title="Thanh toán">
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <div>
              <div style={{ marginBottom: 4 }}>Chi nhánh</div>
              <Select
                style={{ width: "100%" }}
                placeholder="Chọn chi nhánh"
                value={branchId}
                onChange={setBranchId}
                options={branches.map((b) => ({
                  value: b.id,
                  label: `${b.code} — ${b.name}`,
                }))}
              />
            </div>
            <div>
              <div style={{ marginBottom: 4 }}>Khách hàng</div>
              <Select
                showSearch
                allowClear
                optionFilterProp="label"
                placeholder="Khách vãng lai"
                style={{ width: "100%" }}
                value={customerId}
                onChange={setCustomerId}
                options={customers.map((c) => ({
                  value: c.id,
                  label:
                    `${c.full_name ?? ""} ${c.phone ? `(${c.phone})` : c.email ?? ""}`.trim() ||
                    c.id,
                }))}
              />
            </div>
            <div>
              <div style={{ marginBottom: 4 }}>Ghi chú</div>
              <Input.TextArea
                rows={3}
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
            <Typography.Title level={3} style={{ textAlign: "right", margin: 0 }}>
              {total.toLocaleString()} VND
            </Typography.Title>
            <Button
              type="primary"
              size="large"
              icon={<ShoppingCartOutlined />}
              block
              loading={saving}
              onClick={checkout}
            >
              Tạo đơn hàng
            </Button>
          </Space>
        </Card>
      </Col>

      <Modal
        open={!!successOrder}
        title="Tạo đơn thành công"
        onCancel={() => setSuccessOrder(null)}
        footer={[
          <Button key="ok" type="primary" onClick={() => setSuccessOrder(null)}>
            OK
          </Button>,
        ]}
      >
        {successOrder && (
          <Space direction="vertical">
            <div>
              Mã đơn: <Tag color="blue">{successOrder.code}</Tag>
            </div>
            <div>
              Tổng:{" "}
              <strong>
                {Number(successOrder.total_amount).toLocaleString()}{" "}
                {successOrder.currency}
              </strong>
            </div>
            <div>Đã trừ kho và đánh dấu PAID.</div>
          </Space>
        )}
      </Modal>
    </Row>
  );
}
