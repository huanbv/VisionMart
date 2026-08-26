import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AutoComplete,
  Button,
  Card,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  PlusOutlined,
  ReloadOutlined,
  SaveOutlined,
} from "@ant-design/icons";

import {
  getClassSkuMap,
  listModels,
  updateClassSkuMap,
  updateVisionConfig,
} from "@/api/aiReview";

const { Paragraph, Text } = Typography;

/**
 * Product recognition settings — the two knobs that turn "YOLO detected
 * something" into "an order line", both editable here instead of in files:
 *
 *  • Class → SKU mapping (Phương án A): map the class name the detector
 *    actually emits (a COCO name like "bottle", or a custom-trained class)
 *    to a real SKU. This is what makes an uploaded product photo create an
 *    order with the stock model, no training required.
 *
 *  • Detection model (Phương án C): switch the YOLO weight the detector
 *    loads — stock COCO vs. a custom weight dropped into /models — applied
 *    live via YOLO_MODEL_PATH (no container restart).
 */

interface Row {
  id: number;
  className: string;
  sku: string;
}

const STOCK = "__stock__";

let _rid = 1;
const nextId = () => _rid++;

export default function ProductRecognitionCard() {
  const [rows, setRows] = useState<Row[]>([]);
  const [cocoClasses, setCocoClasses] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingMap, setSavingMap] = useState(false);

  const [models, setModels] = useState<string[]>([]);
  const [activeModel, setActiveModel] = useState<string>("");
  const [modelDraft, setModelDraft] = useState<string>(STOCK);
  const [savingModel, setSavingModel] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [map, mdl] = await Promise.all([getClassSkuMap(), listModels()]);
      setRows(
        Object.entries(map.mapping).map(([className, sku]) => ({
          id: nextId(),
          className,
          sku,
        })),
      );
      setCocoClasses(map.coco_classes ?? []);
      setModels(mdl.models ?? []);
      setActiveModel(mdl.active ?? "");
      setModelDraft(mdl.active ? mdl.active : STOCK);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Không tải được cấu hình nhận diện";
      message.error(detail);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const addRow = () =>
    setRows((r) => [...r, { id: nextId(), className: "", sku: "" }]);
  const removeRow = (id: number) =>
    setRows((r) => r.filter((row) => row.id !== id));
  const setRow = (id: number, patch: Partial<Row>) =>
    setRows((r) => r.map((row) => (row.id === id ? { ...row, ...patch } : row)));

  const saveMap = async () => {
    const mapping: Record<string, string> = {};
    for (const row of rows) {
      const c = row.className.trim();
      const s = row.sku.trim();
      if (c && s) mapping[c] = s;
    }
    setSavingMap(true);
    try {
      const res = await updateClassSkuMap(mapping);
      setRows(
        Object.entries(res.mapping).map(([className, sku]) => ({
          id: nextId(),
          className,
          sku,
        })),
      );
      message.success(
        `Đã lưu ${Object.keys(res.mapping).length} ánh xạ — áp dụng ngay`,
      );
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Lưu ánh xạ thất bại";
      message.error(detail);
    } finally {
      setSavingMap(false);
    }
  };

  const saveModel = async () => {
    const value = modelDraft === STOCK ? "" : modelDraft;
    setSavingModel(true);
    try {
      // Persisted like any other vision override; the tracker hot-swaps the
      // weight within ~1s (person_tracker._get_det_model).
      await updateVisionConfig({ YOLO_MODEL_PATH: value });
      setActiveModel(value);
      message.success(
        value
          ? `Đã chuyển sang model: ${value}`
          : "Đã dùng model mặc định (yolov8n COCO)",
      );
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Đổi model thất bại";
      message.error(detail);
    } finally {
      setSavingModel(false);
    }
  };

  const classOptions = useMemo(
    () => cocoClasses.map((c) => ({ value: c })),
    [cocoClasses],
  );

  const modelChanged = (modelDraft === STOCK ? "" : modelDraft) !== activeModel;

  const columns: ColumnsType<Row> = [
    {
      title: "Lớp phát hiện (YOLO)",
      dataIndex: "className",
      key: "className",
      render: (_: unknown, row: Row) => (
        <AutoComplete
          style={{ width: "100%", minWidth: 180 }}
          value={row.className}
          options={classOptions}
          placeholder="vd: bottle, cup, drk_001…"
          filterOption={(input, option) =>
            String(option?.value ?? "")
              .toLowerCase()
              .includes(input.toLowerCase())
          }
          onChange={(v) => setRow(row.id, { className: v })}
        />
      ),
    },
    {
      title: "Mã SKU",
      dataIndex: "sku",
      key: "sku",
      render: (_: unknown, row: Row) => (
        <Input
          style={{ minWidth: 140 }}
          value={row.sku}
          placeholder="vd: DRK-001"
          onChange={(e) => setRow(row.id, { sku: e.target.value })}
        />
      ),
    },
    {
      title: "",
      key: "action",
      width: 48,
      render: (_: unknown, row: Row) => (
        <Button
          type="text"
          danger
          icon={<DeleteOutlined />}
          onClick={() => removeRow(row.id)}
        />
      ),
    },
  ];

  return (
    <Card
      loading={loading}
      title={
        <Space size={6}>
          <Text strong>Nhận diện sản phẩm</Text>
          <Tag color="blue">Lớp → SKU</Tag>
        </Space>
      }
      extra={
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          Tải lại
        </Button>
      }
    >
      <Paragraph type="secondary" style={{ fontSize: 13 }}>
        Detector chỉ tạo được dòng đơn khi lớp nó phát hiện được ánh xạ sang một
        SKU. Với model COCO mặc định, sản phẩm thường ra lớp chung như{" "}
        <Text code>bottle</Text>, <Text code>cup</Text> — ánh xạ chúng sang SKU
        ở đây để quét ảnh tạo được đơn ngay, không cần huấn luyện.
      </Paragraph>

      {/* --- Phương án C: model selector --- */}
      <Card size="small" type="inner" title="Model phát hiện (YOLO)" style={{ marginBottom: 16 }}>
        <Space wrap align="center">
          <Select
            style={{ minWidth: 280 }}
            value={modelDraft}
            onChange={setModelDraft}
            options={[
              { value: STOCK, label: "Mặc định — yolov8n (COCO)" },
              ...models.map((m) => ({ value: m, label: m })),
            ]}
          />
          <Button
            type="primary"
            icon={<SaveOutlined />}
            loading={savingModel}
            disabled={!modelChanged}
            onClick={() => void saveModel()}
          >
            Áp dụng model
          </Button>
          {activeModel ? (
            <Tag color="green">Đang dùng: {activeModel}</Tag>
          ) : (
            <Tag>Đang dùng: mặc định COCO</Tag>
          )}
        </Space>
        <Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
          Chọn trọng số đã huấn luyện (đặt trong thư mục <Text code>/models</Text>)
          để detector xuất ra tên lớp sản phẩm của bạn. Đổi model có hiệu lực
          trong ~1 giây, không cần khởi động lại.
        </Paragraph>
      </Card>

      {/* --- Phương án A: class -> SKU table --- */}
      <Table
        size="small"
        rowKey="id"
        columns={columns}
        dataSource={rows}
        pagination={false}
        locale={{ emptyText: "Chưa có ánh xạ nào — bấm \"Thêm dòng\"" }}
      />
      <Space style={{ marginTop: 12 }}>
        <Button icon={<PlusOutlined />} onClick={addRow}>
          Thêm dòng
        </Button>
        <Popconfirm
          title="Lưu bảng ánh xạ?"
          description="Ghi đè toàn bộ ánh xạ Lớp → SKU của tổ chức này."
          onConfirm={() => void saveMap()}
          okText="Lưu"
          cancelText="Huỷ"
        >
          <Button type="primary" icon={<SaveOutlined />} loading={savingMap}>
            Lưu ánh xạ
          </Button>
        </Popconfirm>
      </Space>
    </Card>
  );
}
