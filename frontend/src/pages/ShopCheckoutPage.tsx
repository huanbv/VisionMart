import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Divider,
  List,
  Result,
  Space,
  Spin,
  Typography,
  message,
} from "antd";
import { CheckCircleFilled, ShoppingOutlined } from "@ant-design/icons";
import { isAxiosError } from "axios";

import {
  type PublicBillResponse,
  cancelPublicCheckout,
  confirmPublicCheckout,
  getPublicBill,
} from "@/api/shop";

const POLL_MS = 4000;

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

export default function ShopCheckoutPage() {
  const { token } = useParams<{ token: string }>();
  const [bill, setBill] = useState<PublicBillResponse | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const data = await getPublicBill(token);
      setBill(data);
      setNotFound(false);
    } catch (err) {
      if (isAxiosError(err) && err.response?.status === 404) {
        setNotFound(true);
      }
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!bill || bill.status !== "pending_checkout") return;
    const id = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(id);
  }, [bill, load]);

  const onConfirm = async () => {
    if (!token) return;
    setConfirming(true);
    try {
      await confirmPublicCheckout(token);
      await load();
      message.success("Thanh toán thành công!");
    } catch (err) {
      const detail =
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không thể xác nhận thanh toán";
      message.error(detail);
      await load();
    } finally {
      setConfirming(false);
    }
  };

  const onCancel = async () => {
    if (!token) return;
    try {
      await cancelPublicCheckout(token);
      await load();
    } catch {
      message.error("Không thể huỷ xác nhận");
    }
  };

  const pageStyle: React.CSSProperties = {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 16,
    background: "#f5f5f5",
  };

  if (loading) {
    return (
      <div style={pageStyle}>
        <Spin size="large" />
      </div>
    );
  }

  if (notFound || !bill) {
    return (
      <div style={pageStyle}>
        <Result
          status="404"
          title="Liên kết không hợp lệ"
          subTitle="Mã QR này không tồn tại hoặc đã hết hạn. Vui lòng quay lại quầy để được hỗ trợ."
        />
      </div>
    );
  }

  if (bill.status === "converted") {
    return (
      <div style={pageStyle}>
        <Card style={{ maxWidth: 420, width: "100%" }}>
          <Result
            icon={<CheckCircleFilled style={{ color: "#52c41a" }} />}
            status="success"
            title="Thanh toán thành công"
            subTitle={`Mã đơn hàng: ${bill.order_code ?? ""}`}
          />
          <Divider />
          <Typography.Paragraph style={{ textAlign: "center" }}>
            Tổng thanh toán:{" "}
            <Typography.Text strong>
              {formatMoney(bill.total_amount, bill.currency)}
            </Typography.Text>
          </Typography.Paragraph>
          <Typography.Paragraph
            type="secondary"
            style={{ textAlign: "center", fontSize: 12 }}
          >
            Cảm ơn quý khách đã mua sắm tại VisionMart!
          </Typography.Paragraph>
        </Card>
      </div>
    );
  }

  if (bill.status !== "pending_checkout") {
    return (
      <div style={pageStyle}>
        <Result
          icon={<ShoppingOutlined />}
          title="Chưa có hoá đơn chờ xác nhận"
          subTitle="Giỏ hàng này hiện không ở trạng thái chờ thanh toán. Nếu bạn vừa huỷ, hãy tiếp tục mua sắm và quay lại quầy khi sẵn sàng."
        />
      </div>
    );
  }

  return (
    <div style={pageStyle}>
      <Card
        title="Hoá đơn của bạn"
        style={{ maxWidth: 420, width: "100%" }}
        extra={<ShoppingOutlined />}
      >
        <List
          size="small"
          dataSource={bill.lines}
          renderItem={(line) => (
            <List.Item>
              <List.Item.Meta
                title={line.product_name}
                description={`${line.sku} • SL: ${line.quantity}`}
              />
              <div>{formatMoney(line.subtotal, bill.currency)}</div>
            </List.Item>
          )}
        />
        <Divider style={{ margin: "12px 0" }} />
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginBottom: 16,
          }}
        >
          <Typography.Text strong>Tổng cộng</Typography.Text>
          <Typography.Text strong style={{ fontSize: 18 }}>
            {formatMoney(bill.total_amount, bill.currency)}
          </Typography.Text>
        </div>

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Thanh toán demo (mô phỏng)"
          description="Đây là môi trường demo đồ án — nhấn Xác nhận sẽ mô phỏng một giao dịch thành công, chưa kết nối cổng thanh toán thật."
        />

        <Space direction="vertical" style={{ width: "100%" }}>
          <Button
            type="primary"
            size="large"
            block
            loading={confirming}
            onClick={onConfirm}
          >
            Xác nhận &amp; Thanh toán
          </Button>
          <Button block onClick={onCancel} disabled={confirming}>
            Chưa xong, tiếp tục mua sắm
          </Button>
        </Space>
      </Card>
    </div>
  );
}
