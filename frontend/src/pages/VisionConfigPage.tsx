import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from "antd";
import { ReloadOutlined, UndoOutlined } from "@ant-design/icons";

import {
  getVisionConfig,
  resetVisionConfig,
  updateVisionConfig,
  type VisionConfigResponse,
} from "@/api/aiReview";
import ProductRecognitionCard from "./ProductRecognitionCard";

const { Title, Paragraph, Text } = Typography;

/**
 * Runtime tuning of the OpenCV preprocessing chain.
 *
 * Changes are written to the engine's runtime config file and picked up
 * within a second — no `.env` edit, no container restart. Values not set
 * here fall through to the deployment defaults, and the UI marks which is
 * which so an operator can tell why a toggle is on.
 */

interface NumField {
  key: string;
  label: string;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
}

interface TextField {
  key: string;
  label: string;
  hint?: string;
}

interface Group {
  title: string;
  note?: string;
  toggle?: { key: string; label: string; hint?: string };
  numbers?: NumField[];
  texts?: TextField[];
}

const GROUPS: Group[] = [
  {
    title: "Vùng quan tâm (ROI)",
    toggle: {
      key: "ENABLE_ROI",
      label: "Bật ROI",
      hint: "Chỉ giữ vùng nghiệp vụ, bỏ phần khung hình không liên quan.",
    },
  },
  {
    title: "Chế độ quét quầy thanh toán",
    note: "Bật để sản phẩm trong vùng thanh toán được thêm vào giỏ ngay khi nhận ra SKU (không đợi cổ tay / 5 giây). Camera phải đánh dấu \"Khu vực thanh toán\".",
    toggle: {
      key: "CHECKOUT_SCAN_MODE",
      label: "Bật chế độ quét quầy",
      hint: "Tắt = camera quầy chạy như kệ hàng (phải có người cầm sản phẩm).",
    },
  },
  {
    title: "Bật phân loại SKU (tầng 2)",
    note: "Model tầng 2 phân loại crop thành SKU — chỉ khi YOLO ra lớp COCO chung (bottle, cup…). Cần file model. Nếu tắt (đang tắt): quầy dùng YOLO + bảng Lớp → SKU; hai số “Ngưỡng phân loại SKU” bên dưới KHÔNG chạy.",
    toggle: {
      key: "ENABLE_SKU_CLASSIFIER",
      label: "Bật SKU classifier",
      hint: "Chưa có model đã train thì bật cũng không có tác dụng — hãy dùng bảng ánh xạ Lớp → SKU.",
    },
    texts: [
      {
        key: "CLASSIFIER_MODEL_PATH",
        label: "Đường dẫn model",
        hint: "Ví dụ /models/sku_classifier.onnx",
      },
      {
        key: "CLASSIFIER_LABELS_PATH",
        label: "Đường dẫn nhãn",
        hint: "Ví dụ /models/sku_labels.json",
      },
    ],
  },
  {
    title: "Ngưỡng phân loại SKU (Classifier)",
    note: "Chỉ khi Bật phân loại SKU. Đang tắt thì chỉnh 0.50 ở đây không làm quầy nhận thêm sản phẩm. Quầy nhận SKU khi YOLO + bảng Lớp → SKU khớp, rồi thêm vào giỏ ngay.",
    numbers: [
      {
        key: "CLASSIFIER_MIN_CONFIDENCE",
        label: "Độ tin cậy tối thiểu",
        min: 0,
        max: 1,
        step: 0.01,
        hint: "Thấp hơn = nhận nhiều sản phẩm hơn nhưng dễ nhận nhầm. Mặc định 0.55.",
      },
      {
        key: "CLASSIFIER_MIN_MARGIN",
        label: "Khoảng cách hạng 1–2 tối thiểu",
        min: 0,
        max: 1,
        step: 0.01,
        hint: "Chênh lệch tối thiểu giữa SKU dự đoán hạng 1 và hạng 2 — 0 nghĩa là tắt kiểm tra này.",
      },
    ],
  },
  {
    title: "Quầy thanh toán nhiều khách (multi-person)",
    note: "Ghép sản phẩm với đúng khách đứng gần quầy, và bắc cầu qua occlusion ngắn để không đếm trùng một sản phẩm khi tracker đổi track_id.",
    numbers: [
      {
        key: "CHECKOUT_PERSON_ASSOC_MAX_DIST_PX",
        label: "Khoảng cách gán chủ sở hữu (px)",
        min: 50,
        max: 1000,
        step: 10,
        hint: "Người xa sản phẩm hơn khoảng cách này (tâm bbox trên khung) không được gán là chủ, kể cả khi không thấy cổ tay. Camera góc rộng/người đứng lùi khỏi quầy cần giá trị lớn hơn. Mặc định 220.",
      },
      {
        key: "CHECKOUT_HAND_REACH_PX",
        label: "Bán kính cổ tay đặt hàng (px)",
        min: 20,
        max: 400,
        step: 10,
        hint: "Cổ tay phải nằm trong bán kính này so với tâm sản phẩm mới được ưu tiên là người đặt. Có nhiều khách thì cổ tay thắng quỹ đạo. Mặc định 100.",
      },
      {
        key: "CHECKOUT_UNASSIGNED_GRACE_SECONDS",
        label: "Thời gian chờ ghép người (giây)",
        min: 0,
        max: 60,
        step: 1,
        hint: "Trước đây sản phẩm chờ ngần này trước khi vào giỏ nếu chưa ghép được người. Hiện quầy thêm SKU ngay; số này không còn chặn giỏ.",
      },
      {
        key: "PRODUCT_REACQUIRE_WINDOW_SECONDS",
        label: "Cửa sổ bắc cầu occlusion (giây)",
        min: 0,
        max: 30,
        step: 1,
        hint: "Track sản phẩm mới xuất hiện trong khoảng này, gần vị trí cũ, được coi là CÙNG một sản phẩm vật lý (không đếm trùng). Cửa sổ 2s dễ tách một chai thành 2 dòng nếu YOLO mất track lâu hơn. Mặc định 5.",
      },
      {
        key: "PRODUCT_REACQUIRE_MAX_DIST_PX",
        label: "Khoảng cách bắc cầu occlusion (px)",
        min: 10,
        max: 500,
        step: 10,
        hint: "Khoảng cách tối đa giữa vị trí cũ và mới để coi là cùng sản phẩm khi bắc cầu. Mặc định 60.",
      },
      {
        key: "CHECKOUT_TRAJECTORY_WINDOW_SECONDS",
        label: "Cửa sổ xét quỹ đạo (giây)",
        min: 1,
        max: 60,
        step: 1,
        hint: "Chỉ tính người là chủ sở hữu nếu quỹ đạo của họ đi qua gần sản phẩm trong ngần này giây gần đây — không chỉ đứng gần lúc phát hiện. Hoạt động cả khi có nhiều khách. Mặc định 15.",
      },
      {
        key: "CHECKOUT_TRAJECTORY_REACH_DIST_PX",
        label: "Bán kính \"đã chạm tới\" (px)",
        min: 20,
        max: 500,
        step: 10,
        hint: "Khoảng cách tối đa để coi một điểm trong quỹ đạo là đã tới gần sản phẩm. Mặc định 120.",
      },
    ],
  },
  {
    title: "Auto gamma",
    note: "Tự tính hệ số gamma theo độ sáng từng khung — một cấu hình dùng được cả ngày lẫn đêm. Ưu tiên hơn Gamma cố định khi cùng bật.",
    toggle: { key: "ENABLE_AUTO_GAMMA", label: "Bật auto gamma" },
    numbers: [
      {
        key: "AUTO_GAMMA_TARGET_BRIGHTNESS",
        label: "Độ sáng mục tiêu",
        min: 1,
        max: 254,
        step: 5,
        hint: "Mức sáng trung bình muốn đạt (0–255).",
      },
      { key: "AUTO_GAMMA_MIN", label: "Gamma tối thiểu", min: 0.1, max: 5, step: 0.1 },
      { key: "AUTO_GAMMA_MAX", label: "Gamma tối đa", min: 0.1, max: 5, step: 0.1 },
    ],
  },
  {
    title: "Gamma cố định",
    note: "Lưu ý: giá trị > 1 làm ảnh SÁNG hơn, < 1 làm TỐI hơn.",
    toggle: { key: "ENABLE_GAMMA", label: "Bật gamma" },
    numbers: [
      {
        key: "GAMMA_VALUE",
        label: "Giá trị gamma",
        min: 0.1,
        max: 5,
        step: 0.1,
        hint: "1.5–2.0 cho cảnh thiếu sáng.",
      },
    ],
  },
  {
    title: "Độ sáng / tương phản",
    toggle: { key: "ENABLE_BRIGHTNESS_ADJUST", label: "Bật chỉnh độ sáng" },
    numbers: [
      { key: "BRIGHTNESS_DELTA", label: "Độ dời (β)", min: -255, max: 255, step: 5 },
    ],
  },
  {
    title: "Tương phản",
    toggle: { key: "ENABLE_CONTRAST_ADJUST", label: "Bật chỉnh tương phản" },
    numbers: [
      { key: "CONTRAST_ALPHA", label: "Hệ số (α)", min: 0.1, max: 3, step: 0.1 },
    ],
  },
  {
    title: "CLAHE",
    note: "Cân bằng histogram thích nghi cục bộ — xử lý được ảnh sáng không đồng đều mà không cháy vùng sáng.",
    toggle: { key: "ENABLE_CLAHE", label: "Bật CLAHE" },
    numbers: [
      { key: "CLAHE_CLIP_LIMIT", label: "Clip limit", min: 0.1, max: 10, step: 0.5 },
      { key: "CLAHE_TILE_GRID_SIZE", label: "Kích thước lưới ô", min: 1, max: 32, step: 1 },
    ],
  },
  {
    title: "Cân bằng histogram toàn cục (HE)",
    note: "Ít dùng trong thực tế: dễ cháy sáng và khuếch đại nhiễu. Thường nên dùng CLAHE thay thế.",
    toggle: { key: "ENABLE_HIST_EQ", label: "Bật HE" },
  },
  {
    title: "Lọc Gaussian",
    toggle: { key: "ENABLE_GAUSSIAN_BLUR", label: "Bật lọc Gaussian" },
    numbers: [
      {
        key: "GAUSSIAN_KERNEL_SIZE",
        label: "Kích thước nhân",
        min: 1,
        max: 31,
        step: 2,
        hint: "Phải là số lẻ.",
      },
    ],
  },
  {
    title: "Lọc trung vị",
    note: "Bộ lọc duy nhất xử lý tốt nhiễu muối tiêu (chấm đen trắng).",
    toggle: { key: "ENABLE_MEDIAN_BLUR", label: "Bật lọc trung vị" },
    numbers: [
      { key: "MEDIAN_KERNEL_SIZE", label: "Kích thước nhân", min: 1, max: 31, step: 2 },
    ],
  },
  {
    title: "Trung vị thích nghi",
    note: "Xử lý nhiễu xung mật độ cao, giữ chi tiết tốt hơn trung vị thường.",
    toggle: { key: "ENABLE_ADAPTIVE_MEDIAN", label: "Bật trung vị thích nghi" },
    numbers: [
      { key: "ADAPTIVE_MEDIAN_MAX_KERNEL", label: "Cửa sổ tối đa", min: 3, max: 15, step: 2 },
    ],
  },
  {
    title: "Bộ lọc song phương (bilateral)",
    note: "Khử nhiễu mà GIỮ ĐƯỢC BIÊN — quan trọng vì ảnh sẽ đưa vào detector. Đổi lại là bộ lọc tốn CPU nhất.",
    toggle: { key: "ENABLE_BILATERAL", label: "Bật bilateral" },
    numbers: [
      { key: "BILATERAL_DIAMETER", label: "Đường kính", min: 1, max: 25, step: 2 },
      { key: "BILATERAL_SIGMA_COLOR", label: "Sigma màu", min: 1, max: 200, step: 5 },
      { key: "BILATERAL_SIGMA_SPACE", label: "Sigma không gian", min: 1, max: 200, step: 5 },
    ],
  },
  {
    title: "Unsharp masking (làm sắc)",
    note: "Cứu khung hình hơi mờ. Ngưỡng > 0 tránh khuếch đại nhiễu ở vùng tối.",
    toggle: { key: "ENABLE_UNSHARP_MASK", label: "Bật unsharp masking" },
    numbers: [
      {
        key: "UNSHARP_AMOUNT",
        label: "Mức nhấn",
        min: 0,
        max: 3,
        step: 0.1,
        hint: "1.0 là unsharp masking chuẩn, > 1 là highboost (dễ tạo quầng).",
      },
      { key: "UNSHARP_RADIUS", label: "Bán kính", min: 1, max: 15, step: 1 },
      { key: "UNSHARP_THRESHOLD", label: "Ngưỡng", min: 0, max: 100, step: 1 },
    ],
  },
  {
    title: "Đo chất lượng ảnh",
    note: "Cổng chất lượng: đo độ sáng, tương phản, độ nét, nhiễu để loại khung hình xấu trước khi tốn tài nguyên nhận dạng.",
    toggle: { key: "ENABLE_IMAGE_QUALITY", label: "Bật đo chất lượng" },
    numbers: [
      { key: "BLUR_THRESHOLD", label: "Ngưỡng độ nét", min: 0, max: 2000, step: 10 },
      {
        key: "IMAGE_QUALITY_THRESHOLD",
        label: "Ngưỡng điểm chất lượng",
        min: 0,
        max: 1,
        step: 0.05,
      },
    ],
  },
  {
    title: "Gỡ lỗi & đo hiệu năng",
    toggle: { key: "ENABLE_BLUR_ANALYSIS", label: "Phân tích độ mờ" },
  },
  {
    title: "Lớp phủ gỡ lỗi",
    note: "Vẽ ROI + chỉ số chất lượng lên khung hình trả về.",
    toggle: { key: "ENABLE_DEBUG_OVERLAY", label: "Bật debug overlay" },
  },
  {
    title: "Lưu vết pipeline",
    note: "Cho phép trang “Pipeline xử lý ảnh” lưu ảnh từng bước. Tốn I/O nên chỉ bật khi cần.",
    toggle: { key: "ENABLE_PIPELINE_TRACE", label: "Bật lưu vết" },
    numbers: [
      {
        key: "TRACE_SAMPLE_RATE",
        label: "Tỷ lệ lấy mẫu",
        min: 0,
        max: 1,
        step: 0.01,
        hint: "0 = chỉ lưu khi bấm thủ công.",
      },
    ],
  },
  {
    title: "Đo hiệu năng",
    toggle: { key: "ENABLE_PERFORMANCE_METRICS", label: "Đẩy số liệu sang Prometheus" },
  },
  {
    title: "Thu thập dữ liệu học (active learning)",
    note: "Tự đẩy những khung hình AI đoán không chắc vào hàng đợi duyệt. Ảnh chỉ thành dữ liệu huấn luyện sau khi có người xác nhận nhãn.",
    toggle: {
      key: "ENABLE_REVIEW_CAPTURE",
      label: "Bật thu thập tự động",
      hint: "Chạy nền, không làm chậm nhận diện.",
    },
    numbers: [
      {
        key: "REVIEW_CAPTURE_MIN_CONFIDENCE",
        label: "Ngưỡng sàn",
        min: 0,
        max: 1,
        step: 0.05,
        hint: "Bỏ qua các phát hiện tin cậy quá thấp (thường chỉ là nhiễu).",
      },
      {
        key: "REVIEW_CAPTURE_COOLDOWN_SECONDS",
        label: "Giãn cách (giây)",
        min: 1,
        max: 3600,
        step: 10,
        hint: "Tối đa 1 ảnh mỗi camera trong khoảng này — tránh ngập hàng đợi.",
      },
    ],
  },
];

export default function VisionConfigPage() {
  const [cfg, setCfg] = useState<VisionConfigResponse | null>(null);
  const [draft, setDraft] = useState<Record<string, string | number | boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getVisionConfig();
      setCfg(data);
      setDraft({ ...data.effective });
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Không tải được cấu hình";
      setError(detail);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Only send what actually differs — keeps the override file minimal. */
  const changed = cfg
    ? Object.keys(draft).filter(
        (k) => String(draft[k]) !== String(cfg.effective[k]),
      )
    : [];

  const save = async () => {
    if (!changed.length) return;
    setSaving(true);
    try {
      const payload: Record<string, string | number | boolean> = {};
      changed.forEach((k) => (payload[k] = draft[k]));
      const data = await updateVisionConfig(payload);
      setCfg(data);
      setDraft({ ...data.effective });
      message.success(`Đã lưu ${changed.length} thay đổi — áp dụng trong ~1 giây`);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Lưu thất bại";
      message.error(detail);
    } finally {
      setSaving(false);
    }
  };

  const resetAll = async () => {
    setSaving(true);
    try {
      const data = await resetVisionConfig();
      setCfg(data);
      setDraft({ ...data.effective });
      message.success("Đã xoá toàn bộ tuỳ chỉnh, quay về mặc định");
    } catch {
      message.error("Không đặt lại được");
    } finally {
      setSaving(false);
    }
  };

  const isOverridden = (key: string) => cfg?.overridden_keys.includes(key) ?? false;
  const boolOf = (key: string) => draft[key] === true || draft[key] === "true";
  const numOf = (key: string) => {
    const v = draft[key];
    const n = typeof v === "number" ? v : Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  const strOf = (key: string) => {
    const v = draft[key];
    return v === undefined || v === null ? "" : String(v);
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          Cấu hình xử lý ảnh
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Chỉnh trực tiếp chuỗi tiền xử lý OpenCV — không cần sửa file{" "}
          <Text code>.env</Text> hay khởi động lại. Thay đổi có hiệu lực trong
          khoảng 1 giây. Thẻ <Tag color="gold">tuỳ chỉnh</Tag> đánh dấu giá trị
          đã đặt tại đây; còn lại là mặc định khi triển khai.
        </Paragraph>
      </div>

      <Alert
        type="warning"
        showIcon
        message="Đọc trước khi bật tiền xử lý trên production"
        description={
          <>
            Mô hình nhận dạng hiện được huấn luyện trên ảnh <b>chưa tăng cường</b>.
            Nếu chỉ bật tăng cường lúc chạy, phân bố ảnh đầu vào sẽ lệch so với
            lúc huấn luyện và độ chính xác <b>có thể giảm</b>. Hãy đo A/B trước
            (module <Text code>evaluation</Text>), và nếu dùng thì áp dụng cùng
            một cấu hình cho cả huấn luyện lẫn chạy thật.
          </>
        }
      />

      {error && <Alert type="error" showIcon message={error} />}

      <ProductRecognitionCard />

      <Card
        loading={loading}
        title={
          cfg ? (
            <Space size={4}>
              <Text>Đang có</Text>
              <Tag color={cfg.overridden_keys.length ? "gold" : "default"}>
                {cfg.overridden_keys.length} tuỳ chỉnh
              </Tag>
            </Space>
          ) : (
            "Đang tải…"
          )
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()} disabled={saving}>
              Tải lại
            </Button>
            <Popconfirm
              title="Xoá toàn bộ tuỳ chỉnh?"
              description="Mọi thiết lập sẽ quay về mặc định khi triển khai."
              onConfirm={() => void resetAll()}
              okText="Xoá"
              cancelText="Huỷ"
            >
              <Button icon={<UndoOutlined />} danger disabled={saving || !cfg?.overridden_keys.length}>
                Đặt lại mặc định
              </Button>
            </Popconfirm>
            <Button
              type="primary"
              onClick={() => void save()}
              loading={saving}
              disabled={!changed.length}
            >
              Lưu{changed.length ? ` (${changed.length})` : ""}
            </Button>
          </Space>
        }
      >
        {cfg && (
          <Row gutter={[16, 16]}>
            {GROUPS.map((g) => (
              <Col xs={24} lg={12} xxl={8} key={g.title}>
                <Card size="small" title={g.title} style={{ height: "100%" }}>
                  {g.note && (
                    <Paragraph type="secondary" style={{ fontSize: 12 }}>
                      {g.note}
                    </Paragraph>
                  )}

                  {g.toggle && (
                    <Space align="center" style={{ marginBottom: 8 }}>
                      <Switch
                        checked={boolOf(g.toggle.key)}
                        onChange={(v) =>
                          setDraft((d) => ({ ...d, [g.toggle!.key]: v }))
                        }
                      />
                      <Text>{g.toggle.label}</Text>
                      {isOverridden(g.toggle.key) && <Tag color="gold">tuỳ chỉnh</Tag>}
                    </Space>
                  )}
                  {g.toggle?.hint && (
                    <Paragraph type="secondary" style={{ fontSize: 12 }}>
                      {g.toggle.hint}
                    </Paragraph>
                  )}

                  {g.texts?.length ? (
                    <>
                      <Divider style={{ margin: "8px 0" }} />
                      <Space direction="vertical" size={8} style={{ width: "100%" }}>
                        {g.texts.map((t) => (
                          <div key={t.key}>
                            <Space align="center" wrap>
                              <Text style={{ minWidth: 130, display: "inline-block" }}>
                                {t.label}
                              </Text>
                              <Input
                                style={{ width: 260 }}
                                value={strOf(t.key)}
                                onChange={(e) =>
                                  setDraft((d) => ({ ...d, [t.key]: e.target.value }))
                                }
                              />
                              {isOverridden(t.key) && <Tag color="gold">tuỳ chỉnh</Tag>}
                            </Space>
                            {t.hint && (
                              <div>
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {t.hint}
                                </Text>
                              </div>
                            )}
                          </div>
                        ))}
                      </Space>
                    </>
                  ) : null}

                  {g.numbers?.length ? (
                    <>
                      <Divider style={{ margin: "8px 0" }} />
                      <Space direction="vertical" size={8} style={{ width: "100%" }}>
                        {g.numbers.map((n) => (
                          <div key={n.key}>
                            <Space align="center" wrap>
                              <Text style={{ minWidth: 150, display: "inline-block" }}>
                                {n.label}
                              </Text>
                              <InputNumber
                                value={numOf(n.key)}
                                min={n.min}
                                max={n.max}
                                step={n.step}
                                onChange={(v) =>
                                  setDraft((d) => ({ ...d, [n.key]: v ?? 0 }))
                                }
                              />
                              {isOverridden(n.key) && <Tag color="gold">tuỳ chỉnh</Tag>}
                            </Space>
                            {n.hint && (
                              <div>
                                <Text type="secondary" style={{ fontSize: 12 }}>
                                  {n.hint}
                                </Text>
                              </div>
                            )}
                          </div>
                        ))}
                      </Space>
                    </>
                  ) : null}
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Card>

      {cfg && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          Tệp cấu hình: <Text code>{cfg.config_path}</Text>
        </Text>
      )}
    </Space>
  );
}
