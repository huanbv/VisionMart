import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Image,
  InputNumber,
  Input,
  List,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from "antd";
import type { UploadProps } from "antd";
import {
  CloudUploadOutlined,
  DeleteOutlined,
  DownloadOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RocketOutlined,
} from "@ant-design/icons";

import { listProducts, type Product } from "@/api/catalog";
import {
  checkDeploy,
  createTrainingJob,
  deleteTrainingImage,
  deployTrainingJob,
  exportTrainingImages,
  getTrainingJob,
  listTrainingImages,
  listTrainingJobs,
  uploadTrainingImage,
  type TrainingImage,
  type TrainingJob,
} from "@/api/aiTraining";
import { formatApiErrorDetail } from "@/api/client";

const { Title, Text, Paragraph } = Typography;

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

export default function AiTrainingPage() {
  const { message } = App.useApp();
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
  const [images, setImages] = useState<TrainingImage[]>([]);
  const [imagesByProduct, setImagesByProduct] = useState<Record<string, number>>({});
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [activeJob, setActiveJob] = useState<TrainingJob | null>(null);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [loadingImages, setLoadingImages] = useState(false);
  const [training, setTraining] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [now, setNow] = useState<number>(() => Date.now() / 1000);
  const [deployBlocked, setDeployBlocked] = useState<{
    jobId: string;
    reason: string;
  } | null>(null);
  // Panel "Bước 3" nằm PHÍA TRÊN bảng lịch sử, nên bấm Xem ở bảng sẽ cập
  // nhật một khối đã trôi khỏi màn hình — nhìn ra là nút không có tác
  // dụng. Cuộn tới nơi vừa đổi mới cho thấy việc đã xảy ra.
  const statusCardRef = useRef<HTMLDivElement | null>(null);

  const selectJob = (row: TrainingJob) => {
    setActiveJob(row);
    // requestAnimationFrame: cuộn sau khi React đã vẽ lại, nếu không sẽ
    // cuộn tới vị trí cũ của khối trước khi nó đổi kích thước.
    requestAnimationFrame(() =>
      statusCardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  };

  const [form] = Form.useForm<{
    name: string;
    product_ids: string[];
    epochs: number;
    image_size: number;
  }>();

  const loadProducts = async () => {
    setLoadingProducts(true);
    try {
      const res = await listProducts({ limit: 200, is_active: true });
      setProducts(res.items);
      if (res.items.length && !selectedProductId) {
        setSelectedProductId(res.items[0].id);
      }
    } catch (err) {
      console.error(err);
      message.error("Không tải được sản phẩm");
    } finally {
      setLoadingProducts(false);
    }
  };

  const loadAllCounts = async () => {
    try {
      const all = await listTrainingImages();
      const counts: Record<string, number> = {};
      for (const item of all.items) {
        counts[item.product_id] = (counts[item.product_id] ?? 0) + 1;
      }
      setImagesByProduct(counts);
    } catch (err) {
      console.error(err);
    }
  };

  const loadImages = async (productId: string | null) => {
    if (!productId) {
      setImages([]);
      return;
    }
    setLoadingImages(true);
    try {
      const res = await listTrainingImages(productId);
      setImages(res.items);
    } catch (err) {
      console.error(err);
      message.error("Không tải được ảnh training");
    } finally {
      setLoadingImages(false);
    }
  };

  const loadJobs = async () => {
    try {
      const res = await listTrainingJobs();
      setJobs(res.items);
      const running = res.items.find(
        (j) => j.status === "pending" || j.status === "running"
      );
      if (running) setActiveJob(running);
      else if (res.items[0]) setActiveJob(res.items[0]);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    void loadProducts();
    void loadJobs();
    void loadAllCounts();
  }, []);

  useEffect(() => {
    void loadImages(selectedProductId);
  }, [selectedProductId]);

  useEffect(() => {
    if (!activeJob) return;
    if (activeJob.status !== "pending" && activeJob.status !== "running") return;
    const timer = window.setInterval(async () => {
      try {
        const fresh = await getTrainingJob(activeJob.id);
        setActiveJob(fresh);
        setJobs((prev) =>
          prev.map((j) => (j.id === fresh.id ? fresh : j))
        );
      } catch (err) {
        console.error(err);
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [activeJob]);

  useEffect(() => {
    if (!activeJob) return;
    if (activeJob.status !== "pending" && activeJob.status !== "running") return;
    const tick = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(tick);
  }, [activeJob]);

  const uploadProps: UploadProps = useMemo(
    () => ({
      multiple: true,
      showUploadList: false,
      accept: "image/jpeg,image/png,image/webp",
      customRequest: async ({ file, onSuccess, onError }) => {
        if (!selectedProductId) {
          message.warning("Chọn sản phẩm trước khi tải ảnh");
          onError?.(new Error("no product"));
          return;
        }
        try {
          await uploadTrainingImage(selectedProductId, file as File);
          onSuccess?.({});
        } catch (err) {
          onError?.(err as Error);
        }
      },
      onChange: (info) => {
        const done = info.fileList.filter((f) => f.status === "done").length;
        const failed = info.fileList.filter((f) => f.status === "error").length;
        if (info.file.status === "done") {
          message.success(`Đã tải ${info.file.name}`);
          void loadImages(selectedProductId);
          void loadAllCounts();
        }
        if (info.file.status === "error") {
          message.error(`Lỗi tải ${info.file.name}`);
        }
        if (done + failed === info.fileList.length && info.fileList.length > 0) {
          // batch finished
        }
      },
    }),
    [selectedProductId]
  );

  const handleDeleteImage = async (imageId: string) => {
    try {
      await deleteTrainingImage(imageId);
      message.success("Đã xoá ảnh");
      void loadImages(selectedProductId);
      void loadAllCounts();
    } catch {
      message.error("Xoá thất bại");
    }
  };

  const handleStartTraining = async () => {
    try {
      const values = await form.validateFields();
      setTraining(true);
      const job = await createTrainingJob({
        name: values.name,
        product_ids: values.product_ids,
        epochs: values.epochs,
        image_size: values.image_size,
      });
      message.success("Đã khởi tạo job training");
      setActiveJob(job);
      void loadJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (detail) message.error(detail);
      else if (err?.errorFields) return;
      else message.error("Không tạo được job");
    } finally {
      setTraining(false);
    }
  };

  const handleExport = async (productId?: string | null) => {
    setExporting(true);
    try {
      await exportTrainingImages(productId ?? undefined);
      message.success(
        productId ? "Đã tải ZIP ảnh huấn luyện của SKU đang chọn" : "Đã tải ZIP tất cả ảnh huấn luyện"
      );
    } catch (err: unknown) {
      message.error(formatApiErrorDetail(err, "Export ảnh thất bại"));
    } finally {
      setExporting(false);
    }
  };

  const handleDeploy = async (jobId: string, force = false) => {
    try {
      if (!force) {
        const gate = await checkDeploy(jobId);
        if (!gate.allowed) {
          setDeployBlocked({ jobId, reason: gate.reason });
          return;
        }
      }
      const updated = await deployTrainingJob(jobId, force);
      message.success("Đã triển khai weight mới cho AI");
      setActiveJob(updated);
      setDeployBlocked(null);
      void loadJobs();
    } catch (err: unknown) {
      const detail =
        err &&
        typeof err === "object" &&
        "response" in err &&
        (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
      const text = typeof detail === "string" ? detail : "Triển khai thất bại";
      if (!force && typeof detail === "string" && detail.includes("Blocked:")) {
        setDeployBlocked({ jobId, reason: detail });
        return;
      }
      message.error(text);
    }
  };

  const productOptions = products.map((p) => ({
    value: p.id,
    label: `${p.sku} — ${p.name} (${imagesByProduct[p.id] ?? 0} ảnh)`,
  }));

  return (
    <div>
      <Title level={3}>Huấn luyện AI nhận diện sản phẩm</Title>
      <Paragraph type="secondary">
        Tải ít nhất 5 ảnh crop mỗi sản phẩm (khuyến nghị 20–50 ảnh, nhiều góc).
        Ảnh ở đây là cận cảnh 1 SKU — khi bấm <b>Train từ nhãn bbox</b> chúng
        được gộp vào cùng job với ảnh cảnh đã khoanh khung. Quầy live chỉ
        triển khai được 1 file .pt: hãy deploy weight train bbox (scene
        detector), không dùng weight train-crop-cả-khung từ nút bên dưới.
      </Paragraph>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="Hai nguồn dữ liệu, một weight triển khai"
        description="Gán nhãn bbox = ảnh cảnh nhiều sản phẩm. Train AI = crop 1 sản phẩm. Chỉ job “Train từ nhãn bbox” gộp cả hai. Nút train trên trang này chỉ học crop cả khung — dễ nhận nhầm mặt gỗ quầy trống."
      />

      <Row gutter={16}>
        <Col span={14}>
          <Card
            title="Bước 1 — Tải ảnh huấn luyện"
            extra={
              <Space wrap>
                <Button
                  icon={<DownloadOutlined />}
                  loading={exporting}
                  disabled={!selectedProductId}
                  onClick={() => void handleExport(selectedProductId)}
                >
                  Export SKU này
                </Button>
                <Button
                  icon={<DownloadOutlined />}
                  loading={exporting}
                  onClick={() => void handleExport()}
                >
                  Export tất cả
                </Button>
                <Button
                  icon={<ReloadOutlined />}
                  onClick={() => {
                    void loadProducts();
                    void loadAllCounts();
                  }}
                  loading={loadingProducts}
                >
                  Làm mới
                </Button>
              </Space>
            }
          >
            <Space direction="vertical" style={{ width: "100%" }} size={12}>
              <Select
                style={{ width: "100%" }}
                placeholder="Chọn sản phẩm"
                value={selectedProductId ?? undefined}
                onChange={setSelectedProductId}
                options={productOptions}
                loading={loadingProducts}
                showSearch
                optionFilterProp="label"
              />
              <Upload.Dragger {...uploadProps} disabled={!selectedProductId}>
                <p className="ant-upload-drag-icon">
                  <CloudUploadOutlined />
                </p>
                <p className="ant-upload-text">
                  Kéo thả hoặc bấm để tải ảnh JPG/PNG/WebP
                </p>
                <p className="ant-upload-hint">
                  Ảnh sẽ được gán cho sản phẩm đang chọn.
                </p>
              </Upload.Dragger>

              <List
                loading={loadingImages}
                grid={{ gutter: 8, column: 4 }}
                dataSource={images}
                locale={{ emptyText: <Empty description="Chưa có ảnh" /> }}
                renderItem={(item) => (
                  <List.Item>
                    <Card
                      size="small"
                      cover={
                        item.preview_url ? (
                          <Image
                            src={item.preview_url}
                            height={120}
                            style={{ objectFit: "cover" }}
                            preview
                          />
                        ) : null
                      }
                      actions={[
                        <Popconfirm
                          key="del"
                          title="Xoá ảnh này?"
                          onConfirm={() => handleDeleteImage(item.id)}
                        >
                          <DeleteOutlined />
                        </Popconfirm>,
                      ]}
                    >
                      <Text style={{ fontSize: 11 }} type="secondary">
                        {new Date(item.created_at).toLocaleDateString()}
                      </Text>
                    </Card>
                  </List.Item>
                )}
              />
            </Space>
          </Card>
        </Col>

        <Col span={10}>
          <Card title="Bước 2 — Khởi tạo Training" style={{ marginBottom: 16 }}>
            <Form
              form={form}
              layout="vertical"
              initialValues={{
                name: `training-${new Date().toISOString().slice(0, 10)}`,
                epochs: 30,
                image_size: 640,
                product_ids: [],
              }}
            >
              <Form.Item
                name="name"
                label="Tên job"
                rules={[{ required: true, message: "Nhập tên" }]}
              >
                <Input placeholder="training-2026-11-14" />
              </Form.Item>
              <Form.Item
                name="product_ids"
                label="Sản phẩm sẽ train"
                rules={[
                  { required: true, message: "Chọn tối thiểu 2 sản phẩm" },
                  {
                    validator: (_, v) =>
                      Array.isArray(v) && v.length >= 2
                        ? Promise.resolve()
                        : Promise.reject(new Error("Cần >=2 sản phẩm")),
                  },
                ]}
              >
                <Select
                  mode="multiple"
                  placeholder="Chọn 2+ sản phẩm"
                  options={productOptions}
                  optionFilterProp="label"
                />
              </Form.Item>
              <Row gutter={8}>
                <Col span={12}>
                  <Form.Item name="epochs" label="Epochs">
                    <InputNumber min={5} max={300} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="image_size" label="Image size">
                    <InputNumber min={320} max={1280} step={32} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
              </Row>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                onClick={handleStartTraining}
                loading={training}
                block
              >
                Bắt đầu Training
              </Button>
            </Form>
          </Card>

          <div ref={statusCardRef}>
          <Card title="Bước 3 — Trạng thái Training">
            {!activeJob && <Empty description="Chưa có job nào" />}
            {activeJob && (
              <Space direction="vertical" style={{ width: "100%" }} size={12}>
                <Descriptions
                  size="small"
                  column={1}
                  items={[
                    { key: "id", label: "Job ID", children: activeJob.id },
                    { key: "name", label: "Tên", children: activeJob.name },
                    {
                      key: "status",
                      label: "Trạng thái",
                      children: (
                        <Tag color={STATUS_COLORS[activeJob.status] || "default"}>
                          {activeJob.status}
                        </Tag>
                      ),
                    },
                    {
                      key: "weight",
                      label: "Weight",
                      children: activeJob.weight_key || "—",
                    },
                  ]}
                />
                {(() => {
                  const total = activeJob.total_epochs || activeJob.epochs || 0;
                  const current = activeJob.current_epoch || 0;
                  const running = activeJob.status === "running" || activeJob.status === "pending";
                  const succeeded = activeJob.status === "succeeded";
                  const stage = activeJob.stage || "";
                  const imgTotal = activeJob.images_total || 0;
                  const imgDone = activeJob.images_done || 0;

                  // Tiến độ tính theo giai đoạn đang chạy, không phải theo
                  // epoch suốt cả job. Trước đây lúc tải ảnh, epoch còn 0
                  // nên thanh đứng im ở 5% — người dùng không phân biệt
                  // được "đang tải" với "đã treo". Chuẩn bị dữ liệu chiếm
                  // 15% đầu vì nó thường nhanh hơn huấn luyện nhiều.
                  const percent = succeeded
                    ? 100
                    : stage === "preparing" && imgTotal > 0
                    ? // Sàn 5%: nếu để rơi về 0 khi chưa tải được ảnh nào,
                      // thanh sẽ TỤT LÙI so với trạng thái chờ trước đó —
                      // một thanh tiến độ đi ngược đọc ra là hỏng.
                      Math.max(5, Math.round((imgDone / imgTotal) * 15))
                    : stage === "uploading"
                    ? 97
                    : total > 0 && current > 0
                    ? 15 + Math.min(80, Math.round((current / total) * 80))
                    : running
                    ? 5
                    : 0;
                  const startTs = activeJob.started_at_ts || 0;
                  const endTs = activeJob.finished_at_ts || 0;
                  const elapsed = startTs
                    ? (endTs > 0 ? endTs : now) - startTs
                    : 0;
                  // ETA chỉ tính khi đã qua ít nhất một epoch, và suy từ
                  // nhịp epoch chứ không từ tổng thời gian đã trôi — nếu
                  // gộp cả giai đoạn tải ảnh vào thì ước lượng sẽ lệch
                  // hẳn ở những epoch đầu.
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
                          Đã tải {imgDone}/{imgTotal} ảnh
                        </Text>
                      )}
                      {activeJob.class_counts &&
                        Object.keys(activeJob.class_counts).length > 0 && (
                          <div style={{ marginTop: 8 }}>
                            <Text strong style={{ fontSize: 13 }}>
                              Ảnh theo lớp
                            </Text>
                            <Space wrap size={4} style={{ marginTop: 4 }}>
                              {Object.entries(activeJob.class_counts).map(
                                ([cls, n]) => (
                                  <Tag key={cls} color="blue">
                                    {cls}: {n}
                                  </Tag>
                                ),
                              )}
                            </Space>
                            {(activeJob.train_count || activeJob.val_count) && (
                              <Text
                                type="secondary"
                                style={{ display: "block", fontSize: 12 }}
                              >
                                Chia tập: {activeJob.train_count || 0} huấn
                                luyện / {activeJob.val_count || 0} kiểm tra
                              </Text>
                            )}
                          </div>
                        )}
                    </>
                  );
                })()}
                {activeJob.error_message && (
                  <Alert type="error" message={activeJob.error_message} />
                )}
                {activeJob.metrics && (
                  <Row gutter={8}>
                    {Object.entries(activeJob.metrics)
                      .slice(0, 4)
                      .map(([k, v]) => (
                        <Col span={12} key={k}>
                          <Statistic
                            title={k}
                            value={typeof v === "number" ? v.toFixed(3) : v}
                          />
                        </Col>
                      ))}
                  </Row>
                )}
                {activeJob.status === "succeeded" && activeJob.weight_key && (
                  <Space direction="vertical" style={{ width: "100%" }}>
                    {deployBlocked?.jobId === activeJob.id && (
                      <Alert
                        type="warning"
                        showIcon
                        message="Deploy bị chặn do metric giảm"
                        description={deployBlocked.reason}
                        action={
                          <Popconfirm
                            title="Triển khai dù metric thấp hơn model cũ?"
                            description="Chỉ dùng khi model mới (bbox cảnh) thay thế model full-frame cũ."
                            okText="Vẫn triển khai"
                            cancelText="Huỷ"
                            onConfirm={() => void handleDeploy(activeJob.id, true)}
                          >
                            <Button size="small" type="primary" danger>
                              Deploy bỏ qua cảnh báo
                            </Button>
                          </Popconfirm>
                        }
                      />
                    )}
                    <Button
                      type="primary"
                      icon={<RocketOutlined />}
                      block
                      onClick={() => void handleDeploy(activeJob.id)}
                    >
                      Triển khai weight cho AI Engine
                    </Button>
                  </Space>
                )}
              </Space>
            )}
          </Card>
          </div>
        </Col>
      </Row>

      <Card title="Lịch sử job" style={{ marginTop: 16 }}>
        <Table
          rowKey="id"
          size="small"
          dataSource={jobs}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: "Tên", dataIndex: "name" },
            {
              title: "Trạng thái",
              dataIndex: "status",
              render: (v: string) => (
                <Tag color={STATUS_COLORS[v] || "default"}>{v}</Tag>
              ),
            },
            {
              title: "Tiến độ",
              key: "progress",
              render: (_, row) => {
                const total = row.total_epochs || row.epochs || 0;
                const current = row.current_epoch || 0;
                const stage = row.stage || "";
                const imgTotal = row.images_total || 0;
                const imgDone = row.images_done || 0;

                let percent = 0;
                if (row.status === "succeeded") {
                  percent = 100;
                } else if (row.status === "failed") {
                  percent = 0;
                } else if (stage === "preparing" && imgTotal > 0) {
                  percent = Math.max(5, Math.round((imgDone / imgTotal) * 15));
                } else if (stage === "uploading") {
                  percent = 97;
                } else if (total > 0 && current > 0) {
                  percent = 15 + Math.min(80, Math.round((current / total) * 80));
                } else if (row.status === "running" || row.status === "pending") {
                  percent = 5;
                }

                if (row.status === "succeeded") {
                  return <Progress percent={100} size="small" />;
                }
                if (row.status === "failed") {
                  return <Progress percent={100} status="exception" size="small" />;
                }
                if (row.status === "running" || row.status === "pending") {
                  return (
                    <div style={{ width: 140 }}>
                      <Progress percent={percent} size="small" status="active" />
                      <div style={{ fontSize: 10, color: "#8c8c8c", marginTop: -2 }}>
                        {stage === "preparing" ? "Chuẩn bị..." : `Epoch: ${current}/${total}`}
                      </div>
                    </div>
                  );
                }
                return "—";
              }
            },
            { title: "Epochs", dataIndex: "epochs" },
            {
              title: "Tạo lúc",
              dataIndex: "created_at",
              render: (v: string) => new Date(v).toLocaleString(),
            },
            { title: "Weight", dataIndex: "weight_key", render: (v) => v || "—" },
            {
              title: "",
              render: (_, row) => (
                <Space>
                  <Button
                    size="small"
                    type={activeJob?.id === row.id ? "primary" : "default"}
                    onClick={() => selectJob(row)}
                  >
                    {activeJob?.id === row.id ? "Đang xem" : "Xem"}
                  </Button>
                  {row.status === "succeeded" && row.weight_key ? (
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => handleDeploy(row.id)}
                    >
                      Triển khai
                    </Button>
                  ) : (
                    // Nút bị ẩn hoàn toàn khiến người dùng tưởng chức năng
                    // hỏng. Hiện nút mờ kèm lý do thì rõ là "chưa đủ điều
                    // kiện", không phải "bấm không ăn".
                    <Tooltip
                      title={
                        row.status !== "succeeded"
                          ? `Chỉ triển khai được job đã thành công (hiện: ${row.status})`
                          : "Job này không có file weight"
                      }
                    >
                      <Button size="small" disabled>
                        Triển khai
                      </Button>
                    </Tooltip>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
