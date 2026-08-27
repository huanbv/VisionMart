import { useEffect, useState } from "react";
import { Button, Modal, Select, Space, Tooltip, Typography, message } from "antd";
import { EditOutlined } from "@ant-design/icons";
import { isAxiosError } from "axios";

import { retagCartLine, type Cart, type CartLine } from "@/api/carts";
import { listAllProducts, type Product } from "@/api/catalog";
import CartLinePhoto from "@/components/CartLinePhoto";

/**
 * Đổi SKU trên đúng dòng giỏ. Giữ crop; nếu có ảnh thì đưa vào tập học
 * (admin đã chọn SKU đúng — không lấy đoán của model).
 */
export default function CartLineSkuButton({
  cart,
  line,
  disabled,
  onDone,
}: {
  cart: Cart;
  line: CartLine;
  disabled?: boolean;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setProductId(undefined);
    setLoading(true);
    listAllProducts({ is_active: true })
      .then(setProducts)
      .catch(() => message.error("Không tải được danh sách sản phẩm"))
      .finally(() => setLoading(false));
  }, [open]);

  const submit = async () => {
    if (!productId) {
      message.warning("Chọn SKU đúng");
      return;
    }
    if (productId === line.product_id) {
      message.info("Đúng SKU hiện tại — không đổi");
      setOpen(false);
      return;
    }
    setSaving(true);
    try {
      const res = await retagCartLine(cart.id, line.line_id, productId);
      if (res.added_to_training) {
        message.success("Đã đổi SKU và đưa crop vào tập huấn luyện");
      } else if (line.has_photo) {
        message.success("Đã đổi SKU trên đơn. Chưa ghi được vào tập học — kiểm tra MinIO.");
      } else {
        message.success("Đã đổi SKU trên đơn. Không có ảnh crop nên chưa đưa vào huấn luyện.");
      }
      setOpen(false);
      onDone();
    } catch (err) {
      message.error(
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không đổi được SKU",
      );
    } finally {
      setSaving(false);
    }
  };

  const editable = cart.status === "active" && !disabled;

  return (
    <>
      <Tooltip title={editable ? "Đổi SKU (đưa crop vào tập học)" : "Chỉ sửa khi giỏ đang ACTIVE"}>
        <Button
          size="small"
          icon={<EditOutlined />}
          disabled={!editable}
          onClick={() => setOpen(true)}
        />
      </Tooltip>
      <Modal
        title="Đổi SKU sản phẩm trong giỏ"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void submit()}
        okText="Đổi SKU"
        confirmLoading={saving}
        destroyOnClose
      >
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          {line.has_photo ? (
            <CartLinePhoto
              cartId={cart.id}
              lineId={line.line_id}
              size={96}
              alt={line.product_name || line.sku}
            />
          ) : (
            <Typography.Text type="secondary">
              Dòng này không có ảnh crop — đổi SKU vẫn sửa đơn, nhưng AI chưa học được từ lần sửa.
            </Typography.Text>
          )}
          <div>
            <Typography.Text type="secondary">AI gắn: </Typography.Text>
            <Typography.Text strong>
              {line.product_name} ({line.sku})
            </Typography.Text>
          </div>
          <Select
            showSearch
            loading={loading}
            style={{ width: "100%" }}
            placeholder="Chọn SKU đúng (gõ mã hoặc tên)"
            optionFilterProp="label"
            value={productId}
            onChange={setProductId}
            options={products
              .filter((p) => p.id !== line.product_id)
              .map((p) => ({
                label: `${p.sku} — ${p.name}`,
                value: p.id,
              }))}
          />
        </Space>
      </Modal>
    </>
  );
}
