import type { RoiZone } from "@/api/cameras";

export const ZONE_TYPES = [
  { value: "checkout", label: "Quầy thanh toán", color: "#ff4d4f" },
  { value: "shelf", label: "Kệ hàng", color: "#1677ff" },
  { value: "entrance", label: "Lối vào", color: "#52c41a" },
  { value: "exit", label: "Lối ra", color: "#faad14" },
] as const;

export type ZoneType = (typeof ZONE_TYPES)[number]["value"];

export function colorOf(type: string): string {
  return ZONE_TYPES.find((t) => t.value === type)?.color ?? "#ff4d4f";
}

export function labelOf(type: string): string {
  return ZONE_TYPES.find((t) => t.value === type)?.label ?? type;
}

/**
 * Vẽ lại các vùng nhận diện đã lưu lên trên ảnh camera.
 *
 * Đa giác vẽ bằng SVG với viewBox 0→1 và ``preserveAspectRatio="none"``:
 * toạ độ vùng vốn đã là phân số, nên SVG tự co giãn khớp với ảnh ở mọi
 * kích thước hiển thị — từ ô nhỏ trong lưới đến modal xem trực tiếp — mà
 * không cần biết độ phân giải thật của luồng hay đo phần tử bằng JS.
 *
 * Nhãn tên vùng thì vẽ bằng thẻ HTML định vị theo phần trăm, KHÔNG dùng
 * <text> trong SVG: viewBox 0→1 bị kéo giãn không đều theo hai chiều, nên
 * chữ trong SVG sẽ méo theo tỉ lệ khung, và cỡ chữ tính bằng px lại là
 * đơn vị của hệ toạ độ (11px = 11 lần cả khung hình). Để ngoài HTML thì
 * chữ luôn nét và đúng cỡ.
 *
 * Overlay chỉ nằm đè lên ảnh với ``pointerEvents: none`` nên không chặn
 * thao tác nào ở lớp dưới.
 */
export default function RoiOverlay({
  zones,
  showLabels = true,
}: {
  zones: RoiZone[] | null | undefined;
  showLabels?: boolean;
}) {
  if (!zones || zones.length === 0) return null;

  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      <svg
        viewBox="0 0 1 1"
        preserveAspectRatio="none"
        style={{ width: "100%", height: "100%", display: "block" }}
      >
        {zones.map((z, i) => {
          const color = colorOf(z.type);
          return (
            <polygon
              key={i}
              points={z.points.map(([x, y]) => `${x},${y}`).join(" ")}
              fill={color}
              fillOpacity={0.18}
              stroke={color}
              strokeWidth={2}
              // Giữ nét viền mảnh đều nhau: không có thuộc tính này thì
              // viewBox 0→1 khi kéo giãn sẽ nhân luôn độ dày nét lên,
              // thành viền dày cả chục pixel và méo theo tỉ lệ khung.
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </svg>

      {showLabels &&
        zones.map((z, i) => {
          // Nhãn đặt ở đỉnh cao nhất của vùng.
          const top = z.points.reduce(
            (best, p) => (p[1] < best[1] ? p : best),
            z.points[0],
          );
          return (
            <span
              key={`t${i}`}
              style={{
                position: "absolute",
                left: `${top[0] * 100}%`,
                top: `${top[1] * 100}%`,
                // Đẩy nhãn lên trên đỉnh; nếu vùng chạm mép trên khung
                // hình thì nhãn sẽ tự nằm bên trong thay vì bị cắt mất.
                transform:
                  top[1] < 0.06 ? "translateY(2px)" : "translateY(-100%)",
                background: colorOf(z.type),
                color: "#fff",
                fontSize: 11,
                fontWeight: 600,
                lineHeight: 1.4,
                padding: "0 5px",
                borderRadius: 2,
                whiteSpace: "nowrap",
                maxWidth: "100%",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {z.name}
            </span>
          );
        })}
    </div>
  );
}
