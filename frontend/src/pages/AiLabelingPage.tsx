import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  List,
  Progress,
  Row,
  Space,
  Statistic,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadProps } from "antd";
import {
  CloudUploadOutlined,
  DeleteOutlined,
  LeftOutlined,
  RightOutlined,
  SaveOutlined,
  PlayCircleOutlined,
} from "@ant-design/icons";

import BboxLabelEditor from "@/components/BboxLabelEditor";
import { listProducts, type Product } from "@/api/catalog";
import {
  createLabeledTrainingJob,
  draftToYolo,
  getLabelImage,
  getLabelingStats,
  listLabelImages,
  saveLabelBoxes,
  uploadLabelImages,
  yoloToDraft,
  type DraftBox,
  type LabelImageSummary,
  type LabelingStats,
} from "@/api/aiLabeling";
import { getTrainingJob, type TrainingJob } from "@/api/aiTraining";

const { Title, Text, Paragraph } = Typography;
const BATCH_SIZE = 40;
const PAGE_SIZE = 50;

export default function AiLabelingPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [stats, setStats] = useState<LabelingStats | null>(null);
  const [items, setItems] = useState<LabelImageSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState<"all" | "pending" | "labeled">("all");
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [boxes, setBoxes] = useState<DraftBox[]>([]);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
  const [selectedBoxId, setSelectedBoxId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadPct, setUploadPct] = useState(0);
  const [training, setTraining] = useState(false);
  const [activeJob, setActiveJob] = useState<TrainingJob | null>(null);
  const pollRef = useRef<number | null>(null);
  const uploadQueueRef = useRef<File[]>([]);
  const uploadTimerRef = useRef<number | null>(null);
  const uploadingRef = useRef(false);

  const productById = useMemo(() => {
    const m = new Map<string, Product>();
    for (const p of products) m.set(p.id, p);
    return m;
  }, [products]);

  const loadProducts = useCallback(async () => {
    try {
      const all: Product[] = [];
      let skip = 0;
      const pageSize = 200;
      for (;;) {
        const res = await listProducts({ limit: pageSize, skip, is_active: true });
        all.push(...res.items);
        if (all.length >= res.total || res.items.length < pageSize) break;
        skip += pageSize;
      }
      setProducts(all);
      if (all.length && !selectedProductId) {
        setSelectedProductId(all[0]!.id);
      }
    } catch {
      message.error("Không tải được danh sách sản phẩm");
    }
  }, [selectedProductId]);

  const refreshStats = useCallback(async () => {
    try {
      const s = await getLabelingStats();
      setStats(s);
    } catch {
      /* stats optional on first load */
    }
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const labeled =
        filter === "labeled" ? true : filter === "pending" ? false : undefined;
      const res = await listLabelImages({
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        labeled,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (e: unknown) {
      const detail =
        e && typeof e === "object" && "response" in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      message.error(
        typeof detail === "string"
          ? detail
          : "Không tải được danh sách ảnh — chạy migration DB nếu vừa deploy"
      );
    } finally {
      setLoading(false);
    }
  }, [filter, page]);

  const loadImage = useCallback(
    async (id: string) => {
      setLoading(true);
      try {
        const detail = await getLabelImage(id);
        setCurrentId(id);
        setPreviewUrl(detail.preview_url);
        setBoxes(
          detail.boxes.map((b) =>
            yoloToDraft(
              b,
              b.sku ?? productById.get(b.product_id)?.sku ?? "?",
              b.product_name ?? productById.get(b.product_id)?.name ?? "?"
            )
          )
        );
        setSelectedBoxId(null);
        setDirty(false);
      } catch {
        message.error("Không tải được ảnh");
      } finally {
        setLoading(false);
      }
    },
    [productById]
  );

  useEffect(() => {
    void loadProducts();
    void refreshStats();
  }, [loadProducts, refreshStats]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    setCurrentId(null);
  }, [page, filter]);

  useEffect(() => {
    if (!currentId && items.length > 0) {
      void loadImage(items[0]!.id);
    }
  }, [currentId, items, loadImage]);

  const currentIndex = items.findIndex((i) => i.id === currentId);

  const saveCurrent = async (): Promise<boolean> => {
    if (!currentId) return false;
    setSaving(true);
    try {
      await saveLabelBoxes(
        currentId,
        boxes.map((b) => draftToYolo(b))
      );
      setDirty(false);
      message.success("Đã lưu nhãn");
      await refreshStats();
      await loadList();
      return true;
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "Lưu thất bại");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const goNext = async () => {
    if (dirty) {
      const ok = await saveCurrent();
      if (!ok) return;
    }
    const idx = currentIndex >= 0 ? currentIndex + 1 : 0;
    if (idx < items.length) {
      await loadImage(items[idx]!.id);
    } else if ((page + 1) * PAGE_SIZE < total) {
      setCurrentId(null);
      setPage((p) => p + 1);
    } else {
      message.info("Đã hết ảnh trong danh sách");
    }
  };

  const goPrev = async () => {
    if (dirty) {
      const ok = await saveCurrent();
      if (!ok) return;
    }
    const idx = currentIndex > 0 ? currentIndex - 1 : -1;
    if (idx >= 0) {
      await loadImage(items[idx]!.id);
    } else if (page > 0) {
      setPage((p) => p - 1);
    }
  };

  const deleteSelectedBox = () => {
    if (!selectedBoxId) return;
    setBoxes((prev) => prev.filter((b) => b.clientId !== selectedBoxId));
    setSelectedBoxId(null);
    setDirty(true);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        deleteSelectedBox();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        void goNext();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        void goPrev();
      } else if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        void saveCurrent();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const runUpload = useCallback(async () => {
    if (uploadingRef.current) return;
    const files = uploadQueueRef.current.splice(0);
    if (!files.length) return;
    uploadingRef.current = true;
    setUploading(true);
    setUploadPct(0);
    let uploaded = 0;
    let failed = 0;
    try {
      for (let i = 0; i < files.length; i += BATCH_SIZE) {
        const batch = files.slice(i, i + BATCH_SIZE);
        const res = await uploadLabelImages(batch);
        uploaded += res.uploaded;
        failed += res.failed;
        setUploadPct(Math.round(((i + batch.length) / files.length) * 100));
      }
      message.success(`Đã tải lên ${uploaded} ảnh${failed ? `, ${failed} lỗi` : ""}`);
      setPage(0);
      setFilter("all");
      setCurrentId(null);
      await refreshStats();
      await loadList();
    } catch (e: unknown) {
      const detail =
        e && typeof e === "object" && "response" in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      message.error(typeof detail === "string" ? detail : "Upload thất bại");
    } finally {
      uploadingRef.current = false;
      setUploading(false);
      setUploadPct(0);
      if (uploadQueueRef.current.length) {
        void runUpload();
      }
    }
  }, [loadList, refreshStats]);

  const uploadProps: UploadProps = {
    multiple: true,
    accept: "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp",
    showUploadList: false,
    disabled: uploading,
    beforeUpload: (file) => {
      uploadQueueRef.current.push(file);
      if (uploadTimerRef.current) window.clearTimeout(uploadTimerRef.current);
      uploadTimerRef.current = window.setTimeout(() => {
        void runUpload();
      }, 400);
      return false;
    },
  };

  const startTrain = async (values: { name: string; epochs: number }) => {
    setTraining(true);
    try {
      const job = await createLabeledTrainingJob({
        name: values.name,
        epochs: values.epochs,
      });
      setActiveJob(job);
      message.success("Đã bắt đầu huấn luyện từ dữ liệu gán nhãn");
      pollRef.current = window.setInterval(async () => {
        const j = await getTrainingJob(job.id);
        setActiveJob(j);
        if (j.status === "succeeded" || j.status === "failed") {
          if (pollRef.current) window.clearInterval(pollRef.current);
        }
      }, 3000);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "Không tạo được job");
    } finally {
      setTraining(false);
    }
  };

  useEffect(
    () => () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (uploadTimerRef.current) window.clearTimeout(uploadTimerRef.current);
    },
    []
  );

  return (
    <div>
      <Title level={3}>Gán nhãn bbox theo SKU</Title>
      <Paragraph type="secondary">
        Upload ảnh cảnh (nhiều sản phẩm/khung), kéo chuột vẽ khung và gán SKU. Phím tắt: ← →
        chuyển ảnh, Delete xóa khung, Ctrl+S lưu.
      </Paragraph>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={6}>
          <Card title="Thống kê" size="small">
            {stats && (
              <>
                <Statistic title="Tổng ảnh" value={stats.total_images} />
                <Statistic title="Đã gán nhãn" value={stats.labeled_images} />
                <Statistic title="Bbox" value={stats.total_boxes} />
                <Statistic title="SKU khác nhau" value={stats.distinct_skus} />
                {!stats.ready_for_training && stats.training_message && (
                  <Alert
                    type="warning"
                    showIcon
                    message={stats.training_message}
                    style={{ marginTop: 12 }}
                  />
                )}
              </>
            )}
          </Card>

          <Card title="Upload ảnh cảnh" size="small" style={{ marginTop: 16 }}>
            <Upload {...uploadProps}>
              <Button icon={<CloudUploadOutlined />} loading={uploading} block>
                Chọn ảnh (JPEG/PNG/WebP)
              </Button>
            </Upload>
            {uploading && <Progress percent={uploadPct} size="small" style={{ marginTop: 8 }} />}
            <Text type="secondary" style={{ display: "block", marginTop: 8, fontSize: 12 }}>
              Hỗ trợ upload hàng loạt — 600 ảnh chia nhiều lần hoặc một lần.
            </Text>
          </Card>

          <Card
            title="Danh sách ảnh"
            size="small"
            style={{ marginTop: 16 }}
            extra={
              <Space size={4}>
                <Tag
                  color={filter === "all" ? "blue" : "default"}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    setFilter("all");
                    setPage(0);
                  }}
                >
                  Tất cả
                </Tag>
                <Tag
                  color={filter === "pending" ? "orange" : "default"}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    setFilter("pending");
                    setPage(0);
                  }}
                >
                  Chưa gán
                </Tag>
                <Tag
                  color={filter === "labeled" ? "green" : "default"}
                  style={{ cursor: "pointer" }}
                  onClick={() => {
                    setFilter("labeled");
                    setPage(0);
                  }}
                >
                  Đã gán
                </Tag>
              </Space>
            }
          >
            <List
              size="small"
              loading={loading}
              dataSource={items}
              renderItem={(item) => (
                <List.Item
                  style={{
                    cursor: "pointer",
                    background: item.id === currentId ? "#e6f4ff" : undefined,
                    padding: "4px 8px",
                  }}
                  onClick={() => void loadImage(item.id)}
                >
                  <Space>
                    {item.labeled ? (
                      <Tag color="green">{item.box_count}</Tag>
                    ) : (
                      <Tag>—</Tag>
                    )}
                    <Text ellipsis style={{ maxWidth: 160 }}>
                      {item.original_filename ?? item.id.slice(0, 8)}
                    </Text>
                  </Space>
                </List.Item>
              )}
            />
            <Space style={{ marginTop: 8 }}>
              <Button
                size="small"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
              >
                Trang trước
              </Button>
              <Text type="secondary">
                {page + 1} / {Math.max(1, Math.ceil(total / PAGE_SIZE))}
              </Text>
              <Button
                size="small"
                disabled={(page + 1) * PAGE_SIZE >= total}
                onClick={() => setPage((p) => p + 1)}
              >
                Trang sau
              </Button>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card
            title={
              currentId
                ? `Ảnh ${currentIndex + 1 + page * PAGE_SIZE}/${total}`
                : "Chưa có ảnh"
            }
            extra={
              <Space>
                <Button icon={<LeftOutlined />} onClick={() => void goPrev()} />
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving}
                  onClick={() => void saveCurrent()}
                >
                  Lưu
                </Button>
                <Button icon={<RightOutlined />} onClick={() => void goNext()} />
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!selectedBoxId}
                  onClick={deleteSelectedBox}
                />
              </Space>
            }
          >
            <BboxLabelEditor
              imageUrl={previewUrl}
              products={products}
              boxes={boxes}
              selectedProductId={selectedProductId}
              onProductChange={setSelectedProductId}
              onBoxesChange={(b) => {
                setBoxes(b);
                setDirty(true);
              }}
              selectedBoxId={selectedBoxId}
              onSelectBox={setSelectedBoxId}
            />
            {dirty && (
              <Alert type="info" message="Có thay đổi chưa lưu" style={{ marginTop: 8 }} />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={6}>
          <Card title="Huấn luyện detector" size="small">
            <Form
              layout="vertical"
              initialValues={{ name: "Scene detector", epochs: 50 }}
              onFinish={startTrain}
            >
              <Form.Item name="name" label="Tên job" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="epochs" label="Epochs">
                <InputNumber min={5} max={300} style={{ width: "100%" }} />
              </Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                icon={<PlayCircleOutlined />}
                loading={training}
                disabled={!stats?.ready_for_training}
                block
              >
                Train từ nhãn bbox
              </Button>
            </Form>
            <Paragraph type="secondary" style={{ marginTop: 12, fontSize: 12 }}>
              Yêu cầu: ≥10 ảnh đã gán, ≥2 SKU, mỗi SKU ≥5 bbox. Sau khi train xong, deploy tại
              trang Train AI.
            </Paragraph>
            {activeJob && (
              <Alert
                style={{ marginTop: 12 }}
                type={activeJob.status === "failed" ? "error" : "info"}
                message={`Job: ${activeJob.status}`}
                description={activeJob.progress ?? activeJob.error_message ?? undefined}
              />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
