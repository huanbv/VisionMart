import { useEffect, useRef, useState } from "react";
import { Typography } from "antd";

import type { Camera } from "@/api/cameras";
import { openMjpegStream } from "@/utils/mjpegStream";
import RoiOverlay from "@/components/RoiOverlay";

/** Trạng thái luồng, báo ra ngoài cho panel tiến độ AI (nếu component cha cần). */
export type LiveStreamStatus = "connecting" | "live" | "error" | "paused";

// Mất luồng thì thử lại sau ngần này (giây) thay vì treo lỗi vĩnh viễn cho
// tới khi người dùng đổi camera hay bấm lại switch — camera RTSP rớt tạm
// thời (mất điện, khởi động lại đầu ghi) là chuyện thường, nên tự phục hồi
// khi luồng có lại là hành vi đúng, không cần người canh chừng.
const RETRY_DELAY_MS = 5_000;

/**
 * Ô xem camera trực tiếp, tách riêng để tái dùng ngoài trang Cameras (ví
 * dụ đặt cạnh giỏ hàng để so sánh giữa sản phẩm AI thêm vào giỏ và cảnh
 * thật trên quầy). Tự mở/đóng luồng MJPEG theo vòng đời component: luôn
 * gọi handle.stop() khi gỡ để không giữ cv2.VideoCapture mở vô thời hạn.
 *
 * Vẽ ROI overlay theo toạ độ phân số (0–1) như ở trang Cameras, và dùng
 * objectFit "contain" để vùng vẽ không lệch khỏi vị trí thật.
 *
 * `paused`: when true, do not open the stream (and do not auto-retry).
 * Pausing auto-cart on Live Cart does NOT set this — the feed stays up
 * so product boxes in the checkout zone remain visible.
 */
export default function LiveCameraView({
  camera,
  detect = true,
  detectEveryN = 3,
  showLabels = true,
  paused = false,
  onStatusChange,
}: {
  camera: Camera;
  detect?: boolean;
  detectEveryN?: number;
  showLabels?: boolean;
  paused?: boolean;
  onStatusChange?: (status: LiveStreamStatus) => void;
}) {
  const [frame, setFrame] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;

  useEffect(() => {
    if (paused) {
      setFrame(null);
      setError(null);
      onStatusChangeRef.current?.("paused");
      return;
    }

    let stopped = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let handle: { stop: () => void } | null = null;

    const connect = () => {
      if (stopped) return;
      setFrame(null);
      setError(null);
      onStatusChangeRef.current?.("connecting");
      handle = openMjpegStream(
        camera.id,
        (url) => {
          setFrame(url);
          onStatusChangeRef.current?.("live");
        },
        (msg) => {
          setError(msg);
          onStatusChangeRef.current?.("error");
          if (!stopped) {
            retryTimer = setTimeout(connect, RETRY_DELAY_MS);
          }
        },
        { detect, detectEveryN },
      );
    };
    connect();

    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      handle?.stop();
    };
  }, [camera.id, detect, detectEveryN, paused]);

  if (paused) {
    return (
      <div
        style={{
          position: "relative",
          width: "100%",
          aspectRatio: "16 / 9",
          background: "#141414",
          borderRadius: 4,
          overflow: "hidden",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          ⏸️ Đã tạm dừng nhận diện AI
        </Typography.Text>
      </div>
    );
  }

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
            flexDirection: "column",
            gap: 4,
            alignItems: "center",
            justifyContent: "center",
            padding: 8,
            textAlign: "center",
          }}
        >
          <Typography.Text type="danger" style={{ fontSize: 12 }}>
            {error}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            Đang tự động thử kết nối lại…
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
