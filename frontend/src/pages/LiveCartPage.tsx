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
  QrcodeOutlined,
  ReloadOutlined,
  ShoppingCartOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { isAxiosError } from "axios";

import {
  type Cart,
  type CartCheckoutQrResponse,
  type CartStatus,
  abandonCart,
  cancelCheckout,
  checkoutCart,
  confirmCheckoutStaff,
  getCheckoutQr,
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
  pending_checkout: "orange",
};

const STATUS_LABEL: Record<CartStatus, string> = {
  active: "ACTIVE",
  abandoned: "ABANDONED",
  converted: "CONVERTED",
  pending_checkout: "CHỜ KHÁCH XÁC NHẬN",
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
  const [qrByCart, setQrByCart] = useState<Record<string, CartCheckoutQrResponse>>({});

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
      // "Live" view = anything still in play: shopping (active) or frozen
      // waiting on a customer/staff checkout confirmation (pending_checkout).
      const [activeRes, pendingRes] = await Promise.all([
        listCarts({ branch_id: branchId, status: "active", limit: 100 }),
        listCarts({ branch_id: branchId, status: "pending_checkout", limit: 100 }),
      ]);
      setCarts([...pendingRes.items, ...activeRes.items]);
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

  const onShowQr = async (cart: Cart) => {
    try {
      const qr = await getCheckoutQr(cart.id);
      setQrByCart((prev) => ({ ...prev, [cart.id]: qr }));
    } catch {
      message.error("Không tải được mã QR xác nhận");
    }
  };

  const onConfirmStaff = async (cart: Cart) => {
    try {
      const res = await confirmCheckoutStaff(cart.id);
      message.success(`Đã xác nhận hộ khách — đơn ${res.order_code}`);
      setQrByCart((prev) => {
        const next = { ...prev };
        delete next[cart.id];
        return next;
      });
      load();
    } catch (err) {
      const detail =
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không thể xác nhận thanh toán";
      message.error(detail);
    }
  };

  const onCancelCheckout = async (cart: Cart) => {
    try {
      await cancelCheckout(cart.id);
      setQrByCart((prev) => {
        const next = { ...prev };
        delete next[cart.id];
        return next;
      });
      message.info("Đã huỷ, khách tiếp tục mua sắm");
      load();
    } catch {
      message.error("Không thể huỷ chờ xác nhận");
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
                      {STATUS_LABEL[cart.status]}
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
                  cart.status === "pending_checkout" ? (
                    <Space>
                      <Button icon={<QrcodeOutlined />} onClick={() => onShowQr(cart)}>
                        Hiện QR
                      </Button>
                      <Popconfirm
                        title="Xác nhận hộ khách (không có QR)?"
                        onConfirm={() => onConfirmStaff(cart)}
                      >
                        <Button type="primary">Xác nhận hộ</Button>
                      </Popconfirm>
                      <Tooltip title="Huỷ chờ xác nhận, khách tiếp tục mua sắm">
                        <Button
                          danger
                          icon={<StopOutlined />}
                          onClick={() => onCancelCheckout(cart)}
                        />
                      </Tooltip>
                    </Space>
                  ) : (
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
                  )
                }
              >
                {cart.status === "pending_checkout" && cart.overall_confidence < 0.75 && (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type="error"
                    showIcon
                    message={`Độ tin cậy AI thấp (${Math.round(cart.overall_confidence * 100)}%)`}
                    description="Nên kiểm tra lại từng sản phẩm trước khi xác nhận hộ khách — AI có thể đã nhận diện sai."
                  />
                )}
                {cart.status === "pending_checkout" && qrByCart[cart.id] && (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type="warning"
                    showIcon
                    message="Đang chờ khách xác nhận thanh toán"
                    description={
                      <Space direction="vertical" align="center" style={{ width: "100%" }}>
                        <div
                          style={{ width: 160, height: 160 }}
                          // eslint-disable-next-line react/no-danger
                          dangerouslySetInnerHTML={{
                            __html: qrByCart[cart.id].qr_svg,
                          }}
                        />
                        <Typography.Text code copyable style={{ fontSize: 11 }}>
                          {qrByCart[cart.id].confirm_url}
                        </Typography.Text>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          Khách quét mã này bằng điện thoại để xem hoá đơn và
                          xác nhận thanh toán.
                        </Typography.Text>
                      </Space>
                    }
                  />
                )}
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
                              <Tooltip title="Độ tin cậy nhận diện của AI cho sản phẩm này">
                                <Tag color={line.confidence < 0.75 ? "red" : "purple"}>
                                  AI {Math.round(line.confidence * 100)}%
                                </Tag>
                              </Tooltip>
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
            <code>/ws/carts</code>. Khi AI phát hiện khách vào khu vực checkout,
            giỏ chuyển sang <code>PENDING_CHECKOUT</code> (đóng băng hoá đơn,
            <b> chưa trừ tiền</b>) — khách quét mã QR hiển thị ở đây để xem hoá
            đơn và tự xác nhận thanh toán, hoặc nhân viên bấm "Xác nhận hộ" nếu
            khách không có điện thoại. Nếu không ai xác nhận trong{" "}
            {"CART_CHECKOUT_CONFIRM_TIMEOUT_MINUTES"} phút, giỏ tự quay lại
            ACTIVE để khách tiếp tục mua sắm. Có thể test bằng{" "}
            <code>POST http://ai-engine:8100/cart/simulate</code>.
          </>
        }
      />
    </Space>
  );
}
