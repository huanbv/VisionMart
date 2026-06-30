import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import {
  HistoryOutlined,
  PlusOutlined,
  SettingOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { listBranches, type Branch } from "@/api/tenancy";
import { listProducts, type Product } from "@/api/catalog";
import {
  adjustInventory,
  type InventoryRow,
  listInventory,
  listMovements,
  type MovementType,
  type StockMovement,
  transferInventory,
  updateReorderLevel,
} from "@/api/inventory";
import { useAuth } from "@/contexts/AuthContext";

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);
const PAGE_SIZE = 20;

const MOVEMENT_LABEL: Record<MovementType, string> = {
  in: "Nhập kho",
  out: "Xuất kho",
  adjust: "Điều chỉnh",
  transfer_in: "Chuyển đến",
  transfer_out: "Chuyển đi",
};

interface AdjustFormValues {
  product_id: string;
  branch_id: string;
  movement_type: MovementType;
  quantity: number;
  reason: string;
  reference: string;
}

interface TransferFormValues {
  product_id: string;
  from_branch_id: string;
  to_branch_id: string;
  quantity: number;
  reason: string;
  reference: string;
}

export default function InventoryPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<InventoryRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [branchFilter, setBranchFilter] = useState<string | undefined>(undefined);
  const [lowOnly, setLowOnly] = useState(false);
  const [loading, setLoading] = useState(false);

  const [branches, setBranches] = useState<Branch[]>([]);
  const [products, setProducts] = useState<Product[]>([]);

  const [adjustOpen, setAdjustOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);
  const [reorderOpen, setReorderOpen] = useState<InventoryRow | null>(null);
  const [reorderValue, setReorderValue] = useState(0);
  const [movementsRow, setMovementsRow] = useState<InventoryRow | null>(null);
  const [movements, setMovements] = useState<StockMovement[]>([]);
  const [movementsLoading, setMovementsLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [adjustForm] = Form.useForm<AdjustFormValues>();
  const [transferForm] = Form.useForm<TransferFormValues>();

  const load = async () => {
    setLoading(true);
    try {
      const res = await listInventory({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
        branch_id: branchFilter,
        low_stock: lowOnly,
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được tồn kho");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    listBranches({ limit: 200 })
      .then((res) => setBranches(res.items))
      .catch(() => message.error("Không tải được chi nhánh"));
    listProducts({ limit: 500 })
      .then((res) => setProducts(res.items))
      .catch(() => message.error("Không tải được sản phẩm"));
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, branchFilter, lowOnly]);

  const productOptions = useMemo(
    () => products.map((p) => ({ value: p.id, label: `${p.sku} — ${p.name}` })),
    [products],
  );
  const branchOptions = useMemo(
    () => branches.map((b) => ({ value: b.id, label: `${b.code} — ${b.name}` })),
    [branches],
  );

  const openAdjust = () => {
    adjustForm.resetFields();
    adjustForm.setFieldsValue({ movement_type: "in", quantity: 1 });
    setAdjustOpen(true);
  };

  const onAdjust = async (values: AdjustFormValues) => {
    setSaving(true);
    try {
      const sign = values.movement_type === "out" ? -1 : 1;
      const delta =
        values.movement_type === "adjust"
          ? values.quantity
          : sign * Math.abs(values.quantity);
      await adjustInventory({
        product_id: values.product_id,
        branch_id: values.branch_id,
        delta,
        movement_type: values.movement_type,
        reason: values.reason || null,
        reference: values.reference || null,
      });
      message.success("Đã cập nhật tồn kho");
      setAdjustOpen(false);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      message.error(typeof detail === "string" ? detail : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const openTransfer = () => {
    transferForm.resetFields();
    transferForm.setFieldsValue({ quantity: 1 });
    setTransferOpen(true);
  };

  const onTransfer = async (values: TransferFormValues) => {
    if (values.from_branch_id === values.to_branch_id) {
      message.error("Chi nhánh nguồn và đích phải khác nhau");
      return;
    }
    setSaving(true);
    try {
      await transferInventory({
        product_id: values.product_id,
        from_branch_id: values.from_branch_id,
        to_branch_id: values.to_branch_id,
        quantity: values.quantity,
        reason: values.reason || null,
        reference: values.reference || null,
      });
      message.success("Đã chuyển kho");
      setTransferOpen(false);
      load();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
      message.error(typeof detail === "string" ? detail : "Chuyển kho thất bại");
    } finally {
      setSaving(false);
    }
  };

  const openReorder = (row: InventoryRow) => {
    setReorderValue(row.reorder_level);
    setReorderOpen(row);
  };

  const saveReorder = async () => {
    if (!reorderOpen) return;
    setSaving(true);
    try {
      await updateReorderLevel(reorderOpen.id, reorderValue);
      message.success("Đã cập nhật ngưỡng cảnh báo");
      setReorderOpen(null);
      load();
    } catch {
      message.error("Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const openMovements = async (row: InventoryRow) => {
    setMovementsRow(row);
    setMovementsLoading(true);
    try {
      const res = await listMovements(row.id, { limit: 100 });
      setMovements(res.items);
    } catch {
      message.error("Không tải được lịch sử");
    } finally {
      setMovementsLoading(false);
    }
  };

  const columns: ColumnsType<InventoryRow> = [
    { title: "SKU", dataIndex: "product_sku", width: 130 },
    { title: "Sản phẩm", dataIndex: "product_name" },
    { title: "Chi nhánh", dataIndex: "branch_name", width: 180 },
    {
      title: "Tồn",
      dataIndex: "quantity",
      width: 90,
      align: "right",
    },
    {
      title: "Giữ chỗ",
      dataIndex: "reserved_quantity",
      width: 100,
      align: "right",
    },
    {
      title: "Khả dụng",
      dataIndex: "available_quantity",
      width: 100,
      align: "right",
    },
    {
      title: "Ngưỡng",
      dataIndex: "reorder_level",
      width: 90,
      align: "right",
      render: (v: number) => (v > 0 ? v : "—"),
    },
    {
      title: "Trạng thái",
      dataIndex: "low_stock",
      width: 130,
      render: (v: boolean) =>
        v ? <Tag color="red">Thấp</Tag> : <Tag color="green">OK</Tag>,
    },
    {
      title: "Hành động",
      width: 130,
      fixed: "right",
      render: (_, row) => (
        <Space>
          <Button
            size="small"
            icon={<HistoryOutlined />}
            onClick={() => openMovements(row)}
          />
          <Button
            size="small"
            icon={<SettingOutlined />}
            disabled={!canEdit}
            onClick={() => openReorder(row)}
          />
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="Tồn kho"
      extra={
        <Space>
          <Input.Search
            placeholder="Tìm SKU/tên/barcode"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setSearch(v);
            }}
            style={{ width: 240 }}
          />
          <Select
            allowClear
            placeholder="Lọc chi nhánh"
            style={{ width: 200 }}
            options={branchOptions}
            value={branchFilter}
            onChange={(v) => {
              setPage(1);
              setBranchFilter(v);
            }}
          />
          <Space size={4}>
            <Switch
              checked={lowOnly}
              onChange={(v) => {
                setPage(1);
                setLowOnly(v);
              }}
            />
            <span>Chỉ tồn thấp</span>
          </Space>
          {canEdit && (
            <>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={openAdjust}
              >
                Nhập/Xuất
              </Button>
              <Button icon={<SwapOutlined />} onClick={openTransfer}>
                Chuyển kho
              </Button>
            </>
          )}
        </Space>
      }
    >
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          onChange: setPage,
          showSizeChanger: false,
        }}
        scroll={{ x: 1200 }}
      />

      <Drawer
        title="Điều chỉnh tồn kho"
        open={adjustOpen}
        onClose={() => setAdjustOpen(false)}
        width={460}
        destroyOnClose
      >
        <Form form={adjustForm} layout="vertical" onFinish={onAdjust}>
          <Form.Item
            label="Loại"
            name="movement_type"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: "in", label: "Nhập kho (+)" },
                { value: "out", label: "Xuất kho (−)" },
                { value: "adjust", label: "Điều chỉnh (delta)" },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="Sản phẩm"
            name="product_id"
            rules={[{ required: true }]}
          >
            <Select showSearch optionFilterProp="label" options={productOptions} />
          </Form.Item>
          <Form.Item
            label="Chi nhánh"
            name="branch_id"
            rules={[{ required: true }]}
          >
            <Select options={branchOptions} />
          </Form.Item>
          <Form.Item
            label="Số lượng (delta nếu Điều chỉnh, có thể âm)"
            name="quantity"
            rules={[{ required: true }]}
          >
            <InputNumber className="!w-full" />
          </Form.Item>
          <Form.Item label="Lý do" name="reason">
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item label="Mã tham chiếu" name="reference">
            <Input maxLength={120} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>
            Lưu
          </Button>
        </Form>
      </Drawer>

      <Drawer
        title="Chuyển kho giữa chi nhánh"
        open={transferOpen}
        onClose={() => setTransferOpen(false)}
        width={460}
        destroyOnClose
      >
        <Form form={transferForm} layout="vertical" onFinish={onTransfer}>
          <Form.Item
            label="Sản phẩm"
            name="product_id"
            rules={[{ required: true }]}
          >
            <Select showSearch optionFilterProp="label" options={productOptions} />
          </Form.Item>
          <Form.Item
            label="Từ chi nhánh"
            name="from_branch_id"
            rules={[{ required: true }]}
          >
            <Select options={branchOptions} />
          </Form.Item>
          <Form.Item
            label="Đến chi nhánh"
            name="to_branch_id"
            rules={[{ required: true }]}
          >
            <Select options={branchOptions} />
          </Form.Item>
          <Form.Item
            label="Số lượng"
            name="quantity"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} className="!w-full" />
          </Form.Item>
          <Form.Item label="Lý do" name="reason">
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item label="Mã tham chiếu" name="reference">
            <Input maxLength={120} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>
            Chuyển
          </Button>
        </Form>
      </Drawer>

      <Modal
        title="Ngưỡng cảnh báo tồn thấp"
        open={!!reorderOpen}
        onCancel={() => setReorderOpen(null)}
        onOk={saveReorder}
        confirmLoading={saving}
      >
        <p>
          {reorderOpen?.product_name} @ {reorderOpen?.branch_name}
        </p>
        <InputNumber
          min={0}
          value={reorderValue}
          onChange={(v) => setReorderValue(Number(v ?? 0))}
          className="!w-full"
        />
      </Modal>

      <Drawer
        title={`Lịch sử: ${movementsRow?.product_name ?? ""}`}
        open={!!movementsRow}
        onClose={() => setMovementsRow(null)}
        width={620}
      >
        <Table
          rowKey="id"
          loading={movementsLoading}
          dataSource={movements}
          pagination={false}
          size="small"
          columns={[
            {
              title: "Thời gian",
              dataIndex: "created_at",
              width: 170,
              render: (v: string) => new Date(v).toLocaleString(),
            },
            {
              title: "Loại",
              dataIndex: "movement_type",
              width: 120,
              render: (v: MovementType) => MOVEMENT_LABEL[v],
            },
            {
              title: "Δ",
              dataIndex: "delta",
              width: 70,
              align: "right",
              render: (v: number) => (
                <Tag color={v >= 0 ? "green" : "red"}>{v >= 0 ? `+${v}` : v}</Tag>
              ),
            },
            { title: "Sau", dataIndex: "quantity_after", width: 70, align: "right" },
            { title: "Lý do", dataIndex: "reason", render: (v) => v ?? "—" },
          ]}
        />
      </Drawer>
    </Card>
  );
}
