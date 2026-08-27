import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Segmented,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { UploadProps } from "antd";
import {
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  LeftOutlined,
  RightOutlined,
  SaveOutlined,
  PlayCircleOutlined,
  ScissorOutlined,
} from "@ant-design/icons";

import { Link } from "react-router-dom";

import BboxLabelEditor, { type EditorMode, type LabelTool } from "@/components/BboxLabelEditor";
import LabelImageGrid from "@/components/LabelImageGrid";
import { listProducts, type Product } from "@/api/catalog";
import {
  createLabeledTrainingJob,
  cropLabelImage,
  draftToYolo,
  exportLabelImages,
  getLabelImage,
  getLabelingStats,
  listLabelImages,
  markLabelImageCropped,
  saveLabelBoxes,
  uploadLabelImages,
  yoloToDraft,
  type DraftBox,
  type CropRect,
  type LabelImageSummary,
  type LabelingStats,
} from "@/api/aiLabeling";
import { getTrainingJob, listTrainingJobs, type TrainingJob } from "@/api/aiTraining";
import { ensureAccessTokenFresh, formatApiErrorDetail } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

const { Title, Text, Paragraph } = Typography;
const BATCH_SIZE = 40;
const PAGE_SIZE = 24;

const STATUS_COLORS: Record<string, string> = {
  pending: "default",
  running: "processing",
  succeeded: "success",
  failed: "error",
};

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

function trainingJobPercent(job: TrainingJob): number {
  const total = job.total_epochs || job.epochs || 0;
  const current = job.current_epoch || 0;
  const running = job.status === "running" || job.status === "pending";
  const succeeded = job.status === "succeeded";
  const stage = job.stage || "";
  const imgTotal = job.images_total || 0;
  const imgDone = job.images_done || 0;

  if (succeeded) return 100;
  if (stage === "preparing" && imgTotal > 0) {
    return Math.max(5, Math.round((imgDone / imgTotal) * 15));
  }
  if (stage === "uploading") return 97;
  if (total > 0 && current > 0) {
    return 15 + Math.min(80, Math.round((current / total) * 80));
  }
  if (running) return 5;
  return 0;
}

export default function AiLabelingPage() {
  const { message } = App.useApp();
  const { user } = useAuth();
  const [products, setProducts] = useState<Product[]>([]);
  const [stats, setStats] = useState<LabelingStats | null>(null);
  const [items, setItems] = useState<LabelImageSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState<"all" | "pending" | "labeled" | "uncropped">("all");
  const [listSkuFilter, setListSkuFilter] = useState<string | null>(null);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [isCropped, setIsCropped] = useState(false);
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
  const [exporting, setExporting] = useState(false);
  const [exportMode, setExportMode] = useState<"crops" | "scenes">("crops");
  const [editorMode, setEditorMode] = useState<EditorMode>("label");
  const [labelTool, setLabelTool] = useState<LabelTool>("rect");
  const [cropRect, setCropRect] = useState<CropRect | null>(null);
  const [cropping, setCropping] = useState(false);
  const [activeJob, setActiveJob] = useState<TrainingJob | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);
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
  }, [message, selectedProductId]);

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
      const cropped = filter === "uncropped" ? false : undefined;
      const res = await listLabelImages({
        skip: page * PAGE_SIZE,
        limit: PAGE_SIZE,
        labeled,
        cropped,
        product_id: listSkuFilter ?? undefined,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (e: unknown) {
      message.error(
        formatApiErrorDetail(
          e,
          "Không tải được danh sách ảnh — chạy migration DB nếu vừa deploy"
        )
      );
    } finally {
      setLoading(false);
    }
  }, [filter, listSkuFilter, message, page]);

  const loadImage = useCallback(
    async (id: string) => {
      setLoading(true);
      try {
        const detail = await getLabelImage(id);
        setCurrentId(id);
        setPreviewUrl(detail.preview_url);
        setIsCropped(detail.is_cropped);
        setEditorMode(detail.is_cropped ? "label" : "crop");
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
        setCropRect(null);
      } catch {
        message.error("Không tải được ảnh");
      } finally {
        setLoading(false);
      }
    },
    [message, productById]
  );

  useEffect(() => {
    if (!user) return;
    void loadProducts();
    void refreshStats();
  }, [user, loadProducts, refreshStats]);

  useEffect(() => {
    if (!user) return;
    void loadList();
  }, [user, loadList]);

  useEffect(() => {
    setCurrentId(null);
  }, [page, filter, listSkuFilter]);

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
      const saved = await saveLabelBoxes(
        currentId,
        boxes.map((b) => draftToYolo(b))
      );
      setBoxes(
        saved.map((b) =>
          yoloToDraft(
            b,
            b.sku ?? productById.get(b.product_id)?.sku ?? "?",
            b.product_name ?? productById.get(b.product_id)?.name ?? "?"
          )
        )
      );
      setSelectedBoxId(null);
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

  const applyCrop = async () => {
    if (!currentId || !cropRect) return;
    if (dirty) {
      const ok = await saveCurrent();
      if (!ok) return;
    }
    setCropping(true);
    try {
      const detail = await cropLabelImage(currentId, cropRect);
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
      setCropRect(null);
      setEditorMode("label");
      setIsCropped(true);
      setDirty(false);
      message.success("Đã cắt và lưu đè ảnh gốc");
      await refreshStats();
      await loadList();
    } catch (e: unknown) {
      const detail =
        e && typeof e === "object" && "response" in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      message.error(typeof detail === "string" ? detail : "Cắt ảnh thất bại");
    } finally {
      setCropping(false);
    }
  };

  const skipCrop = async () => {
    if (!currentId || isCropped) return;
    try {
      await markLabelImageCropped(currentId);
      setIsCropped(true);
      setEditorMode("label");
      message.success("Đã đánh dấu ảnh không cần cắt — có thể gán nhãn");
      await refreshStats();
      await loadList();
    } catch (e: unknown) {
      const detail =
        e && typeof e === "object" && "response" in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : undefined;
      message.error(typeof detail === "string" ? detail : "Thao tác thất bại");
    }
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
      await ensureAccessTokenFresh();
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
  }, [loadList, message, refreshStats]);

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

  const handleExportLabels = async (productId?: string | null) => {
    setExporting(true);
    try {
      await exportLabelImages({
        mode: exportMode,
        productId: productId ?? undefined,
      });
      message.success(
        productId
          ? "Đã tải ZIP ảnh gán nhãn của SKU đang chọn"
          : "Đã tải ZIP ảnh gán nhãn theo sản phẩm"
      );
    } catch (e: unknown) {
      message.error(formatApiErrorDetail(e, "Export ảnh gán nhãn thất bại"));
    } finally {
      setExporting(false);
    }
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
      startJobPolling(job.id);
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "Không tạo được job");
    } finally {
      setTraining(false);
    }
  };

  const startJobPolling = useCallback((jobId: string) => {
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const j = await getTrainingJob(jobId);
        setActiveJob(j);
        if (j.status === "succeeded" || j.status === "failed") {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        /* poll retry next tick */
      }
    }, 3000);
  }, []);

  useEffect(() => {
    if (!user) return;
    void (async () => {
      try {
        const { items } = await listTrainingJobs();
        const running = items.find(
          (j) =>
            (j.status === "running" || j.status === "pending") &&
            j.class_map &&
            typeof j.class_map === "object" &&
            (j.class_map as { mode?: string }).mode === "labeled_scenes"
        );
        if (running) {
          const fresh = await getTrainingJob(running.id);
          setActiveJob(fresh);
          startJobPolling(running.id);
        }
      } catch {
        /* optional resume */
      }
    })();
  }, [startJobPolling, user]);

  useEffect(
    () => () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (uploadTimerRef.current) window.clearTimeout(uploadTimerRef.current);
    },
    []
  );

  useEffect(() => {
    const running =
      activeJob?.status === "running" || activeJob?.status === "pending";
    if (!running) return;
    const tick = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(tick);
  }, [activeJob?.status]);

  return (
    <div>
      <Title level={3}>Gán nhãn bbox theo SKU</Title>
      <Paragraph type="secondary">
        Upload ảnh cảnh (nhiều sản phẩm/khung). <strong>Cắt ảnh</strong> bỏ vùng thừa trước,
        sau đó gán nhãn bbox theo SKU. Phím tắt: ← → chuyển ảnh, Delete xóa khung, Ctrl+S
        lưu.
      </Paragraph>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={5}>
          <Card title="Thống kê" size="small">
            {stats && (
              <>
                <Statistic title="Tổng ảnh" value={stats.total_images} />
                <Statistic title="Đã gán nhãn" value={stats.labeled_images} />
                <Statistic title="Chưa cắt" value={stats.pending_crop} />
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
                <Space direction="vertical" style={{ width: "100%", marginTop: 12 }} size={8}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    Export ZIP theo thư mục SKU
                  </Text>
                  <Segmented
                    block
                    value={exportMode}
                    onChange={(v) => setExportMode(v as "crops" | "scenes")}
                    options={[
                      { label: "Cắt bbox", value: "crops" },
                      { label: "Ảnh cảnh", value: "scenes" },
                    ]}
                  />
                  <Button
                    block
                    icon={<DownloadOutlined />}
                    loading={exporting}
                    disabled={(stats.total_boxes ?? 0) === 0}
                    onClick={() => void handleExportLabels()}
                  >
                    Export tất cả SKU
                  </Button>
                  <Button
                    block
                    icon={<DownloadOutlined />}
                    loading={exporting}
                    disabled={!selectedProductId}
                    onClick={() => void handleExportLabels(selectedProductId)}
                  >
                    Export SKU đang chọn
                  </Button>
                </Space>
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
        </Col>

        <Col xs={24} lg={13}>
          <Card
            title={
              currentId
                ? `Ảnh ${currentIndex + 1 + page * PAGE_SIZE}/${total}`
                : "Chưa có ảnh"
            }
            extra={
              <Space wrap>
                <Button
                  type={editorMode === "crop" ? "primary" : "default"}
                  icon={<ScissorOutlined />}
                  disabled={!currentId || (editorMode === "crop" && !isCropped)}
                  onClick={() => {
                    if (editorMode === "crop") {
                      if (!isCropped) return;
                      setEditorMode("label");
                    } else {
                      setEditorMode("crop");
                    }
                    setCropRect(null);
                    setSelectedBoxId(null);
                  }}
                >
                  {editorMode === "crop" ? "Gán nhãn" : "Cắt ảnh"}
                </Button>
                {editorMode === "label" && isCropped && (
                  <Segmented
                    value={labelTool}
                    onChange={(v) => setLabelTool(v as LabelTool)}
                    options={[
                      { label: "Kéo vuông", value: "rect" },
                      { label: "Chấm điểm", value: "polygon" },
                    ]}
                  />
                )}
                {editorMode === "crop" && (
                  <>
                    <Button
                      type="primary"
                      icon={<ScissorOutlined />}
                      loading={cropping}
                      disabled={!cropRect}
                      onClick={() => void applyCrop()}
                    >
                      Áp dụng cắt
                    </Button>
                    {!isCropped && (
                      <Button onClick={() => void skipCrop()}>Bỏ qua cắt</Button>
                    )}
                  </>
                )}
                <Button icon={<LeftOutlined />} onClick={() => void goPrev()} />
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  loading={saving}
                  disabled={editorMode === "crop" || !isCropped}
                  onClick={() => void saveCurrent()}
                >
                  Lưu
                </Button>
                <Button icon={<RightOutlined />} onClick={() => void goNext()} />
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!selectedBoxId || editorMode === "crop" || !isCropped}
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
              mode={editorMode}
              labelTool={labelTool}
              cropRect={cropRect}
              onCropRectChange={setCropRect}
              labelingEnabled={isCropped}
            />
            {!isCropped && (
              <Alert
                type="warning"
                showIcon
                message="Ảnh chưa cắt — cắt vùng thừa hoặc bấm Bỏ qua cắt trước khi gán nhãn bbox."
                style={{ marginTop: 8 }}
              />
            )}
            {editorMode === "crop" && cropRect && (
              <Alert
                type="warning"
                showIcon
                message="Vùng cam = phần giữ lại. Bbox ngoài vùng sẽ bị cắt hoặc xóa."
                style={{ marginTop: 8 }}
              />
            )}
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
              Yêu cầu: ≥10 ảnh đã gán bbox, ≥2 SKU, mỗi SKU ≥5 bbox. Job này
              tự kèm ảnh crop từ trang Train AI / duyệt dữ liệu vào cùng một
              weight — triển khai weight đó cho quầy (chỉ chọn được 1 model).
            </Paragraph>
            {activeJob && (
              <Space direction="vertical" style={{ width: "100%", marginTop: 12 }} size={10}>
                <Descriptions
                  size="small"
                  column={1}
                  items={[
                    {
                      key: "status",
                      label: "Trạng thái",
                      children: (
                        <Tag color={STATUS_COLORS[activeJob.status] || "default"}>
                          {activeJob.status}
                        </Tag>
                      ),
                    },
                    { key: "name", label: "Tên job", children: activeJob.name },
                  ]}
                />
                {(() => {
                  const total = activeJob.total_epochs || activeJob.epochs || 0;
                  const current = activeJob.current_epoch || 0;
                  const running =
                    activeJob.status === "running" || activeJob.status === "pending";
                  const succeeded = activeJob.status === "succeeded";
                  const stage = activeJob.stage || "";
                  const imgTotal = activeJob.images_total || 0;
                  const imgDone = activeJob.images_done || 0;
                  const percent = trainingJobPercent(activeJob);
                  const startTs = activeJob.started_at_ts || 0;
                  const endTs = activeJob.finished_at_ts || 0;
                  const elapsed = startTs ? (endTs > 0 ? endTs : now) - startTs : 0;
                  const eta =
                    running && current > 0 && total > 0 && elapsed > 0
                      ? (elapsed / current) * (total - current)
                      : 0;
                  return (
                    <>
                      <Progress
                        percent={percent}
                        status={
                          activeJob.status === "failed"
                            ? "exception"
                            : succeeded
                              ? "success"
                              : "active"
                        }
                      />
                      <Row gutter={8}>
                        <Col span={8}>
                          <Statistic
                            title="Epoch"
                            value={total > 0 ? `${current}/${total}` : "—"}
                          />
                        </Col>
                        <Col span={8}>
                          <Statistic
                            title="Đã chạy"
                            value={startTs ? formatDuration(elapsed) : "—"}
                          />
                        </Col>
                        <Col span={8}>
                          <Statistic
                            title="Còn lại (ước tính)"
                            value={eta > 0 ? formatDuration(eta) : "—"}
                          />
                        </Col>
                      </Row>
                      {activeJob.progress && (
                        <Text type="secondary">{activeJob.progress}</Text>
                      )}
                      {stage === "preparing" && imgTotal > 0 && (
                        <Text type="secondary" style={{ display: "block" }}>
                          Đã tải {imgDone}/{imgTotal} ảnh huấn luyện
                        </Text>
                      )}
                      {activeJob.class_counts &&
                        Object.keys(activeJob.class_counts).length > 0 && (
                          <Space wrap size={4}>
                            {Object.entries(activeJob.class_counts).map(([cls, n]) => (
                              <Tag key={cls} color="blue">
                                {cls}: {n}
                              </Tag>
                            ))}
                          </Space>
                        )}
                    </>
                  );
                })()}
                {activeJob.status === "failed" && activeJob.error_message && (
                  <Alert type="error" message={activeJob.error_message} />
                )}
                {activeJob.status === "succeeded" && (
                  <Alert
                    type="success"
                    message="Huấn luyện xong"
                    description={
                      <>
                        Weight: {activeJob.weight_key || "—"}.{" "}
                        <Link to="/ai-training">Deploy tại Train AI →</Link>
                      </>
                    }
                  />
                )}
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      <Card
        title={`Thư viện ảnh (${total})`}
        size="small"
        style={{ marginTop: 16 }}
        extra={
          <Space wrap size={8}>
            <Select
              allowClear
              showSearch
              placeholder="Lọc theo SKU"
              style={{ minWidth: 220 }}
              value={listSkuFilter ?? undefined}
              optionFilterProp="label"
              onChange={(v) => {
                setListSkuFilter(v ?? null);
                setPage(0);
                if (v) setSelectedProductId(v);
              }}
              options={products.map((p) => ({
                value: p.id,
                label: `${p.sku} — ${p.name}`,
              }))}
            />
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
            <Tag
              color={filter === "uncropped" ? "orange" : "default"}
              style={{ cursor: "pointer" }}
              onClick={() => {
                setFilter("uncropped");
                setPage(0);
              }}
            >
              Chưa cắt
            </Tag>
          </Space>
        }
      >
        <LabelImageGrid
          items={items}
          currentId={currentId}
          loading={loading}
          onSelect={(id) => void loadImage(id)}
        />
        <Space style={{ marginTop: 12 }}>
          <Button size="small" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
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
        <Text type="secondary" style={{ display: "block", marginTop: 8, fontSize: 12 }}>
          Lọc SKU → chỉ hiện ảnh có nhãn SKU đó · ✂ cam = chưa cắt · số xanh = số bbox · bấm ô ảnh
          để mở cắt/gán nhãn
        </Text>
      </Card>
    </div>
  );
}
