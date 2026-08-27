import { Empty, Spin, Tag, Typography } from "antd";
import { ScissorOutlined } from "@ant-design/icons";

import type { LabelImageSummary } from "@/api/aiLabeling";

const { Text } = Typography;

export default function LabelImageGrid({
  items,
  currentId,
  loading,
  onSelect,
}: {
  items: LabelImageSummary[];
  currentId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
}) {
  if (loading && items.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: 32 }}>
        <Spin />
      </div>
    );
  }

  if (!items.length) {
    return <Empty description="Chưa có ảnh — upload ở trên" />;
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
        gap: 10,
      }}
    >
      {items.map((item) => {
        const selected = item.id === currentId;
        const title = item.original_filename ?? item.id.slice(0, 8);
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.id)}
            title={title}
            style={{
              display: "block",
              width: "100%",
              padding: 0,
              border: selected ? "2px solid #1677ff" : "1px solid #d9d9d9",
              borderRadius: 6,
              background: selected ? "#e6f4ff" : "#fff",
              cursor: "pointer",
              overflow: "hidden",
              textAlign: "left",
            }}
          >
            <div
              style={{
                position: "relative",
                aspectRatio: "4 / 3",
                background: "#f5f5f5",
              }}
            >
              {item.preview_url ? (
                <img
                  src={item.preview_url}
                  alt={title}
                  loading="lazy"
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    display: "block",
                  }}
                />
              ) : (
                <div
                  style={{
                    width: "100%",
                    height: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    color: "#bfbfbf",
                    fontSize: 12,
                  }}
                >
                  Không xem trước
                </div>
              )}
              <div
                style={{
                  position: "absolute",
                  top: 4,
                  left: 4,
                  display: "flex",
                  gap: 4,
                  flexWrap: "wrap",
                }}
              >
                {!item.is_cropped && (
                  <Tag color="orange" style={{ margin: 0, fontSize: 10, lineHeight: "18px" }} icon={<ScissorOutlined />}>
                    cam
                  </Tag>
                )}
                {item.labeled ? (
                  <Tag color="green" style={{ margin: 0, fontSize: 10, lineHeight: "18px" }}>
                    {item.box_count}
                  </Tag>
                ) : (
                  <Tag style={{ margin: 0, fontSize: 10, lineHeight: "18px" }}>—</Tag>
                )}
              </div>
            </div>
            <Text
              ellipsis
              style={{
                display: "block",
                padding: "4px 6px",
                fontSize: 11,
                maxWidth: "100%",
              }}
            >
              {title}
            </Text>
          </button>
        );
      })}
    </div>
  );
}
