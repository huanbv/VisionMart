/**
 * VideoAnalysisPage — Phân tích video file qua AI pipeline.
 *
 * Cơ chế:
 *  1. Người dùng upload video (MP4/AVI/MOV...).
 *  2. Video phát trong <video>; mỗi N giây, canvas chụp frame hiện tại → Blob JPEG.
 *  3. Blob được gửi lên POST /ai/ai/frame (manual_scan=false, optional weight_key).
 *  4. Mặc định tạm dừng phát khi đang chờ AI, rồi chạy tiếp — inference chậm
 *     hơn 1× không bỏ khung. Nút Tạm dừng vẫn gửi khung đang đóng băng.
 *  5. Backend nhận events → tạo giỏ hàng → WebSocket thông báo → danh sách giỏ cập nhật.
 *  6. Nút Dừng dừng vòng lặp gửi frame.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  List,
  Popconfirm,
  Progress,
  Row,
  Select,
  Slider,
  Space,
  Statistic,
  Switch,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  Upload,
  message,
} from "antd";
import {
  BorderOuterOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  QrcodeOutlined,
  ReloadOutlined,
  ShoppingCartOutlined,
  StopOutlined,
  UploadOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import { isAxiosError } from "axios";

import {
  abandonCart,
  bulkAbandonCarts,
  cancelCheckout,
  checkoutCart,
  confirmCheckoutStaff,
  getCheckoutQr,
  listCarts,
  removeCartLine,
  type Cart,
  type CartCheckoutQrResponse,
} from "@/api/carts";
import { listBranches, getOrganization, type Branch } from "@/api/tenancy";
import { listCameras, getRoiZones, type Camera, type RoiZone } from "@/api/cameras";
import { tokenStore } from "@/api/client";
import RoiZoneEditor from "@/components/RoiZoneEditor";
import { listTrainingJobs, type TrainingJob } from "@/api/aiTraining";

const AI_FRAME_URL = "/ai/ai/frame";
const AI_RESET_URL = "/ai/ai/reset-session";
// Đọc từ biến môi trường lúc build (VITE_AI_ENGINE_KEY trong .env) thay vì
// hardcode literal — key thật không nằm trong lịch sử git. Vẫn nằm trong
// bundle JS gửi tới trình duyệt (không tránh được vì gọi ai-engine thẳng
// từ client, xem comment ở AI_FRAME_URL), fallback placeholder chỉ để dev
// local không set biến vẫn chạy được (sẽ bị ai-engine từ chối 401 nếu
// AI_ENGINE_API_KEY thật khác giá trị mặc định — không phải lỗi ẩn).
const AI_ENGINE_KEY = import.meta.env.VITE_AI_ENGINE_KEY ?? "change-me-ai-engine-key";
const REFRESH_MS = 3_000;

const IGNORED_COCO_CLASSES = new Set([
  "chair", "cat", "dog", "book", "table", "couch", "tv", "laptop",
  "potted plant", "cell phone", "remote", "keyboard", "mouse", "dining table", "bed", "toilet", "refrigerator"
]);

function jobKind(job: TrainingJob): "bbox" | "crop" {
  return job.class_map?.["mode"] === "labeled_scenes" ? "bbox" : "crop";
}

function jobMetricHint(job: TrainingJob): string {
  const metrics = job.metrics || {};
  const entry = Object.entries(metrics).find(([k]) =>
    /map50/i.test(k)
  );
  if (!entry || typeof entry[1] !== "number") return "";
  const value = entry[1] <= 1 ? entry[1] * 100 : entry[1];
  return ` · mAP50 ${value.toFixed(0)}%`;
}

function jobSelectLabel(job: TrainingJob): string {
  const date = new Date(job.created_at).toLocaleDateString("vi-VN");
  const live = job.deployed_at ? " · đang live" : "";
  return `${job.name}${jobMetricHint(job)}${live} — ${date}`;
}

function formatMoney(amount: string, currency: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return `${amount} ${currency}`;
  try {
    return new Intl.NumberFormat("vi-VN", {
      style: "currency",
      currency: currency || "VND",
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value.toLocaleString("vi-VN")} ${currency}`;
  }
}

interface LogItem {
  id: string;
  time: string;
  type: "scan" | "add" | "remove" | "checkout" | "info" | "error";
  message: string;
  detail?: string;
}

export default function VideoAnalysisPage() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchId] = useState<string | undefined>();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<string | undefined>();
  const selectedCamera = useMemo(() => cameras.find((c) => c.id === cameraId), [cameras, cameraId]);
  const [organizationId, setOrganizationId] = useState<string | undefined>();

  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [frameInterval, setFrameInterval] = useState(2);
  const [minConfidence, setMinConfidence] = useState(0.6);
  const [cleanBeforeStart, setCleanBeforeStart] = useState(true);
  const [pauseForAi, setPauseForAi] = useState(true);
  const [weightKey, setWeightKey] = useState<string>("live");
  const [trainingJobs, setTrainingJobs] = useState<TrainingJob[]>([]);
  const [framesProcessed, setFramesProcessed] = useState(0);
  const [framesAccepted, setFramesAccepted] = useState(0);
  const [lastFrameResult, setLastFrameResult] = useState<string | null>(null);

  const [carts, setCarts] = useState<Cart[]>([]);
  const [cartsLoading, setCartsLoading] = useState(false);
  const [qrByCart, setQrByCart] = useState<Record<string, CartCheckoutQrResponse>>({});
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [wsConnected, setWsConnected] = useState(false);

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null);
  const stopRef = useRef(false);
  const runningRef = useRef(false);
  const userPausedRef = useRef(false);
  const autoPausingRef = useRef(false);
  const loopWakeRef = useRef<Set<() => void>>(new Set());

  const [roiZones, setRoiZones] = useState<RoiZone[]>([]);
  const [roiEditorOpen, setRoiEditorOpen] = useState(false);
  const [roiSnapshot, setRoiSnapshot] = useState<string | null>(null);

  const captureVideoSnapshot = useCallback((): string | null => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !video.videoWidth) return null;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85);
  }, []);

  const openRoiEditor = () => {
    if (!videoUrl) {
      message.warning("Tải video trước, rồi tua tới khung mặt quầy để vẽ vùng");
      return;
    }
    const snap = captureVideoSnapshot();
    if (!snap) {
      message.warning("Chờ video tải xong (hoặc bấm play một nhịp) rồi vẽ vùng");
      return;
    }
    videoRef.current?.pause();
    setIsPaused(true);
    setRoiSnapshot(snap);
    setRoiEditorOpen(true);
  };

  const loadCameraRoi = () => {
    if (!cameraId) {
      message.warning("Chọn camera quầy nếu muốn nạp vùng đã lưu");
      return;
    }
    getRoiZones(cameraId)
      .then((z) => {
        setRoiZones(z);
        message.success(
          z.length
            ? `Đã nạp ${z.length} vùng từ camera — chỉnh lại nếu góc video khác`
            : "Camera này chưa có vùng thanh toán",
        );
      })
      .catch(() => message.error("Không tải được vùng camera"));
  };

  const drawDetectionsOverlay = useCallback((detections: any[]) => {
    const video = videoRef.current;
    const overlayCanvas = overlayCanvasRef.current;
    if (!video || !overlayCanvas) return;

    const displayW = video.clientWidth || video.videoWidth || 640;
    const displayH = video.clientHeight || video.videoHeight || 480;

    overlayCanvas.width = displayW;
    overlayCanvas.height = displayH;

    const ctx = overlayCanvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, displayW, displayH);

    const vidW = video.videoWidth || displayW;
    const vidH = video.videoHeight || displayH;
    const scaleX = displayW / vidW;
    const scaleY = displayH / vidH;

    // 1. Vẽ Khu vực thanh toán (ROI Payzone)
    const zones = roiZones;
    zones.forEach((zone) => {
      if (!zone.points || zone.points.length < 3) return;
      ctx.save();
      ctx.beginPath();
      zone.points.forEach(([nx, ny], idx) => {
        const px = nx * displayW;
        const py = ny * displayH;
        if (idx === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.closePath();

      const isCheckout = zone.type === "checkout" || zone.name?.toLowerCase().includes("checkout") || zone.name?.toLowerCase().includes("quầy");
      ctx.strokeStyle = isCheckout ? "#faad14" : "#1890ff";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.stroke();

      ctx.fillStyle = isCheckout ? "rgba(250, 173, 20, 0.15)" : "rgba(24, 144, 255, 0.1)";
      ctx.fill();

      const firstX = zone.points[0][0] * displayW;
      const firstY = zone.points[0][1] * displayH;
      ctx.font = "bold 12px sans-serif";
      ctx.fillStyle = isCheckout ? "#faad14" : "#1890ff";
      ctx.setLineDash([]);
      ctx.fillText(
        isCheckout ? "🛒 KHU VỰC THANH TOÁN (PAYZONE)" : `📦 ${zone.name.toUpperCase()}`,
        firstX + 6,
        firstY + 16
      );
      ctx.restore();
    });

    // 2. Vẽ Khung nhận diện Bounding Boxes (Chỉ vẽ Khách hàng & Sản phẩm thực tế)
    if (!detections || !Array.isArray(detections) || detections.length === 0) return;

    detections.forEach((d) => {
      const className = String(d.class_name || "").toLowerCase();
      const isPerson = className === "person";

      // Lọc bỏ các đối tượng nội thất/đồ vật không phải sản phẩm (ghế, sách, mèo, bàn...)
      if (!isPerson) {
        const isIgnored = IGNORED_COCO_CLASSES.has(className);
        if (isIgnored && !d.sku) return;
      }

      const bbox = d.bbox || {};
      const x1 = Number(bbox.x1 ?? 0) * scaleX;
      const y1 = Number(bbox.y1 ?? 0) * scaleY;
      const x2 = Number(bbox.x2 ?? 0) * scaleX;
      const y2 = Number(bbox.y2 ?? 0) * scaleY;
      const boxW = x2 - x1;
      const boxH = y2 - y1;

      const strokeColor = isPerson ? "#00f0ff" : "#00ff66";
      const labelBgColor = isPerson ? "rgba(0, 200, 255, 0.9)" : "rgba(0, 230, 80, 0.9)";

      ctx.save();
      ctx.setLineDash([]);
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 3;
      ctx.strokeRect(x1, y1, boxW, boxH);

      ctx.fillStyle = isPerson ? "rgba(0, 240, 255, 0.15)" : "rgba(0, 255, 102, 0.15)";
      ctx.fillRect(x1, y1, boxW, boxH);

      const confStr = d.confidence != null ? `${(d.confidence * 100).toFixed(0)}%` : "";
      const displayLabel = d.sku || d.class_name?.toUpperCase() || "SP";
      const labelText = isPerson
        ? `👤 KHÁCH HÀNG #${d.track_id ?? ""} (${confStr})`
        : `📦 ${displayLabel} (${confStr})`;

      ctx.font = "bold 13px sans-serif";
      const textWidth = ctx.measureText(labelText).width;
      const labelHeight = 22;
      const labelY = Math.max(0, y1 - labelHeight);

      ctx.fillStyle = labelBgColor;
      ctx.fillRect(x1, labelY, textWidth + 12, labelHeight);

      ctx.fillStyle = "#000000";
      ctx.fillText(labelText, x1 + 6, labelY + 15);
      ctx.restore();
    });
  }, [roiZones]);

  useEffect(() => {
    if (!videoUrl) return;
    drawDetectionsOverlay([]);
  }, [roiZones, videoUrl, drawDetectionsOverlay]);

  const clearOverlayCanvas = useCallback(() => {
    const overlayCanvas = overlayCanvasRef.current;
    if (!overlayCanvas) return;
    const ctx = overlayCanvas.getContext("2d");
    if (ctx) ctx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  }, []);

  const addLog = useCallback(
    (type: LogItem["type"], msg: string, detail?: string) => {
      const time = new Date().toLocaleTimeString("vi-VN");
      setLogs((prev) => [
        { id: `${Date.now()}-${Math.random()}`, time, type, message: msg, detail },
        ...prev.slice(0, 49),
      ]);
    },
    []
  );

  useEffect(() => {
    (async () => {
      try {
        const [orgRes, branchRes] = await Promise.all([
          getOrganization(),
          listBranches({ skip: 0, limit: 200 }),
        ]);
        setOrganizationId(orgRes.id);
        setBranches(branchRes.items);
        if (branchRes.items.length) setBranchId(branchRes.items[0].id);
      } catch {
        message.error("Không tải được thông tin tổ chức");
      }
    })();
  }, []);

  useEffect(() => {
    listTrainingJobs()
      .then((res) => {
        setTrainingJobs(
          res.items.filter((j) => j.status === "succeeded" && Boolean(j.weight_key)),
        );
      })
      .catch(() => {
        setTrainingJobs([]);
      });
  }, []);

  const modelSelectOptions = useMemo(() => {
    const bbox = trainingJobs.filter((j) => jobKind(j) === "bbox");
    const crop = trainingJobs.filter((j) => jobKind(j) === "crop");
    const toOpts = (jobs: TrainingJob[]) =>
      jobs.map((j) => ({
        label: jobSelectLabel(j),
        value: j.weight_key as string,
      }));
    return [
      { label: "Model đang triển khai (live)", value: "live" },
      ...(bbox.length
        ? [{ label: "Train từ nhãn bbox", options: toOpts(bbox) }]
        : []),
      ...(crop.length
        ? [{ label: "Train AI (crop 1 SKU)", options: toOpts(crop) }]
        : []),
    ];
  }, [trainingJobs]);

  useEffect(() => {
    if (!branchId) return;
    (async () => {
      try {
        const res = await listCameras({ branch_id: branchId, is_active: true, limit: 100 });
        setCameras(res.items);
        const preferred = res.items.find((c) => c.is_checkout_zone) ?? res.items[0];
        setCameraId(preferred?.id);
      } catch {
        setCameras([]);
      }
    })();
  }, [branchId]);

  const [hasStartedAnalysis, setHasStartedAnalysis] = useState(false);
  const videoStartTimeRef = useRef<number | null>(null);

  const loadCarts = useCallback(async () => {
    if (!branchId) return;
    setCartsLoading(true);
    try {
      const [activeRes, pendingRes] = await Promise.all([
        listCarts({ branch_id: branchId, status: "active", limit: 100 }),
        listCarts({ branch_id: branchId, status: "pending_checkout", limit: 100 }),
      ]);
      const allCarts = [...pendingRes.items, ...activeRes.items];

      if (!hasStartedAnalysis || videoStartTimeRef.current === null) {
        setCarts([]);
      } else {
        const startTimeIso = new Date(videoStartTimeRef.current - 2000).toISOString();
        const filteredCarts = allCarts.filter(
          (c) => (c.created_at && c.created_at >= startTimeIso) || (c.updated_at && c.updated_at >= startTimeIso)
        );
        setCarts(filteredCarts);
      }
    } catch {
      // silent
    } finally {
      setCartsLoading(false);
    }
  }, [branchId, hasStartedAnalysis]);

  useEffect(() => {
    loadCarts();
    const id = window.setInterval(loadCarts, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [loadCarts]);

  // WebSocket for realtime updates — ONLY log to timeline when video analysis is running!
  useEffect(() => {
    if (!branchId) return;
    let ws: WebSocket | null = null;
    let retry: number | null = null;
    let cancelled = false;
    const connect = () => {
      const token = tokenStore.getAccess();
      if (!token || cancelled) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const host =
        window.location.port === "3000"
          ? `${window.location.hostname}:8000`
          : window.location.host;
      ws = new WebSocket(
        `${proto}://${host}/ws/carts?token=${encodeURIComponent(token)}&branch_id=${branchId}`
      );
      ws.onopen = () => setWsConnected(true);
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data?.type === "cart_update" && runningRef.current) {
            const act = data.action;
            if (act === "cart_line_added" || act === "line_added") {
              addLog("add", `🛒 Thêm sản phẩm vào giỏ`, `Giỏ ${data.cart_id?.slice(0, 8)} • ${formatMoney(data.total_amount || "0", data.currency || "VND")}`);
            } else if (act === "checkout_pending" || act === "checkout_requested") {
              addLog("checkout", `⚡ Đóng băng hoá đơn chờ xác nhận`, `Giỏ ${data.cart_id?.slice(0, 8)}`);
            } else if (act === "cart_created") {
              addLog("scan", `✨ Mở giỏ hàng mới`, `Phiên ${data.cart_id?.slice(0, 8)}`);
            } else if (act === "cart_abandoned") {
              addLog("remove", `🗑️ Giỏ hàng bị hủy`);
            }
          }
        } catch {}
        loadCarts();
      };
      ws.onclose = () => {
        setWsConnected(false);
        if (cancelled) return;
        retry = window.setTimeout(connect, 5_000);
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      cancelled = true;
      setWsConnected(false);
      if (retry) window.clearTimeout(retry);
      ws?.close();
    };
  }, [branchId, loadCarts, addLog]);

  const handleVideoUpload = (file: File) => {
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    const url = URL.createObjectURL(file);
    setVideoFile(file);
    setVideoUrl(url);
    setIsRunning(false);
    setIsPaused(false);
    setHasStartedAnalysis(false);
    videoStartTimeRef.current = null;
    setCarts([]);
    setFramesProcessed(0);
    setFramesAccepted(0);
    setLastFrameResult(null);
    stopRef.current = true;
    runningRef.current = false;
    addLog("info", `📂 Đã tải video: ${file.name}`, `Kích thước: ${(file.size / 1024 / 1024).toFixed(1)} MB`);
    return false;
  };

  const resetSession = async (camId?: string) => {
    try {
      const form = new FormData();
      if (camId) form.append("camera_id", camId);
      await fetch(AI_RESET_URL, {
        method: "POST",
        headers: { "X-AI-Engine-Key": AI_ENGINE_KEY },
        body: form,
      });
      addLog("info", "Reset session AI engine", "Gio hang moi se duoc tao cho video nay");
    } catch {
      // non-fatal
    }
  };

  const captureAndSendFrame = useCallback(async (): Promise<void> => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !organizationId || !branchId) return;
    if (video.ended) return;

    let autoPaused = false;
    if (pauseForAi && !video.paused && !userPausedRef.current) {
      autoPausingRef.current = true;
      video.pause();
      autoPausingRef.current = false;
      autoPaused = true;
    }

    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      if (autoPaused && !userPausedRef.current && !stopRef.current) {
        video.play().catch(() => {});
      }
      return;
    }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.85)
    );
    if (!blob) {
      if (autoPaused && !userPausedRef.current && !stopRef.current) {
        video.play().catch(() => {});
      }
      return;
    }

    const form = new FormData();
    form.append("organization_id", organizationId);
    form.append("branch_id", branchId);
    if (cameraId) form.append("camera_id", cameraId);
    form.append("manual_scan", "false");
    form.append("min_confidence", String(minConfidence));
    form.append("recognize_face", "false");
    if (weightKey && weightKey !== "live") {
      form.append("weight_key", weightKey);
    }
    if (roiZones.length > 0) {
      form.append("skip_roi", "false");
      form.append("roi_zones", JSON.stringify(roiZones));
    } else {
      form.append("skip_roi", "true");
    }
    form.append("image", new File([blob], "frame.jpg", { type: "image/jpeg" }));

    try {
      const res = await fetch(AI_FRAME_URL, {
        method: "POST",
        headers: { "X-AI-Engine-Key": AI_ENGINE_KEY },
        body: form,
      });

      if (!res.ok) {
        const text = await res.text().catch(() => "");
        addLog("error", `Frame bị reject (${res.status})`, text.slice(0, 100));
        return;
      }

      const result = await res.json();
      const detections = result?.detections || result?.frame_pipeline?.detections || [];
      const products: number = result?.products ?? result?.frame_pipeline?.products ?? 0;
      const persons: number = result?.persons ?? result?.frame_pipeline?.persons ?? 0;
      const events: any[] = result?.emitted_events || result?.frame_pipeline?.emitted_events || [];
      const accepted = events.filter((e) => e?.backend?.body?.accepted === true).length;
      const elapsed = result?.elapsed_ms;
      const modelName = typeof result?.model === "string"
        ? result.model.split(/[/\\]/).pop()
        : null;

      // Draw detection bounding boxes (people & products) on overlay canvas!
      drawDetectionsOverlay(detections);

      setFramesProcessed((n) => n + 1);
      if (accepted > 0) setFramesAccepted((n) => n + accepted);

      const detectedSkus = events
        .filter((e) => e?.event?.product_sku && e?.backend?.body?.accepted === true)
        .map((e) => e.event.product_sku)
        .join(", ");

      const elapsedPart =
        typeof elapsed === "number" ? ` | ⏱ ${Math.round(elapsed)} ms` : "";
      const modelPart = modelName ? ` | ${modelName}` : "";
      setLastFrameResult(
        `👤 ${persons} người | 📦 ${products} SP${detectedSkus ? ` | ✅ ${detectedSkus}` : ""}${elapsedPart}${modelPart}`
      );

      if (detectedSkus) {
        addLog("add", `🔍 Phát hiện & Nhận dạng SKU: ${detectedSkus}`, `${products} sản phẩm trong khung${elapsedPart}`);
      }
    } catch (err) {
      addLog("error", "Lỗi gửi frame", String(err));
    } finally {
      if (autoPaused && !userPausedRef.current && !stopRef.current) {
        video.play().catch(() => {});
      }
    }
  }, [organizationId, branchId, cameraId, minConfidence, addLog, drawDetectionsOverlay, roiZones, pauseForAi, weightKey]);

  const wakeLoop = useCallback(() => {
    loopWakeRef.current.forEach((resolve) => resolve());
    loopWakeRef.current.clear();
  }, []);

  const waitMsOrWake = useCallback((ms: number) => {
    return new Promise<void>((resolve) => {
      const done = () => {
        loopWakeRef.current.delete(done);
        window.clearTimeout(timer);
        resolve();
      };
      loopWakeRef.current.add(done);
      const timer = window.setTimeout(done, ms);
    });
  }, []);

  const waitWhileUserPaused = useCallback(() => {
    const video = videoRef.current;
    return new Promise<void>((resolve) => {
      if (!video || !video.paused || video.ended || stopRef.current || !userPausedRef.current) {
        resolve();
        return;
      }
      const finish = () => {
        video.removeEventListener("play", finish);
        video.removeEventListener("seeked", finish);
        window.clearInterval(poll);
        resolve();
      };
      video.addEventListener("play", finish);
      video.addEventListener("seeked", finish);
      const poll = window.setInterval(() => {
        if (stopRef.current || !userPausedRef.current || !video.paused) finish();
      }, 200);
    });
  }, []);

  const runLoop = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    stopRef.current = false;
    const video = videoRef.current;
    if (!video) { runningRef.current = false; return; }

    const modelHint = weightKey !== "live" ? ` · model ${weightKey.split("/").pop()}` : " · model live";
    addLog("info", "▶️ Bắt đầu phân tích video", `Gửi frame mỗi ${frameInterval}s${pauseForAi ? " · tạm video khi gửi AI" : ""}${modelHint}`);

    while (!stopRef.current) {
      if (video.ended) {
        addLog("info", "🏁 Video kết thúc", "Phân tích hoàn tất");
        break;
      }
      await captureAndSendFrame();
      if (stopRef.current) break;
      if (userPausedRef.current && video.paused) {
        await waitWhileUserPaused();
      } else {
        await waitMsOrWake(frameInterval * 1000);
      }
    }

    runningRef.current = false;
    setIsRunning(false);
    setIsPaused(false);
  }, [captureAndSendFrame, frameInterval, addLog, pauseForAi, weightKey, waitMsOrWake, waitWhileUserPaused]);

  const handleStart = async () => {
    const video = videoRef.current;
    if (!video || !videoUrl) { message.warning("Chưa tải video"); return; }
    if (!organizationId || !branchId) { message.warning("Chưa chọn chi nhánh"); return; }

    // Ghi lại thời điểm bắt đầu phân tích video
    videoStartTimeRef.current = Date.now();
    setHasStartedAnalysis(true);

    // 1. Dọn giỏ cũ nếu được bật
    if (cleanBeforeStart && carts.length > 0) {
      try {
        await bulkAbandonCarts(carts.map((c) => c.id), branchId);
        setCarts([]);
        addLog("remove", `🗑️ Đã dọn ${carts.length} giỏ hàng cũ`, "Chuẩn bị phân tích video mới");
      } catch { /* non-fatal */ }
    } else if (cleanBeforeStart) {
      setCarts([]);
    }

    // 2. Reset checkout session -> 1 giỏ mới cho video
    await resetSession(cameraId);

    // 3. Reset video, overlay & logs
    video.currentTime = 0;
    video.play().catch(() => {});
    clearOverlayCanvas();
    setIsRunning(true);
    setIsPaused(false);
    userPausedRef.current = false;
    setFramesProcessed(0);
    setFramesAccepted(0);
    setLogs([]);
    runLoop();
  };

  const handleStop = () => {
    stopRef.current = true;
    userPausedRef.current = false;
    wakeLoop();
    setIsRunning(false);
    setIsPaused(false);
    videoRef.current?.pause();
    clearOverlayCanvas();
    addLog("info", "⏹️ Đã dừng phân tích video");
    loadCarts();
  };

  const handlePause = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused && userPausedRef.current) {
      userPausedRef.current = false;
      video.play().catch(() => {});
      setIsPaused(false);
      wakeLoop();
    } else {
      userPausedRef.current = true;
      video.pause();
      setIsPaused(true);
      wakeLoop();
    }
  };

  const onCheckout = async (cart: Cart) => {
    try {
      const res = await checkoutCart(cart.id);
      message.success(`Đã tạo đơn ${res.order_code}`);
      loadCarts();
    } catch (err) {
      message.error(isAxiosError(err) && err.response?.data?.detail ? String(err.response.data.detail) : "Không thể checkout");
    }
  };

  const onAbandon = async (cart: Cart) => {
    try { await abandonCart(cart.id); message.success("Đã hủy giỏ hàng"); loadCarts(); }
    catch { message.error("Không thể hủy giỏ hàng"); }
  };

  const onBulkAbandon = async () => {
    try {
      const res = await bulkAbandonCarts(carts.map((c) => c.id), branchId);
      message.success(`Đã hủy ${res.abandoned} giỏ hàng`);
      loadCarts();
    } catch { message.error("Hủy hàng loạt thất bại"); }
  };

  const onRemoveLine = async (cart: Cart, lineId: string) => {
    try { await removeCartLine(cart.id, lineId); loadCarts(); }
    catch { message.error("Không xóa được sản phẩm"); }
  };

  const onShowQr = async (cart: Cart) => {
    try { const qr = await getCheckoutQr(cart.id); setQrByCart((prev) => ({ ...prev, [cart.id]: qr })); }
    catch { message.error("Không tải được mã QR"); }
  };

  const onConfirmStaff = async (cart: Cart) => {
    try {
      const res = await confirmCheckoutStaff(cart.id);
      message.success(`Đã xác nhận — đơn ${res.order_code}`);
      setQrByCart((prev) => { const n = { ...prev }; delete n[cart.id]; return n; });
      loadCarts();
    } catch (err) {
      message.error(isAxiosError(err) && err.response?.data?.detail ? String(err.response.data.detail) : "Không thể xác nhận");
    }
  };

  const onCancelCheckout = async (cart: Cart) => {
    try {
      await cancelCheckout(cart.id);
      setQrByCart((prev) => { const n = { ...prev }; delete n[cart.id]; return n; });
      message.info("Đã huỷ chờ xác nhận"); loadCarts();
    } catch { message.error("Không thể huỷ"); }
  };

  const totalRevenue = useMemo(() => carts.reduce((sum, c) => sum + Number(c.total_amount || 0), 0), [carts]);

  return (
    <>
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      {/* Header */}
      <Card>
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Space size="large" wrap>
              <Space>
                <Typography.Text strong>Chi nhánh:</Typography.Text>
                <Select
                  style={{ minWidth: 220 }}
                  placeholder="Chọn chi nhánh"
                  value={branchId}
                  onChange={setBranchId}
                  options={branches.map((b) => ({ label: `${b.code} — ${b.name}`, value: b.id }))}
                />
              </Space>
              <Space>
                <Typography.Text strong>Camera:</Typography.Text>
                <Select
                  style={{ minWidth: 200 }}
                  placeholder="Chọn camera (tùy chọn)"
                  value={cameraId}
                  onChange={setCameraId}
                  allowClear
                  options={cameras.map((c) => ({ label: `${c.name}${c.is_checkout_zone ? " — Quầy" : ""}`, value: c.id }))}
                />
              </Space>
              <Badge status={wsConnected ? "success" : "default"} text={wsConnected ? "Realtime bật" : "Realtime tắt"} />
            </Space>
          </Col>
          <Col>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={loadCarts} loading={cartsLoading}>Làm mới</Button>
              {carts.length > 0 && (
                <Popconfirm title={`Hủy tất cả ${carts.length} giỏ hàng?`} onConfirm={onBulkAbandon} okText="Xóa hết" cancelText="Bỏ">
                  <Button danger icon={<DeleteOutlined />}>Xóa tất cả ({carts.length})</Button>
                </Popconfirm>
              )}
            </Space>
          </Col>
        </Row>
      </Card>

      {/* Video panel */}
      <Card
        title={
          <Space>
            <VideoCameraOutlined />
            <Typography.Text strong>Phân tích Video AI</Typography.Text>
            <Typography.Text type="secondary" style={{ fontWeight: 400 }}>
              (upload video → AI nhận diện từng frame → tự động tạo đơn hàng)
            </Typography.Text>
          </Space>
        }
      >
        <Row gutter={[16, 16]}>
          {/* Controls */}
          <Col xs={24} md={9}>
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <Upload accept="video/*" beforeUpload={handleVideoUpload} showUploadList={false} maxCount={1}>
                <Button icon={<UploadOutlined />} style={{ width: "100%" }}>
                  {videoFile ? `📹 ${videoFile.name}` : "Chọn file video (MP4, AVI...)"}
                </Button>
              </Upload>

              <Button
                icon={<BorderOuterOutlined />}
                onClick={openRoiEditor}
                disabled={!videoFile || isRunning}
                style={{ width: "100%" }}
              >
                Vẽ vùng thanh toán trên video
                {roiZones.length > 0 ? ` (${roiZones.length})` : ""}
              </Button>
              <Button
                size="small"
                type="link"
                onClick={loadCameraRoi}
                disabled={!cameraId || isRunning}
              >
                Nạp vùng đã lưu của camera
              </Button>
              {roiZones.length > 0 ? (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  AI chỉ nhận diện trong {roiZones.length} vùng đã vẽ trên khung video
                  (không dùng vùng camera live nếu góc máy khác).
                </Typography.Text>
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Chưa có vùng — AI quét toàn khung. Nên vẽ vùng mặt quầy trước khi phân tích.
                </Typography.Text>
              )}

              <Card size="small" style={{ background: "#fafafa" }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Gửi frame AI mỗi (giây):
                </Typography.Text>
                <Row align="middle" gutter={8}>
                  <Col flex="auto">
                    <Slider
                      min={1} max={10} step={1}
                      value={frameInterval}
                      onChange={setFrameInterval}
                      disabled={isRunning}
                      marks={{ 1: "1s", 2: "2s", 5: "5s", 10: "10s" }}
                    />
                  </Col>
                  <Col><Tag color="blue">{frameInterval}s</Tag></Col>
                </Row>

                <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 8, display: "block" }}>
                  Độ tin cậy AI tối thiểu (lọc nhiễu):
                </Typography.Text>
                <Row align="middle" gutter={8}>
                  <Col flex="auto">
                    <Slider
                      min={0.3} max={0.9} step={0.05}
                      value={minConfidence}
                      onChange={setMinConfidence}
                      disabled={isRunning}
                      marks={{ 0.3: "30%", 0.6: "60%", 0.8: "80%" }}
                    />
                  </Col>
                  <Col><Tag color="purple">{(minConfidence * 100).toFixed(0)}%</Tag></Col>
                </Row>

                <Space style={{ marginTop: 8 }}>
                  <Switch
                    checked={cleanBeforeStart}
                    onChange={setCleanBeforeStart}
                    size="small"
                    disabled={isRunning}
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    Don sach gio cu truoc khi bat dau
                  </Typography.Text>
                </Space>

                <Space style={{ marginTop: 8 }} align="start">
                  <Switch
                    checked={pauseForAi}
                    onChange={setPauseForAi}
                    size="small"
                    disabled={isRunning}
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    Tạm dừng video khi đang gửi AI — để hệ thống kịp nhận diện,
                    không bỏ khung vì inference chậm hơn phát 1×
                  </Typography.Text>
                </Space>

                <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 12, display: "block" }}>
                  Model để test (không triển khai live):
                </Typography.Text>
                <Select
                  style={{ width: "100%", marginTop: 4 }}
                  value={weightKey}
                  onChange={setWeightKey}
                  disabled={isRunning}
                  options={modelSelectOptions}
                  showSearch
                  optionFilterProp="label"
                />
                <Typography.Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 4 }}>
                  Chọn job Train AI hoặc Train từ nhãn bbox để so sánh tốc độ/độ chính xác.
                  Camera live vẫn dùng model đang triển khai.
                </Typography.Text>
              </Card>

              <Space style={{ width: "100%", justifyContent: "center" }} size="middle">
                {!isRunning ? (
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    onClick={handleStart}
                    disabled={!videoFile || !branchId}
                    size="large"
                    style={{ minWidth: 160, fontWeight: 600 }}
                  >
                    ▶ Bắt đầu phân tích
                  </Button>
                ) : (
                  <>
                    <Button icon={isPaused ? <PlayCircleOutlined /> : <PauseCircleOutlined />} onClick={handlePause} size="large">
                      {isPaused ? "Tiếp tục" : "Tạm dừng"}
                    </Button>
                    <Button
                      danger type="primary"
                      icon={<StopOutlined />}
                      onClick={handleStop}
                      size="large"
                      style={{ minWidth: 120, fontWeight: 600 }}
                    >
                      ⏹ Dừng
                    </Button>
                  </>
                )}
              </Space>

              {(framesProcessed > 0 || isRunning) && (
                <Card size="small" style={{ background: "#f6ffed", border: "1px solid #b7eb8f" }}>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Statistic title="Frames đã gửi" value={framesProcessed} valueStyle={{ fontSize: 20 }} />
                    </Col>
                    <Col span={12}>
                      <Statistic title="Events chấp nhận" value={framesAccepted} valueStyle={{ fontSize: 20, color: "#52c41a" }} />
                    </Col>
                  </Row>
                  {lastFrameResult && (
                    <Typography.Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 6 }}>
                      📊 Frame gần nhất: {lastFrameResult}
                    </Typography.Text>
                  )}
                  {isRunning && (
                    <Progress percent={100} status="active" showInfo={false} strokeColor="#52c41a" style={{ marginTop: 8, marginBottom: 0 }} />
                  )}
                </Card>
              )}

              <Card size="small" title="📋 Nhật ký sự kiện AI" style={{ maxHeight: 260, overflowY: "auto" }}>
                {logs.length === 0 ? (
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    Chưa có sự kiện. Tải video và nhấn Bắt đầu phân tích.
                  </Typography.Text>
                ) : (
                  <Timeline
                    items={logs.map((log) => ({
                      color: log.type === "add" ? "green" : log.type === "checkout" ? "orange" : log.type === "remove" || log.type === "error" ? "red" : "blue",
                      children: (
                        <div style={{ fontSize: 11 }}>
                          <Space size={4}>
                            <Tag style={{ fontSize: 10, margin: 0, padding: "0 4px" }}>{log.time}</Tag>
                            <Typography.Text strong style={{ fontSize: 11 }}>{log.message}</Typography.Text>
                          </Space>
                          {log.detail && <div style={{ color: "#666", fontSize: 10, marginTop: 1 }}>{log.detail}</div>}
                        </div>
                      ),
                    }))}
                  />
                )}
              </Card>
            </Space>
          </Col>

          {/* Video player */}
          <Col xs={24} md={15}>
            <div style={{ position: "relative", background: "#000", borderRadius: 8, overflow: "hidden" }}>
              {videoUrl ? (
                <div style={{ position: "relative", width: "100%" }}>
                  <video
                    ref={videoRef}
                    src={videoUrl}
                    controls
                    style={{ width: "100%", maxHeight: 480, display: "block" }}
                    onEnded={() => { if (isRunning) handleStop(); }}
                    onLoadedData={() => drawDetectionsOverlay([])}
                    onPause={() => {
                      if (autoPausingRef.current || stopRef.current) return;
                      if (runningRef.current) {
                        userPausedRef.current = true;
                        setIsPaused(true);
                        wakeLoop();
                      }
                    }}
                    onPlay={() => {
                      if (autoPausingRef.current) return;
                      userPausedRef.current = false;
                      setIsPaused(false);
                      wakeLoop();
                    }}
                    onSeeked={() => {
                      if (runningRef.current && userPausedRef.current) wakeLoop();
                    }}
                  />
                  <canvas
                    ref={overlayCanvasRef}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      height: "100%",
                      pointerEvents: "none",
                    }}
                  />
                </div>
              ) : (
                <div style={{ height: 320, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12 }}>
                  <VideoCameraOutlined style={{ fontSize: 56, color: "#444" }} />
                  <Typography.Text style={{ color: "#888" }}>Chọn file video để bắt đầu phân tích AI</Typography.Text>
                </div>
              )}
              <canvas ref={canvasRef} style={{ display: "none" }} />
              {isRunning && !isPaused && (
                <div style={{ position: "absolute", top: 10, right: 10, background: "rgba(82,196,26,0.92)", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 700, boxShadow: "0 2px 8px rgba(0,0,0,0.25)" }}>
                  🔴 AI đang phân tích
                </div>
              )}
              {isPaused && (
                <div style={{ position: "absolute", top: 10, right: 10, background: "rgba(250,140,22,0.92)", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 700 }}>
                  ⏸ Đã tạm dừng
                </div>
              )}
            </div>

            {!videoFile && (
              <Alert
                message="Hướng dẫn sử dụng"
                description={
                  <ol style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                    <li>Chọn chi nhánh và camera quầy (để ghi giỏ vào đúng chi nhánh)</li>
                    <li>Nhấn <strong>"Chọn file video"</strong> để tải video lên</li>
                    <li>Tua tới khung thấy mặt quầy, nhấn <strong>"Vẽ vùng thanh toán trên video"</strong> — AI chỉ quét trong vùng đó</li>
                    <li>Chọn tần suất gửi frame (2s phù hợp với hầu hết video)</li>
                    <li>Nhấn <strong>"▶ Bắt đầu phân tích"</strong> — AI quét từng frame tự động</li>
                    <li>Sản phẩm được nhận diện sẽ tự thêm vào giỏ hàng bên dưới</li>
                    <li>Nhấn <strong>"⏹ Dừng"</strong> để kết thúc bất cứ lúc nào</li>
                  </ol>
                }
                type="info"
                showIcon
                style={{ marginTop: 12 }}
              />
            )}
          </Col>
        </Row>
      </Card>

      {/* Stats */}
      <Row gutter={16}>
        <Col span={8}>
          <Card>
            <Statistic title="Giỏ hàng đang mở" value={carts.length} prefix={<ShoppingCartOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Tổng giá trị chờ thanh toán"
              value={totalRevenue}
              formatter={(v) => new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND", maximumFractionDigits: 0 }).format(Number(v))}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="Tổng sản phẩm trong giỏ" value={carts.reduce((s, c) => s + c.lines.length, 0)} prefix={<CheckCircleOutlined />} />
          </Card>
        </Col>
      </Row>

      {/* Cart list */}
      <Card title={<Space><ShoppingCartOutlined /><Typography.Text strong>Giỏ hàng được tạo từ video</Typography.Text></Space>}>
        {carts.length === 0 ? (
          <Empty description="Chưa có giỏ hàng. Phân tích video để AI tự động tạo đơn." />
        ) : (
          <List
            dataSource={carts}
            renderItem={(cart) => (
              <List.Item key={cart.id}>
                <Card
                  size="small" style={{ width: "100%", borderRadius: 8 }}
                  title={
                    <Space>
                      <Tag color={cart.status === "active" ? "green" : cart.status === "pending_checkout" ? "orange" : "default"}>
                        {cart.status === "active" ? "ACTIVE" : cart.status === "pending_checkout" ? "CHỜ XÁC NHẬN" : cart.status}
                      </Tag>
                      <Typography.Text style={{ fontSize: 12, color: "#888" }}>{cart.id.slice(0, 8)}</Typography.Text>
                      <Tag color="purple">{cart.session_id?.split(":track:")[1] ?? "—"}</Tag>
                    </Space>
                  }
                  extra={
                    <Space size="small">
                      {cart.status === "active" && (
                        <>
                          <Tooltip title="Thanh toán ngay">
                            <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => onCheckout(cart)}>Checkout</Button>
                          </Tooltip>
                          <Tooltip title="Xem QR xác nhận">
                            <Button size="small" icon={<QrcodeOutlined />} onClick={() => onShowQr(cart)} />
                          </Tooltip>
                          <Popconfirm title="Hủy giỏ hàng?" onConfirm={() => onAbandon(cart)} okText="Hủy" cancelText="Không">
                            <Button size="small" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        </>
                      )}
                      {cart.status === "pending_checkout" && (
                        <>
                          <Button size="small" type="primary" icon={<CheckCircleOutlined />} onClick={() => onConfirmStaff(cart)}>Xác nhận hộ</Button>
                          <Button size="small" onClick={() => onCancelCheckout(cart)}>Huỷ chờ</Button>
                        </>
                      )}
                    </Space>
                  }
                >
                  {qrByCart[cart.id] && (
                    <div style={{ textAlign: "center", marginBottom: 8 }}>
                      <img src={`data:image/png;base64,${qrByCart[cart.id].qr_base64}`} alt="QR" style={{ width: 100, height: 100 }} />
                      <br />
                      <Typography.Text copyable style={{ fontSize: 11 }}>{qrByCart[cart.id].confirm_url}</Typography.Text>
                    </div>
                  )}
                  {(cart.lines || []).length === 0 ? (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>Giỏ trống</Typography.Text>
                  ) : (
                    <List
                      size="small"
                      dataSource={cart.lines}
                      renderItem={(line: any) => (
                        <List.Item
                          key={line.line_id}
                          extra={
                            <Space>
                              <Typography.Text strong style={{ fontSize: 12 }}>{formatMoney(line.subtotal, cart.currency)}</Typography.Text>
                              {cart.status === "active" && (
                                <Tooltip title="Xóa dòng">
                                  <Button size="small" danger icon={<DeleteOutlined />} onClick={() => onRemoveLine(cart, line.line_id)} />
                                </Tooltip>
                              )}
                            </Space>
                          }
                        >
                          <Space size="small">
                            <Tag color="blue" style={{ fontWeight: 600 }}>{line.sku}</Tag>
                            <Typography.Text style={{ fontSize: 12 }}>{line.product_name}</Typography.Text>
                            <Tag>x{line.quantity}</Tag>
                            {line.confidence != null && line.confidence < 0.7 && (
                              <Tooltip title={`Độ tin cậy AI: ${(line.confidence * 100).toFixed(0)}%`}>
                                <Tag color="orange">⚠️ {(line.confidence * 100).toFixed(0)}%</Tag>
                              </Tooltip>
                            )}
                          </Space>
                        </List.Item>
                      )}
                    />
                  )}
                  <Divider style={{ margin: "8px 0" }} />
                  <Row justify="space-between">
                    <Col><Typography.Text type="secondary" style={{ fontSize: 11 }}>{cart.lines?.length ?? 0} sản phẩm</Typography.Text></Col>
                    <Col><Typography.Text strong>Tổng: {formatMoney(cart.total_amount, cart.currency)}</Typography.Text></Col>
                  </Row>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Card>
    </Space>
      <RoiZoneEditor
        camera={selectedCamera ?? null}
        open={roiEditorOpen}
        onClose={() => setRoiEditorOpen(false)}
        persistToCamera={false}
        snapshotSrc={roiSnapshot}
        initialZones={roiZones}
        title="Vẽ vùng thanh toán trên video"
        onApply={(zones) => {
          setRoiZones(zones);
          drawDetectionsOverlay([]);
        }}
      />
    </>
  );
}
