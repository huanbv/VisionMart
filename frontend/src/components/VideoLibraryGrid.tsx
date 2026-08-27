import { Popconfirm, Tag, Typography } from "antd";
import {
  BorderOuterOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";

import type { RoiZone } from "@/api/cameras";
import type { VideoLibraryMeta } from "@/utils/videoLibrary";

function RoiMapOverlay({ zones }: { zones: RoiZone[] }) {
  if (!zones.length) return null;
  return (
    <svg
      viewBox="0 0 1 1"
      preserveAspectRatio="none"
      style={{
        position: "absolute",
        inset: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
      }}
    >
      {zones.map((zone, i) => {
        if (!zone.points || zone.points.length < 3) return null;
        const isCheckout =
          zone.type === "checkout" ||
          zone.name?.toLowerCase().includes("checkout") ||
          zone.name?.toLowerCase().includes("quầy");
        return (
          <polygon
            key={`${zone.name}-${i}`}
            points={zone.points.map(([x, y]) => `${x},${y}`).join(" ")}
            fill={isCheckout ? "rgba(250, 173, 20, 0.28)" : "rgba(24, 144, 255, 0.22)"}
            stroke={isCheckout ? "#faad14" : "#1677ff"}
            strokeWidth={0.012}
            strokeDasharray="0.03 0.02"
          />
        );
      })}
    </svg>
  );
}

export default function VideoLibraryGrid({
  items,
  selectedId,
  disabled,
  onSelect,
  onDelete,
}: {
  items: VideoLibraryMeta[];
  selectedId?: string;
  disabled?: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  if (!items.length) {
    return (
      <div
        style={{
          border: "1px dashed #d9d9d9",
          borderRadius: 8,
          padding: 20,
          textAlign: "center",
          background: "#fafafa",
        }}
      >
        <VideoCameraOutlined style={{ fontSize: 28, color: "#bfbfbf" }} />
        <div style={{ marginTop: 8 }}>
          <Typography.Text type="secondary">
            Chưa có video — thêm file để hiện dạng lưới. Mỗi video giữ bản đồ vùng thanh toán riêng.
          </Typography.Text>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
        gap: 10,
        maxHeight: 280,
        overflowY: "auto",
        padding: 2,
      }}
    >
      {items.map((item) => {
        const selected = item.id === selectedId;
        const zoneCount = item.roiZones?.length ?? 0;
        return (
          <div
            key={item.id}
            role="button"
            tabIndex={disabled ? -1 : 0}
            onClick={() => {
              if (!disabled) onSelect(item.id);
            }}
            onKeyDown={(e) => {
              if (!disabled && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                onSelect(item.id);
              }
            }}
            style={{
              border: selected ? "2px solid #1677ff" : "1px solid #d9d9d9",
              borderRadius: 8,
              overflow: "hidden",
              background: selected ? "#e6f4ff" : "#fff",
              cursor: disabled ? "not-allowed" : "pointer",
              opacity: disabled ? 0.65 : 1,
              boxShadow: selected ? "0 0 0 2px rgba(22,119,255,0.15)" : undefined,
            }}
          >
            <div style={{ position: "relative", background: "#111" }}>
              {item.poster ? (
                <img
                  src={item.poster}
                  alt={item.name}
                  style={{ width: "100%", display: "block" }}
                />
              ) : (
                <div
                  style={{
                    aspectRatio: "16 / 9",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#888",
                  }}
                >
                  <VideoCameraOutlined style={{ fontSize: 28 }} />
                </div>
              )}
              <RoiMapOverlay zones={item.roiZones || []} />
              <Tag
                color={zoneCount ? "gold" : "default"}
                style={{
                  position: "absolute",
                  top: 6,
                  left: 6,
                  margin: 0,
                  fontSize: 11,
                  lineHeight: "18px",
                }}
                icon={zoneCount ? <CheckCircleOutlined /> : <BorderOuterOutlined />}
              >
                {zoneCount ? `Đã có ${zoneCount} vùng` : "Chưa vẽ vùng"}
              </Tag>
              <Popconfirm
                title="Xóa video này khỏi thư viện?"
                onConfirm={() => onDelete(item.id)}
                okText="Xóa"
                cancelText="Không"
                disabled={disabled}
              >
                <button
                  type="button"
                  aria-label="Xóa video"
                  onClick={(e) => e.stopPropagation()}
                  disabled={disabled}
                  style={{
                    position: "absolute",
                    top: 6,
                    right: 6,
                    border: "none",
                    borderRadius: 4,
                    width: 24,
                    height: 24,
                    background: "rgba(0,0,0,0.55)",
                    color: "#fff",
                    cursor: disabled ? "not-allowed" : "pointer",
                  }}
                >
                  <DeleteOutlined />
                </button>
              </Popconfirm>
            </div>
            <div style={{ padding: "6px 8px" }}>
              <Typography.Text
                ellipsis
                title={item.name}
                style={{ fontSize: 12, display: "block", fontWeight: selected ? 600 : 400 }}
              >
                {item.name}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                {(item.size / 1024 / 1024).toFixed(1)} MB
              </Typography.Text>
            </div>
          </div>
        );
      })}
    </div>
  );
}
