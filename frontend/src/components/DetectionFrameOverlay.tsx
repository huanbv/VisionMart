import type { Camera, Detection, RoiZone } from "@/api/cameras";
import RoiOverlay from "@/components/RoiOverlay";

const PALETTE = [
  "#3cdc50",
  "#ffc83c",
  "#28beff",
  "#ff5aaa",
  "#ff783c",
  "#5affff",
  "#ff5028",
  "#ffa0c8",
];

const GIANT_BOX_FRAC = 0.35;
const MIN_VISIBLE_CONF = 0.35;

export function detectionLabel(d: Detection): string {
  const name = d.name || d.class_name || "object";
  const pct = Number.isFinite(d.confidence) ? ` ${(d.confidence * 100).toFixed(0)}%` : "";
  return d.sku ? `${name} (${d.sku})${pct}` : `${name}${pct}`;
}

export function markerColor(key: string): string {
  if (!key) return PALETTE[0];
  let sum = 0;
  for (let i = 0; i < key.length; i += 1) sum += key.charCodeAt(i);
  return PALETTE[sum % PALETTE.length];
}

function pointInRing(x: number, y: number, points: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i];
    const [xj, yj] = points[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-12) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function isGiantBox(d: Detection, imageWidth: number, imageHeight: number): boolean {
  const b = d.bbox;
  if (!b || imageWidth <= 0 || imageHeight <= 0) return false;
  const area = Math.max(0, b.x2 - b.x1) * Math.max(0, b.y2 - b.y1);
  return area / (imageWidth * imageHeight) >= GIANT_BOX_FRAC;
}

function centerInZones(d: Detection, imageWidth: number, imageHeight: number, zones: RoiZone[]): boolean {
  const b = d.bbox;
  if (!b) return true;
  const cx = (b.x1 + b.x2) / 2 / imageWidth;
  const cy = (b.y1 + b.y2) / 2 / imageHeight;
  return zones.some((z) => z.points?.length >= 3 && pointInRing(cx, cy, z.points));
}

/** Hide full-frame ghosts and markers whose center sits outside Vùng Thanh Toán. */
export function visibleArchivedDetections(
  detections: Detection[],
  imageWidth: number,
  imageHeight: number,
  camera?: Camera,
): Detection[] {
  const isCameraFrame = imageWidth > 0 && imageHeight > 0 && imageWidth / imageHeight > 1.15;
  const zones = isCameraFrame ? camera?.roi_zones ?? [] : [];
  return detections.filter((d) => {
    const cls = (d.class_name || "").toLowerCase();
    if (cls === "person") return false;
    if (cls === "region" && !d.sku) return false;
    if (isGiantBox(d, imageWidth, imageHeight)) return false;
    if (Number.isFinite(d.confidence) && d.confidence < MIN_VISIBLE_CONF) return false;
    if (zones.length > 0 && !centerInZones(d, imageWidth, imageHeight, zones)) return false;
    return true;
  });
}

/**
 * Dots + SKU labels on a saved detection still, matching live overlay.
 * ROI is only drawn for camera-like (landscape) frames — not product collages.
 */
export default function DetectionFrameOverlay({
  detections,
  imageWidth,
  imageHeight,
  camera,
}: {
  detections: Detection[];
  imageWidth: number;
  imageHeight: number;
  camera?: Camera;
}) {
  const showRoi =
    Boolean(camera?.roi_zones?.length) &&
    imageWidth > 0 &&
    imageHeight > 0 &&
    imageWidth / imageHeight > 1.15;
  const visible = visibleArchivedDetections(detections, imageWidth, imageHeight, camera);

  return (
    <div style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      {showRoi && <RoiOverlay zones={camera?.roi_zones} />}
      {visible.map((d, i) => {
        const b = d.bbox;
        if (!b || !imageWidth || !imageHeight) return null;
        const cx = ((b.x1 + b.x2) / 2 / imageWidth) * 100;
        const cy = ((b.y1 + b.y2) / 2 / imageHeight) * 100;
        const key = d.sku || d.name || d.class_name || "object";
        const color = markerColor(key);
        const label = detectionLabel(d);
        const flip = cx > 62;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${cx}%`,
              top: `${cy}%`,
              transform: "translate(-50%, -50%)",
            }}
          >
            <span
              style={{
                display: "block",
                width: 14,
                height: 14,
                borderRadius: "50%",
                background: color,
                border: "2px solid #fff",
                boxShadow: "0 0 0 1px #111",
              }}
            />
            <span
              style={{
                position: "absolute",
                top: "50%",
                left: flip ? "auto" : 18,
                right: flip ? 18 : "auto",
                transform: "translateY(-50%)",
                background: color,
                color: "#111",
                fontSize: 11,
                fontWeight: 600,
                lineHeight: 1.3,
                padding: "1px 5px",
                borderRadius: 3,
                whiteSpace: "nowrap",
              }}
            >
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
