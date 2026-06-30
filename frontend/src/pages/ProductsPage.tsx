import { useEffect, useState } from "react";
import {
  Button,
  Card,
  Drawer,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  message,
} from "antd";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import {
  Category,
  createProduct,
  deleteProduct,
  listCategories,
  listProducts,
  Product,
  ProductPayload,
  updateProduct,
} from "@/api/catalog";
import { useAuth } from "@/contexts/AuthContext";

interface FormValues {
  sku: string;
  name: string;
  category_id: string | null;
  barcode: string | null;
  description: string | null;
  unit_price: number;
  currency: string;
  image_url: string | null;
  is_active: boolean;
  attributes_json?: string;
}

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);
const PAGE_SIZE = 20;

export default function ProductsPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));

  const [data, setData] = useState<Product[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [categories, setCategories] = useState<Category[]>([]);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const load = async () => {
    setLoading(true);
    try {
      const res = await listProducts({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        search: search || undefined,
        category_id: categoryFilter,
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được sản phẩm");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    listCategories()
      .then(setCategories)
      .catch(() => message.error("Không tải được danh mục"));
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, categoryFilter]);

  const categoryName = (id: string | null) =>
    id ? categories.find((c) => c.id === id)?.name ?? id : "—";

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      currency: "VND",
      unit_price: 0,
      is_active: true,
      category_id: null,
    });
    setDrawerOpen(true);
  };

  const openEdit = (p: Product) => {
    setEditing(p);
    form.setFieldsValue({
      sku: p.sku,
      name: p.name,
      category_id: p.category_id,
      barcode: p.barcode,
      description: p.description,
      unit_price: Number(p.unit_price),
      currency: p.currency,
      image_url: p.image_url,
      is_active: p.is_active,
      attributes_json: JSON.stringify(p.attributes ?? {}, null, 2),
    });
    setDrawerOpen(true);
  };

  const onSubmit = async (values: FormValues) => {
    let attributes: Record<string, unknown> | null = null;
    if (values.attributes_json && values.attributes_json.trim()) {
      try {
        attributes = JSON.parse(values.attributes_json);
      } catch {
        message.error("Attributes JSON không hợp lệ");
        return;
      }
    }
    setSaving(true);
    try {
      if (editing) {
        await updateProduct(editing.id, {
          sku: values.sku,
          name: values.name,
          category_id: values.category_id ?? undefined,
          category_unset: values.category_id === null,
          barcode: values.barcode ?? undefined,
          barcode_unset: !values.barcode,
          description: values.description ?? undefined,
          description_unset: !values.description,
          unit_price: values.unit_price,
          currency: values.currency,
          attributes: attributes ?? undefined,
          attributes_unset: attributes === null,
          image_url: values.image_url ?? undefined,
          image_url_unset: !values.image_url,
          is_active: values.is_active,
        });
        message.success("Đã cập nhật sản phẩm");
      } else {
        const payload: ProductPayload = {
          sku: values.sku,
          name: values.name,
          category_id: values.category_id ?? undefined,
          barcode: values.barcode ?? undefined,
          description: values.description ?? undefined,
          unit_price: values.unit_price,
          currency: values.currency,
          attributes: attributes ?? undefined,
          image_url: values.image_url ?? undefined,
          is_active: values.is_active,
        };
        await createProduct(payload);
        message.success("Đã tạo sản phẩm");
      }
      setDrawerOpen(false);
      load();
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      message.error(typeof detail === "string" ? detail : "Lưu thất bại");
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteProduct(id);
      message.success("Đã xóa sản phẩm");
      load();
    } catch {
      message.error("Xóa thất bại");
    }
  };

  const columns: ColumnsType<Product> = [
    { title: "SKU", dataIndex: "sku", width: 140 },
    { title: "Tên", dataIndex: "name" },
    {
      title: "Danh mục",
      dataIndex: "category_id",
      width: 180,
      render: (v: string | null) => categoryName(v),
    },
    { title: "Barcode", dataIndex: "barcode", width: 140, render: (v) => v ?? "—" },
    {
      title: "Đơn giá",
      dataIndex: "unit_price",
      width: 140,
      align: "right",
      render: (v: string, r) => `${Number(v).toLocaleString()} ${r.currency}`,
    },
    {
      title: "Active",
      dataIndex: "is_active",
      width: 100,
      render: (v: boolean) =>
        v ? <Tag color="green">Active</Tag> : <Tag>Inactive</Tag>,
    },
    {
      title: "Hành động",
      width: 140,
      fixed: "right",
      render: (_, record) => (
        <Space>
          <Button
            size="small"
            icon={<EditOutlined />}
            disabled={!canEdit}
            onClick={() => openEdit(record)}
          />
          <Popconfirm
            title="Xóa sản phẩm này?"
            onConfirm={() => onDelete(record.id)}
            disabled={!canEdit}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              disabled={!canEdit}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title="Sản phẩm"
      extra={
        <Space>
          <Input.Search
            placeholder="Tìm SKU/tên/barcode"
            allowClear
            onSearch={(v) => {
              setPage(1);
              setSearch(v);
            }}
            style={{ width: 260 }}
          />
          <Select
            allowClear
            placeholder="Lọc danh mục"
            style={{ width: 200 }}
            options={categories.map((c) => ({ value: c.id, label: c.name }))}
            value={categoryFilter}
            onChange={(v) => {
              setPage(1);
              setCategoryFilter(v);
            }}
          />
          {canEdit && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              Thêm sản phẩm
            </Button>
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
        scroll={{ x: 1100 }}
      />
      <Drawer
        title={editing ? "Sửa sản phẩm" : "Thêm sản phẩm"}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={560}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item
            label="SKU"
            name="sku"
            rules={[{ required: true, max: 80 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label="Tên"
            name="name"
            rules={[{ required: true, max: 255 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label="Danh mục" name="category_id">
            <Select
              allowClear
              placeholder="Không có"
              options={categories.map((c) => ({ value: c.id, label: c.name }))}
            />
          </Form.Item>
          <Form.Item label="Barcode" name="barcode" rules={[{ max: 80 }]}>
            <Input />
          </Form.Item>
          <Form.Item label="Đơn giá" name="unit_price" rules={[{ required: true }]}>
            <InputNumber min={0} className="!w-full" />
          </Form.Item>
          <Form.Item
            label="Tiền tệ"
            name="currency"
            rules={[{ required: true, len: 3 }]}
          >
            <Input maxLength={3} />
          </Form.Item>
          <Form.Item label="Mô tả" name="description">
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item label="Image URL" name="image_url" rules={[{ max: 1024 }]}>
            <Input />
          </Form.Item>
          <Form.Item
            label="Attributes (JSON)"
            name="attributes_json"
            tooltip='Ví dụ: {"weight":"500g","color":"đỏ"}'
          >
            <Input.TextArea rows={4} className="font-mono" />
          </Form.Item>
          <Form.Item label="Active" name="is_active" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving}>
            {editing ? "Cập nhật" : "Tạo mới"}
          </Button>
        </Form>
      </Drawer>
    </Card>
  );
}
