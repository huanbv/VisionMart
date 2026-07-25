import { useEffect, useState } from "react";
import { Typography } from "antd";

import type { Camera } from "@/api/cameras";
import { openMjpegStream } from "@/utils/mjpegStream";
import RoiOverlay from "@/components/RoiOverlay";

/**
 * Ô xem camera trực tiếp, tách riêng để tái dùng ngoài trang Cameras (ví
 * dụ đặt cạnh giỏ hàng để so sánh giữa sản phẩm AI thêm vào giỏ và cảnh
 * thật trên quầy). Tự mở/đóng luồng MJPEG theo vòng đời component: luôn
 * gọi handle.stop() khi gỡ để không giữ cv2.VideoCapture mở vô thời hạn.
 *
 * Vẽ ROI overlay theo toạ độ phân số (0–1) như ở trang Cameras, và dùng
 * objectFit "contain" để vùng vẽ không lệch khỏi vị trí thật.
 */
export default function LiveCameraView({
  camera,
  detect = true,
  showLabels = true,
}: {
  camera: Camera;
  detect?: boolean;
  showLabels?: boolean;
}) {
  const [frame, setFrame] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setFrame(null);
    setError(null);
    const handle = openMjpegStream(
      camera.id,
      (url) => setFrame(url),
      (msg) => setError(msg),
      { detect, detectEveryN: 5 },
    );
    return () => handle.stop();
  }, [camera.id, detect]);

  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        aspectRatio: "16 / 9",
        background: "#000",
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      {error ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 8,
            textAlign: "center",
          }}
        >
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            {error}
          </Typography.Text>
        </div>
      ) : frame ? (
        <>
          <img
            src={frame}
            alt={camera.name}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "contain",
              display: "block",
            }}
          />
          <RoiOverlay zones={camera.roi_zones} showLabels={showLabels} />
        </>
      ) : (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            Đang mở luồng trực tiếp…
          </Typography.Text>
        </div>
      )}
    </div>
  );
}
