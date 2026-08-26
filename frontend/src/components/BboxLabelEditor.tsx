import { useCallback, useEffect, useRef, useState } from "react";
import { Empty, Select, Space, Tag, Typography } from "antd";

import type { CropRect, DraftBox } from "@/api/aiLabeling";
import type { Product } from "@/api/catalog";

const { Text } = Typography;

const COLORS = [
  "#1677ff",
  "#52c41a",
  "#fa8c16",
  "#eb2f96",
  "#722ed1",
  "#13c2c2",
  "#f5222d",
  "#a0d911",
];

function colorForSku(sku: string): string {
  let h = 0;
  for (let i = 0; i < sku.length; i++) h = (h + sku.charCodeAt(i) * 17) % COLORS.length;
  return COLORS[h]!;
}

export type EditorMode = "label" | "crop";

export default function BboxLabelEditor({
  imageUrl,
  products,
  boxes,
  selectedProductId,
  onProductChange,
  onBoxesChange,
  selectedBoxId,
  onSelectBox,
  mode = "label",
  cropRect,
  onCropRectChange,
  labelingEnabled = true,
}: {
  imageUrl: string | null;
  products: Product[];
  boxes: DraftBox[];
  selectedProductId: string | null;
  onProductChange: (id: string) => void;
  onBoxesChange: (boxes: DraftBox[]) => void;
  selectedBoxId: string | null;
  onSelectBox: (id: string | null) => void;
  mode?: EditorMode;
  cropRect?: CropRect | null;
  onCropRectChange?: (rect: CropRect | null) => void;
  labelingEnabled?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [imgEpoch, setImgEpoch] = useState(0);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const [draftRect, setDraftRect] = useState<DraftBox | CropRect | null>(null);

  const product = products.find((p) => p.id === selectedProductId) ?? null;
  const isCropMode = mode === "crop";

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img?.complete || !img.naturalWidth) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(img, 0, 0, w, h);

    const drawBox = (b: DraftBox, selected: boolean) => {
      const x1 = b.x1 * w;
      const y1 = b.y1 * h;
      const bw = (b.x2 - b.x1) * w;
      const bh = (b.y2 - b.y1) * h;
      const color = colorForSku(b.sku);
      ctx.strokeStyle = color;
      ctx.lineWidth = selected ? 3 : 2;
      ctx.strokeRect(x1, y1, bw, bh);
      ctx.fillStyle = color + (selected ? "55" : "33");
      ctx.fillRect(x1, y1, bw, bh);
      ctx.fillStyle = color;
      ctx.font = "12px sans-serif";
      ctx.fillText(b.sku, x1 + 4, y1 + 14);
    };

    const drawCrop = (r: CropRect, dashed: boolean) => {
      const x1 = Math.min(r.x1, r.x2) * w;
      const y1 = Math.min(r.y1, r.y2) * h;
      const bw = Math.abs(r.x2 - r.x1) * w;
      const bh = Math.abs(r.y2 - r.y1) * h;
      ctx.save();
      ctx.strokeStyle = "#fa8c16";
      ctx.lineWidth = 2;
      if (dashed) ctx.setLineDash([8, 6]);
      ctx.strokeRect(x1, y1, bw, bh);
      ctx.fillStyle = "rgba(250, 140, 22, 0.12)";
      ctx.fillRect(x1, y1, bw, bh);
      ctx.restore();
      ctx.fillStyle = "#fa8c16";
      ctx.font = "12px sans-serif";
      ctx.fillText("Vùng cắt", x1 + 4, y1 + 14);
    };

    for (const b of boxes) {
      drawBox(b, b.clientId === selectedBoxId);
    }
    if (isCropMode) {
      if (cropRect) drawCrop(cropRect, false);
      if (draftRect && !("clientId" in draftRect)) {
        drawCrop(draftRect, true);
      }
    } else if (draftRect && "clientId" in draftRect) {
      drawBox(draftRect, true);
    }
  }, [boxes, cropRect, draftRect, isCropMode, selectedBoxId]);

  useEffect(() => {
    if (!imageUrl) {
      imgRef.current = null;
      return;
    }
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      imgRef.current = img;
      const canvas = canvasRef.current;
      if (canvas) {
        canvas.width = img.naturalWidth;
        canvas.height = img.naturalHeight;
      }
      setImgEpoch((n) => n + 1);
    };
    img.src = imageUrl;
  }, [imageUrl]);

  useEffect(() => {
    redraw();
  }, [imgEpoch, redraw, boxes, draftRect, selectedBoxId, cropRect, isCropMode]);

  const normFromEvent = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return {
      x: Math.max(0, Math.min(1, x)),
      y: Math.max(0, Math.min(1, y)),
    };
  };

  const hitTest = (nx: number, ny: number): DraftBox | null => {
    for (let i = boxes.length - 1; i >= 0; i--) {
      const b = boxes[i]!;
      const x1 = Math.min(b.x1, b.x2);
      const x2 = Math.max(b.x1, b.x2);
      const y1 = Math.min(b.y1, b.y2);
      const y2 = Math.max(b.y1, b.y2);
      if (nx >= x1 && nx <= x2 && ny >= y1 && ny <= y2) return b;
    }
    return null;
  };

  const onMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const { x, y } = normFromEvent(e);

    if (isCropMode) {
      onSelectBox(null);
      dragRef.current = { x, y };
      setDraftRect({ x1: x, y1: y, x2: x, y2: y });
      return;
    }

    if (!product || !labelingEnabled) return;
    const hit = hitTest(x, y);
    if (hit) {
      onSelectBox(hit.clientId);
      return;
    }
    onSelectBox(null);
    dragRef.current = { x, y };
    setDraftRect({
      clientId: crypto.randomUUID(),
      product_id: product.id,
      sku: product.sku,
      product_name: product.name,
      x1: x,
      y1: y,
      x2: x,
      y2: y,
    });
  };

  const onMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!dragRef.current || !draftRect) return;
    const { x, y } = normFromEvent(e);
    if (isCropMode) {
      setDraftRect({ ...(draftRect as CropRect), x2: x, y2: y });
      return;
    }
    if (!product || !("clientId" in draftRect)) return;
    setDraftRect({ ...draftRect, x2: x, y2: y });
  };

  const onMouseUp = () => {
    if (!draftRect) {
      dragRef.current = null;
      return;
    }

    if (isCropMode) {
      const r = draftRect as CropRect;
      const w = Math.abs(r.x2 - r.x1);
      const h = Math.abs(r.y2 - r.y1);
      if (w > 0.02 && h > 0.02) {
        onCropRectChange?.({
          x1: Math.min(r.x1, r.x2),
          y1: Math.min(r.y1, r.y2),
          x2: Math.max(r.x1, r.x2),
          y2: Math.max(r.y1, r.y2),
        });
      }
      dragRef.current = null;
      setDraftRect(null);
      return;
    }

    if (!product || !("clientId" in draftRect)) {
      dragRef.current = null;
      setDraftRect(null);
      return;
    }
    const w = Math.abs(draftRect.x2 - draftRect.x1);
    const h = Math.abs(draftRect.y2 - draftRect.y1);
    if (w > 0.01 && h > 0.01) {
      onBoxesChange([...boxes, draftRect]);
      onSelectBox(draftRect.clientId);
    }
    dragRef.current = null;
    setDraftRect(null);
  };

  if (!imageUrl) {
    return <Empty description="Chọn ảnh để gán nhãn" />;
  }

  const canDraw = isCropMode || (!!product && labelingEnabled);

  return (
    <div>
      {!isCropMode && !labelingEnabled && (
        <Tag color="warning" style={{ marginBottom: 12 }}>
          Cắt ảnh hoặc bỏ qua cắt trước khi vẽ khung bbox
        </Tag>
      )}
      {!isCropMode && labelingEnabled && (
        <Space wrap style={{ marginBottom: 12 }}>
          <Text strong>SKU đang vẽ:</Text>
          <Select
            showSearch
            placeholder="Chọn sản phẩm (SKU)"
            style={{ minWidth: 280 }}
            value={selectedProductId ?? undefined}
            onChange={onProductChange}
            optionFilterProp="label"
            options={products.map((p) => ({
              value: p.id,
              label: `${p.sku} — ${p.name}`,
            }))}
          />
          {!product && <Tag color="warning">Chọn SKU trước khi kéo vẽ khung</Tag>}
        </Space>
      )}
      {isCropMode && (
        <Tag color="orange" style={{ marginBottom: 12 }}>
          Chế độ cắt ảnh — kéo chọn vùng giữ lại, bỏ phần thừa quanh cạnh
        </Tag>
      )}
      <div style={{ overflow: "auto", maxHeight: "calc(100vh - 320px)" }}>
        <canvas
          ref={canvasRef}
          style={{
            maxWidth: "100%",
            cursor: canDraw ? "crosshair" : "not-allowed",
            border: "1px solid #d9d9d9",
            borderRadius: 4,
          }}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        />
      </div>
      {boxes.length > 0 && !isCropMode && (
        <Space wrap style={{ marginTop: 8 }}>
          {boxes.map((b) => (
            <Tag
              key={b.clientId}
              color={b.clientId === selectedBoxId ? "blue" : undefined}
              style={{ cursor: "pointer" }}
              onClick={() => onSelectBox(b.clientId)}
            >
              {b.sku}
            </Tag>
          ))}
        </Space>
      )}
    </div>
  );
}
