import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Empty,
  List,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  ReloadOutlined,
  ShoppingCartOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { isAxiosError } from "axios";

import {
  type Cart,
  type CartStatus,
  abandonCart,
  checkoutCart,
  listCarts,
  removeCartLine,
} from "@/api/carts";
import { type Branch, listBranches } from "@/api/tenancy";
import { tokenStore } from "@/api/client";

const REFRESH_MS = 30_000;

const STATUS_COLOR: Record<CartStatus, string> = {
  active: "green",
  abandoned: "default",
  converted: "blue",
};

const SOURCE_LABEL: Record<string, string> = {
  ai_vision: "AI Camera",
  manual: "Thủ công",
  mobile_app: "Mobile",
};

function formatMoney(amount: string, currency: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return `${amount} ${currency}`;
  try {
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: currency || "VND",
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value.toLocaleString("vi-VN")} ${currency}`;
  }
}

export default function LiveCartPage() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchId] = useState<string | undefined>();
  const [carts, setCarts] = useState<Cart[]>([]);
  const [loading, setLoading] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await listBranches({ skip: 0, limit: 200 });
        setBranches(res.items);
        if (res.items.length && !branchId) setBranchId(res.items[0].id);
      } catch {
        message.error("Không tải được danh sách chi nhánh");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async () => {
    if (!branchId) return;
    setLoading(true);
    try {
      const res = await listCarts({ branch_id: branchId, status: "active", limit: 100 });
      setCarts(res.items);
    } catch {
      message.error("Không tải được danh sách giỏ hàng");
    } finally {
      setLoading(false);
    }
  }, [branchId]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (!branchId) return;
    let ws: WebSocket | null = null;
    let retry: number | null = null;
    let cancelled = false;

    const connect = () => {
      const token = tokenStore.getAccess();
      if (!token || cancelled) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const url = `${proto}://${window.location.host}/ws/carts?token=${encodeURIComponent(token)}&branch_id=${branchId}`;
      try {
        ws = new WebSocket(url);
      } catch {
        return;
      }
      ws.onopen = () => setWsConnected(true);
      ws.onmessage = () => {
        load();
      };
      ws.onclose = () => {
        setWsConnected(false);
        if (cancelled) return;
        retry = window.setTimeout(connect, 5_000);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      cancelled = true;
      setWsConnected(false);
      if (retry) window.clearTimeout(retry);
      ws?.close();
    };
  }, [branchId, load]);

  const totalRevenuePending = useMemo(
    () =>
      carts.reduce((sum, c) => sum + Number(c.total_amount || 0), 0),
    [carts],
  );

  const onCheckout = async (cart: Cart) => {
    try {
      const res = await checkoutCart(cart.id);
      message.success(`Đã tạo đơn ${res.order_code}`);
      load();
    } catch (err) {
      const detail =
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không thể checkout";
      message.error(detail);
    }
  };

  const onAbandon = async (cart: Cart) => {
    try {
      await abandonCart(cart.id);
      message.success("Đã hủy giỏ hàng");
      load();
    } catch {
      message.error("Không thể hủy giỏ hàng");
    }
  };

  const onRemoveLine = async (cart: Cart, lineId: string) => {
    try {
      await removeCartLine(cart.id, lineId);
      load();
    } catch {
      message.error("Không xóa được sản phẩm");
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card>
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Space size="large" wrap>
              <Space>
                <Typography.Text strong>Chi nhánh:</Typography.Text>
                <Select
                  style={{ minWidth: 240 }}
                  placeholder="Chọn chi nhánh"
                  value={branchId}
                  onChange={setBranchId}
                  options={branches.map((b) => ({
                    label: `${b.code} — ${b.name}`,
                    value: b.id,
                  }))}
                />
              </Space>
              <Badge
                status={wsConnected ? "success" : "default"}
                text={wsConnected ? "Realtime đang bật" : "Realtime tắt"}
              />
            </Space>
          </Col>
          <Col>
            <Button
              icon={<ReloadOutlined />}
              onClick={load}
              loading={loading}
            >
              Làm mới
            </Button>
          </Col>
        </Row>
      </Card>

      <Row gutter={16}>
        <Col span={8}>
          <Card>
            <Statistic
              title="Giỏ hàng đang mở"
              value={carts.length}
              prefix={<ShoppingCartOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Tổng giá trị chờ thanh toán"
              value={totalRevenuePending}
              precision={0}
              suffix="VND"
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Tổng sản phẩm"
              value={carts.reduce((s, c) => s + c.lines.length, 0)}
            />
          </Card>
        </Col>
      </Row>

      {carts.length === 0 ? (
        <Card>
          <Empty description="Chưa có giỏ hàng nào đang mở tại chi nhánh này" />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {carts.map((cart) => (
            <Col span={12} key={cart.id}>
              <Card
                title={
                  <Space>
                    <Tag color={STATUS_COLOR[cart.status]}>
                      {cart.status.toUpperCase()}
                    </Tag>
                    <Tag color={cart.source === "ai_vision" ? "purple" : "geekblue"}>
                      {SOURCE_LABEL[cart.source] ?? cart.source}
                    </Tag>
                    <Typography.Text code>
                      {cart.session_id ?? cart.id.slice(0, 8)}
                    </Typography.Text>
                  </Space>
                }
                extra={
                  <Space>
                    <Button
                      type="primary"
                      onClick={() => onCheckout(cart)}
                      disabled={cart.lines.length === 0}
                    >
                      Checkout
                    </Button>
                    <Popconfirm
                      title="Hủy giỏ hàng này?"
                      onConfirm={() => onAbandon(cart)}
                    >
                      <Button danger>Hủy</Button>
                    </Popconfirm>
                  </Space>
                }
              >
                <List
                  size="small"
                  dataSource={cart.lines}
                  locale={{ emptyText: "Chưa có sản phẩm" }}
                  renderItem={(line) => (
                    <List.Item
                      actions={[
                        <Tooltip key="del" title="Xóa dòng">
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={() => onRemoveLine(cart, line.line_id)}
                          />
                        </Tooltip>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space>
                            <Typography.Text strong>{line.product_name}</Typography.Text>
                            <Tag>{line.sku}</Tag>
                            {line.added_via === "ai" && (
                              <Tag color="purple">AI</Tag>
                            )}
                          </Space>
                        }
                        description={
                          <Space split="•">
                            <span>SL: {line.quantity}</span>
                            <span>
                              Đơn giá: {formatMoney(line.unit_price, cart.currency)}
                            </span>
                            <span>
                              Thành tiền: {formatMoney(line.subtotal, cart.currency)}
                            </span>
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
                <div style={{ textAlign: "right", marginTop: 12 }}>
                  <Typography.Text strong>
                    Tổng: {formatMoney(cart.total_amount, cart.currency)}
                  </Typography.Text>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Alert
        type="info"
        showIcon
        message="Cách hoạt động"
        description={
          <>
            AI Engine gửi sự kiện <code>product_picked_up</code>, <code>product_returned</code>,{" "}
            <code>checkout_initiated</code> tới{" "}
            <code>POST /api/v1/ai/cart-events</code>. Backend tự tạo/mở giỏ theo{" "}
            <code>track_id</code> và cập nhật realtime qua WebSocket{" "}
            <code>/ws/carts</code>. Có thể test bằng{" "}
            <code>POST http://ai-engine:8100/cart/simulate</code>.
          </>
        }
      />
    </Space>
  );
}
