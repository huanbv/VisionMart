import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Image,
  Input,
  Popconfirm,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CheckOutlined,
  CloseOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import {
  approveCandidate,
  getReviewStats,
  listReviewCandidates,
  rejectCandidate,
  type ReviewCandidate,
  type ReviewSource,
  type ReviewStats,
  type ReviewStatus,
} from "@/api/aiReview";
import { listAllProducts, type Product } from "@/api/catalog";

const { Title, Paragraph, Text } = Typography;

const SOURCE_LABEL: Record<ReviewSource, string> = {
  low_confidence: "Độ tin cậy thấp",
  checkout_mismatch: "Người sửa ở thanh toán",
  manual: "Gắn cờ thủ công",
};

const SOURCE_COLOR: Record<ReviewSource, string> = {
  low_confidence: "orange",
  checkout_mismatch: "purple",
  manual: "blue",
};

/**
 * Human review queue for active learning.
 *
 * Only approved items become training data. Approving requires picking the
 * correct product — the screen never pre-confirms the model's own guess,
 * because rubber-stamping predictions would train the model on its own
 * mistakes, which is exactly what this queue exists to prevent.
 */
export default function AiReviewPage() {
  const [items, setItems] = useState<ReviewCandidate[]>([]);
  const [stats, setStats] = useState<ReviewStats | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [status, setStatus] = useState<ReviewStatus>("pending");
  const [source, setSource] = useState<ReviewSource | undefined>();
  const [choice, setChoice] = useState<Record<string, string>>({});
  const [note, setNote] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, s] = await Promise.all([
        listReviewCandidates({ status, source, limit: 60 }),
        getReviewStats(),
      ]);
      setItems(list.items);
      setStats(s);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Không tải được hàng đợi duyệt";
      setError(detail);
    } finally {
      setLoading(false);
    }
  }, [status, source]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    // Phân trang thay vì xin 500 một lần: backend chặn limit ở 200, nên
    // yêu cầu lớn hơn bị từ chối bằng 422 — cả ô chọn rỗng, không duyệt
    // được nhãn nào.
    listAllProducts({ is_active: true })
      .then(setProducts)
      .catch((err) => {
        console.error("listAllProducts failed", err);
        message.error("Không tải được danh sách sản phẩm");
      });
  }, []);

  const doApprove = async (c: ReviewCandidate) => {
    const productId = choice[c.id];
    if (!productId) {
      message.warning("Chọn sản phẩm đúng trước khi duyệt");
      return;
    }
    setBusy(c.id);
    try {
      await approveCandidate(c.id, productId, note[c.id]);
      message.success("Đã duyệt — ảnh được thêm vào tập huấn luyện");
      await load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Duyệt thất bại";
      message.error(detail);
    } finally {
      setBusy(null);
    }
  };

  const doReject = async (c: ReviewCandidate) => {
    setBusy(c.id);
    try {
      await rejectCandidate(c.id, note[c.id]);
      message.success("Đã bỏ qua khung hình này");
      await load();
    } catch {
      message.error("Thao tác thất bại");
    } finally {
      setBusy(null);
    }
  };

  const productName = (id: string | null) =>
    id ? (products.find((p) => p.id === id)?.name ?? id.slice(0, 8)) : null;

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          Duyệt dữ liệu huấn luyện
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Những khung hình AI đoán không chắc, hoặc bị người sửa lại ở khâu
          thanh toán, được đưa vào đây. Ảnh <b>chỉ trở thành dữ liệu huấn
          luyện sau khi có người xác nhận nhãn</b> — nhờ vậy model học từ nhãn
          đúng thay vì học lại chính sai lầm của nó.
        </Paragraph>
      </div>

      {stats && (
        <Row gutter={16}>
          <Col xs={8} md={5}>
            <Card size="small">
              <Statistic title="Chờ duyệt" value={stats.pending} />
            </Card>
          </Col>
          <Col xs={8} md={5}>
            <Card size="small">
              <Statistic
                title="Đã duyệt"
                value={stats.approved}
                valueStyle={{ color: "#3f8600" }}
              />
            </Card>
          </Col>
          <Col xs={8} md={5}>
            <Card size="small">
              <Statistic
                title="Đã bỏ"
                value={stats.rejected}
                valueStyle={{ color: "#cf1322" }}
              />
            </Card>
          </Col>
          <Col xs={24} md={9}>
            <Card size="small">
              <Text type="secondary" style={{ fontSize: 12 }}>
                Tỷ lệ dùng được
              </Text>
              <Progress
                percent={
                  stats.approved + stats.rejected > 0
                    ? Math.round(
                        (stats.approved / (stats.approved + stats.rejected)) * 100,
                      )
                    : 0
                }
                size="small"
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                Tỷ lệ bỏ quá cao nghĩa là ngưỡng thu thập đang bắt nhầm quá nhiều
                khung hình xấu.
              </Text>
            </Card>
          </Col>
        </Row>
      )}

      <Card>
        <Space wrap>
          <Segmented
            value={status}
            onChange={(v) => setStatus(v as ReviewStatus)}
            options={[
              { label: "Chờ duyệt", value: "pending" },
              { label: "Đã duyệt", value: "approved" },
              { label: "Đã bỏ", value: "rejected" },
            ]}
          />
          <Select
            allowClear
            placeholder="Lọc theo nguồn"
            style={{ minWidth: 220 }}
            value={source}
            onChange={(v) => setSource(v)}
            options={(Object.keys(SOURCE_LABEL) as ReviewSource[]).map((s) => ({
              label: SOURCE_LABEL[s],
              value: s,
            }))}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            Tải lại
          </Button>
        </Space>
      </Card>

      {error && <Alert type="error" showIcon message={error} />}

      <Card loading={loading}>
        {items.length === 0 && !loading ? (
          <Empty
            description={
              status === "pending"
                ? "Không có khung hình nào chờ duyệt"
                : "Không có mục nào"
            }
          />
        ) : (
          <Row gutter={[16, 16]}>
            {items.map((c) => (
              <Col xs={24} md={12} xxl={8} key={c.id}>
                <Card
                  size="small"
                  title={
                    <Space size={4} wrap>
                      <Tag color={SOURCE_COLOR[c.source]}>
                        {SOURCE_LABEL[c.source]}
                      </Tag>
                      {c.confidence != null && (
                        <Tooltip title="Độ tin cậy của model. Càng thấp thì nhãn mới càng đáng giá.">
                          <Tag color={c.confidence < 0.4 ? "red" : "default"}>
                            {(c.confidence * 100).toFixed(0)}%
                          </Tag>
                        </Tooltip>
                      )}
                    </Space>
                  }
                >
                  {c.preview_url ? (
                    <Image
                      src={c.preview_url}
                      alt="khung hình chờ duyệt"
                      style={{ width: "100%", maxHeight: 220, objectFit: "contain" }}
                    />
                  ) : (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="Không xem được ảnh"
                    />
                  )}

                  <div style={{ marginTop: 8 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      AI đoán:{" "}
                      {productName(c.predicted_product_id) ??
                        c.predicted_class ??
                        "không nhận ra"}
                    </Text>
                  </div>

                  {c.status === "pending" ? (
                    <Space direction="vertical" size={8} style={{ width: "100%", marginTop: 8 }}>
                      <Select
                        showSearch
                        style={{ width: "100%" }}
                        placeholder="Chọn sản phẩm ĐÚNG"
                        optionFilterProp="label"
                        value={choice[c.id]}
                        onChange={(v) => setChoice((s) => ({ ...s, [c.id]: v }))}
                        options={products.map((p) => ({ label: p.name, value: p.id }))}
                      />
                      <Input
                        placeholder="Ghi chú (không bắt buộc)"
                        value={note[c.id] ?? ""}
                        onChange={(e) =>
                          setNote((s) => ({ ...s, [c.id]: e.target.value }))
                        }
                      />
                      <Space>
                        <Button
                          type="primary"
                          icon={<CheckOutlined />}
                          loading={busy === c.id}
                          onClick={() => void doApprove(c)}
                        >
                          Duyệt
                        </Button>
                        <Popconfirm
                          title="Bỏ khung hình này?"
                          description="Dùng khi ảnh bị che, rung hoặc không có sản phẩm."
                          onConfirm={() => void doReject(c)}
                          okText="Bỏ"
                          cancelText="Huỷ"
                        >
                          <Button danger icon={<CloseOutlined />} loading={busy === c.id}>
                            Bỏ qua
                          </Button>
                        </Popconfirm>
                      </Space>
                    </Space>
                  ) : (
                    <div style={{ marginTop: 8 }}>
                      <Tag color={c.status === "approved" ? "green" : "red"}>
                        {c.status === "approved" ? "Đã duyệt" : "Đã bỏ"}
                      </Tag>
                      {c.confirmed_product_id && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          → {productName(c.confirmed_product_id)}
                        </Text>
                      )}
                      {c.review_note && (
                        <div>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {c.review_note}
                          </Text>
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>
    </Space>
  );
}
