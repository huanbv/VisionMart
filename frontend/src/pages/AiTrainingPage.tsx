import { useEffect, useMemo, useState } from "react";
import {
  Alert,
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
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadProps } from "antd";
import {
  CloudUploadOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  RocketOutlined,
} from "@ant-design/icons";

import { listProducts, type Product } from "@/api/catalog";
import {
  createTrainingJob,
  deleteTrainingImage,
  deployTrainingJob,
  getTrainingJob,
  listTrainingImages,
  listTrainingJobs,
  uploadTrainingImage,
  type TrainingImage,
  type TrainingJob,
} from "@/api/aiTraining";

const { Title, Text, Paragraph } = Typography;

const STATUS_COLORS: Record<string, string> = {
  pending: "default",
  running: "processing",
  succeeded: "success",
  failed: "error",
};

export default function AiTrainingPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
  const [images, setImages] = useState<TrainingImage[]>([]);
  const [imagesByProduct, setImagesByProduct] = useState<Record<string, number>>({});
  const [jobs, setJobs] = useState<TrainingJob[]>([]);
  const [activeJob, setActiveJob] = useState<TrainingJob | null>(null);
  const [loadingProducts, setLoadingProducts] = useState(false);
  const [loadingImages, setLoadingImages] = useState(false);
  const [training, setTraining] = useState(false);
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

  const handleDeploy = async (jobId: string) => {
    try {
      const updated = await deployTrainingJob(jobId);
      message.success("Đã triển khai weight mới cho AI");
      setActiveJob(updated);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(detail || "Triển khai thất bại");
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
        Tải ít nhất 5 ảnh mỗi sản phẩm (khuyến nghị 20–50 ảnh với nhiều góc chụp
        khác nhau). Chọn tối thiểu 2 sản phẩm để bắt đầu train.
      </Paragraph>

      <Row gutter={16}>
        <Col span={14}>
          <Card
            title="Bước 1 — Tải ảnh huấn luyện"
            extra={
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
                  <Button
                    type="primary"
                    icon={<RocketOutlined />}
                    block
                    onClick={() => handleDeploy(activeJob.id)}
                  >
                    Triển khai weight cho AI Engine
                  </Button>
                )}
              </Space>
            )}
          </Card>
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
                  <Button size="small" onClick={() => setActiveJob(row)}>
                    Xem
                  </Button>
                  {row.status === "succeeded" && row.weight_key && (
                    <Button
                      size="small"
                      type="primary"
                      onClick={() => handleDeploy(row.id)}
                    >
                      Triển khai
                    </Button>
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
