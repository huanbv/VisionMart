/**
 * VideoAnalysisPage — Phân tích video file qua AI pipeline.
 *
 * Cơ chế:
 *  1. Người dùng upload video (MP4/AVI/MOV...).
 *  2. Xem/tua video bình thường — không gửi AI (VPS không GPU vẫn mượt).
 *  3. Tới đoạn quầy: tạm dừng → Kích hoạt AI tại khung này (vùng thanh toán).
 *  4. Tuỳ chọn tự chạy từ đây: tua từng bước, video đứng yên lúc inference.
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
  ThunderboltOutlined,
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
import VideoLibraryGrid from "@/components/VideoLibraryGrid";
import { listTrainingJobs, type TrainingJob } from "@/api/aiTraining";
import {
  mapNormToContent,
  mapPixelToContent,
  videoContentRect,
} from "@/utils/videoContentRect";
import {
  addLibraryVideo,
  deleteLibraryVideo,
  getLibraryVideo,
  listLibraryVideos,
  saveLibraryRoi,
  backfillLibraryPosters,
  type VideoLibraryMeta,
} from "@/utils/videoLibrary";

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
  const [libraryItems, setLibraryItems] = useState<VideoLibraryMeta[]>([]);
  const [selectedVideoId, setSelectedVideoId] = useState<string | undefined>();
  const [isRunning, setIsRunning] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [frameInterval, setFrameInterval] = useState(2);
  const [minConfidence, setMinConfidence] = useState(0.6);
  const [cleanBeforeStart, setCleanBeforeStart] = useState(true);
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
  const scanSessionRef = useRef<string | null>(null);
  const sendingRef = useRef(false);
  const lastDetectionsRef = useRef<any[]>([]);
  const selectedVideoIdRef = useRef<string | undefined>(undefined);
  const videoUrlRef = useRef<string | null>(null);
  selectedVideoIdRef.current = selectedVideoId;
  videoUrlRef.current = videoUrl;

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
        const vidId = selectedVideoIdRef.current;
        if (vidId) {
          void saveLibraryRoi(vidId, z).then(() =>
            setLibraryItems((prev) =>
              prev.map((it) => (it.id === vidId ? { ...it, roiZones: z } : it)),
            ),
          );
        }
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

    lastDetectionsRef.current = Array.isArray(detections) ? detections : [];

    const displayW = video.clientWidth || video.videoWidth || 640;
    const displayH = video.clientHeight || video.videoHeight || 480;

    overlayCanvas.width = displayW;
    overlayCanvas.height = displayH;

    const ctx = overlayCanvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, displayW, displayH);

    const vidW = video.videoWidth || displayW;
    const vidH = video.videoHeight || displayH;
    // Map onto the painted frame (object-fit: contain), not the letterbox bars.
    const content = videoContentRect(displayW, displayH, vidW, vidH);

    // 1. Vẽ Khu vực thanh toán (ROI Payzone)
    const zones = roiZones;
    zones.forEach((zone) => {
      if (!zone.points || zone.points.length < 3) return;
      ctx.save();
      ctx.beginPath();
      zone.points.forEach(([nx, ny], idx) => {
        const { x: px, y: py } = mapNormToContent(nx, ny, content);
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

      const labelAt = mapNormToContent(zone.points[0][0], zone.points[0][1], content);
      ctx.font = "bold 12px sans-serif";
      ctx.fillStyle = isCheckout ? "#faad14" : "#1890ff";
      ctx.setLineDash([]);
      ctx.fillText(
        isCheckout ? "🛒 KHU VỰC THANH TOÁN (PAYZONE)" : `📦 ${zone.name.toUpperCase()}`,
        labelAt.x + 6,
        labelAt.y + 16
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
      const p1 = mapPixelToContent(Number(bbox.x1 ?? 0), Number(bbox.y1 ?? 0), vidW, vidH, content);
      const p2 = mapPixelToContent(Number(bbox.x2 ?? 0), Number(bbox.y2 ?? 0), vidW, vidH, content);
      const x1 = p1.x;
      const y1 = p1.y;
      const x2 = p2.x;
      const y2 = p2.y;
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
    drawDetectionsOverlay(lastDetectionsRef.current);
  }, [roiZones, videoUrl, drawDetectionsOverlay]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !videoUrl) return;
    const redraw = () => drawDetectionsOverlay(lastDetectionsRef.current);
    const ro = new ResizeObserver(redraw);
    ro.observe(video);
    window.addEventListener("resize", redraw);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", redraw);
    };
  }, [videoUrl, drawDetectionsOverlay]);

  useEffect(() => {
    let cancelled = false;
    listLibraryVideos()
      .then((items) => {
        if (!cancelled) setLibraryItems(items);
        return backfillLibraryPosters((id, poster) => {
          if (!cancelled) {
            setLibraryItems((prev) =>
              prev.map((it) => (it.id === id ? { ...it, poster } : it)),
            );
          }
        });
      })
      .catch(() => {
        if (!cancelled) setLibraryItems([]);
      });
    return () => {
      cancelled = true;
      if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
    };
  }, []);

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

  const activateLibraryVideo = useCallback(async (id: string) => {
    const row = await getLibraryVideo(id);
    if (!row) {
      message.error("Không đọc được video trong thư viện");
      return;
    }
    stopRef.current = true;
    runningRef.current = false;
    setIsRunning(false);
    setIsSending(false);
    setHasStartedAnalysis(false);
    videoStartTimeRef.current = null;
    scanSessionRef.current = null;
    if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
    const file = new File([row.blob], row.name, { type: row.type || "video/mp4" });
    const url = URL.createObjectURL(row.blob);
    setVideoFile(file);
    setVideoUrl(url);
    setSelectedVideoId(id);
    setRoiZones(row.roiZones || []);
    lastDetectionsRef.current = [];
    setFramesProcessed(0);
    setFramesAccepted(0);
    setLastFrameResult(null);
    const n = row.roiZones?.length ?? 0;
    addLog(
      "info",
      `📂 Đã chọn video: ${row.name}`,
      n
        ? `Dùng lại ${n} vùng thanh toán đã lưu — không cần vẽ lại`
        : `Kích thước: ${(row.size / 1024 / 1024).toFixed(1)} MB · chưa có vùng, hãy vẽ trước khi phân tích`,
    );
  }, [addLog]);

  const handleVideoUpload = (file: File) => {
    void (async () => {
      try {
        const meta = await addLibraryVideo(file);
        const items = await listLibraryVideos();
        setLibraryItems(items);
        await activateLibraryVideo(meta.id);
      } catch (err) {
        if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
        setVideoFile(file);
        setVideoUrl(URL.createObjectURL(file));
        setSelectedVideoId(undefined);
        message.warning(
          err instanceof Error
            ? `${err.message} Video vẫn dùng được trong phiên này.`
            : "Không lưu thư viện — video vẫn dùng được trong phiên này.",
        );
      }
    })();
    return false;
  };

  const handleDeleteLibraryVideo = async (id: string) => {
    await deleteLibraryVideo(id);
    const items = await listLibraryVideos();
    setLibraryItems(items);
    if (selectedVideoId === id) {
      stopRef.current = true;
      runningRef.current = false;
      setIsRunning(false);
      scanSessionRef.current = null;
      if (videoUrlRef.current) URL.revokeObjectURL(videoUrlRef.current);
      setVideoFile(null);
      setVideoUrl(null);
      setSelectedVideoId(undefined);
      setRoiZones([]);
    }
    message.success("Đã xóa video khỏi thư viện");
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
    if (sendingRef.current) return;
    sendingRef.current = true;

    autoPausingRef.current = true;
    video.pause();
    autoPausingRef.current = false;
    userPausedRef.current = true;
    setIsPaused(true);

    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      sendingRef.current = false;
      return;
    }
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.85)
    );
    if (!blob) {
      sendingRef.current = false;
      return;
    }

    const form = new FormData();
    form.append("organization_id", organizationId);
    form.append("branch_id", branchId);
    if (cameraId) form.append("camera_id", cameraId);
    // Quét như Tải ảnh: một giỏ theo vùng thanh toán, không tách theo từng người trong khung.
    form.append("manual_scan", "true");
    form.append("min_confidence", String(minConfidence));
    form.append("recognize_face", "false");
    if (scanSessionRef.current) {
      form.append("scan_session", scanSessionRef.current);
    }
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
      } else {
        addLog("info", "AI đã quét khung này", `${persons} người · ${products} SP${elapsedPart || ""}`);
      }
    } catch (err) {
      addLog("error", "Lỗi gửi frame", String(err));
    } finally {
      sendingRef.current = false;
    }
  }, [organizationId, branchId, cameraId, minConfidence, addLog, drawDetectionsOverlay, roiZones, weightKey]);

  const waitSeeked = (video: HTMLVideoElement) =>
    new Promise<void>((resolve) => {
      const done = () => {
        video.removeEventListener("seeked", done);
        resolve();
      };
      video.addEventListener("seeked", done);
      window.setTimeout(done, 800);
    });

  const ensureAnalysisSession = async () => {
    if (scanSessionRef.current) return;
    const token = `vid-${(selectedVideoId || "tmp").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 40)}-${Date.now().toString(36)}`;
    scanSessionRef.current = token;
    videoStartTimeRef.current = Date.now();
    setHasStartedAnalysis(true);
    if (cleanBeforeStart && carts.length > 0 && branchId) {
      try {
        await bulkAbandonCarts(carts.map((c) => c.id), branchId);
        setCarts([]);
        addLog("remove", `🗑️ Đã dọn ${carts.length} giỏ hàng cũ`, "Giỏ mới cho phiên phân tích này");
      } catch { /* non-fatal */ }
    } else if (cleanBeforeStart) {
      setCarts([]);
    }
    await resetSession(cameraId);
    setFramesProcessed(0);
    setFramesAccepted(0);
  };

  const handleActivateAi = async () => {
    const video = videoRef.current;
    if (!video || !videoUrl) { message.warning("Chưa chọn video"); return; }
    if (!organizationId || !branchId) { message.warning("Chưa chọn chi nhánh"); return; }
    if (!video.videoWidth) {
      message.warning("Chờ video tải xong, tua tới đoạn cần quét, rồi kích hoạt AI");
      return;
    }
    await ensureAnalysisSession();
    video.pause();
    userPausedRef.current = true;
    setIsPaused(true);
    setIsSending(true);
    const t = video.currentTime;
    addLog("info", "⚡ Kích hoạt AI tại khung này", `t=${t.toFixed(1)}s · tạm dừng video · quét vùng thanh toán`);
    await captureAndSendFrame();
    setIsSending(false);
    loadCarts();
  };

  const runStepLoop = useCallback(async () => {
    if (runningRef.current) return;
    runningRef.current = true;
    stopRef.current = false;
    const video = videoRef.current;
    if (!video) { runningRef.current = false; return; }

    addLog("info", "▶️ Tự chạy AI từ đây", `Video đứng yên, mỗi ${frameInterval}s tua tới khung kế (phù hợp VPS không GPU)`);

    while (!stopRef.current) {
      if (video.ended || video.currentTime >= (video.duration || 0) - 0.05) {
        addLog("info", "🏁 Hết video", "Đã quét tới cuối");
        break;
      }
      await captureAndSendFrame();
      if (stopRef.current) break;
      const next = video.currentTime + frameInterval;
      if (next >= (video.duration || next)) {
        addLog("info", "🏁 Hết video", "Đã quét tới cuối");
        break;
      }
      video.currentTime = next;
      await waitSeeked(video);
    }

    runningRef.current = false;
    setIsRunning(false);
  }, [captureAndSendFrame, frameInterval, addLog]);

  const handleStepFromHere = async () => {
    const video = videoRef.current;
    if (!video || !videoUrl) { message.warning("Chưa chọn video"); return; }
    if (!organizationId || !branchId) { message.warning("Chưa chọn chi nhánh"); return; }
    await ensureAnalysisSession();
    video.pause();
    userPausedRef.current = true;
    setIsPaused(true);
    setIsRunning(true);
    runStepLoop();
  };

  const handleStop = () => {
    stopRef.current = true;
    userPausedRef.current = false;
    setIsRunning(false);
    setIsSending(false);
    scanSessionRef.current = null;
    videoRef.current?.pause();
    setIsPaused(true);
    addLog("info", "⏹️ Đã dừng AI — có thể tua video tiếp, không gửi thêm frame");
    loadCarts();
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
              (thư viện video → AI nhận diện từng frame → tự động tạo đơn hàng)
            </Typography.Text>
          </Space>
        }
      >
        <Row gutter={[16, 16]}>
          <Col span={24}>
            <Space direction="vertical" style={{ width: "100%" }} size="small">
              <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
                <Typography.Text strong>Thư viện video</Typography.Text>
                <Upload
                  accept="video/*"
                  multiple
                  beforeUpload={handleVideoUpload}
                  showUploadList={false}
                  disabled={isRunning}
                >
                  <Button icon={<UploadOutlined />} disabled={isRunning}>
                    Thêm video vào thư viện
                  </Button>
                </Upload>
              </Space>
              <VideoLibraryGrid
                items={libraryItems}
                selectedId={selectedVideoId}
                disabled={isRunning}
                onSelect={(id) => void activateLibraryVideo(id)}
                onDelete={(id) => void handleDeleteLibraryVideo(id)}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                Mỗi ô là một video — vùng thanh toán vẽ trên video đó được nhớ riêng.
                Chọn lại là dùng lại bản đồ, không phải vẽ mỗi lần test.
              </Typography.Text>
            </Space>
          </Col>
          {/* Controls */}
          <Col xs={24} md={9}>
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <Button
                icon={<BorderOuterOutlined />}
                onClick={openRoiEditor}
                disabled={!videoFile || isRunning}
                style={{ width: "100%" }}
              >
                {roiZones.length > 0
                  ? `Sửa vùng thanh toán (${roiZones.length})`
                  : "Vẽ vùng thanh toán cho video này"}
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
                  Đã nhớ {roiZones.length} vùng cho video đang chọn — lần sau chọn lại ô này sẽ dùng luôn.
                </Typography.Text>
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Video này chưa có vùng — AI quét toàn khung. Vẽ vùng mặt quầy một lần, lần sau không phải vẽ lại.
                </Typography.Text>
              )}

              <Card size="small" style={{ background: "#fafafa" }}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Gửi / tua khung AI mỗi (giây) — chỉ khi bấm “Tự chạy AI từ đây”:
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
                    disabled={isRunning || isSending}
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    Dọn giỏ cũ khi kích hoạt AI lần đầu
                  </Typography.Text>
                </Space>

                <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 10 }}
                  message="Xem video trước, AI sau"
                  description="Phát/tua video bình thường (không tốn GPU). Tới đoạn quầy thì tạm dừng rồi bấm Kích hoạt AI — VPS không GPU không phải vừa phát vừa nhận diện."
                />

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

              <Space direction="vertical" style={{ width: "100%" }} size="small">
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  onClick={() => void handleActivateAi()}
                  disabled={!videoFile || !branchId || isSending || isRunning}
                  loading={isSending}
                  size="large"
                  style={{ width: "100%", fontWeight: 600 }}
                >
                  Kích hoạt AI tại khung này
                </Button>
                <Space style={{ width: "100%", justifyContent: "center" }} wrap>
                  <Button
                    icon={<PlayCircleOutlined />}
                    onClick={() => void handleStepFromHere()}
                    disabled={!videoFile || !branchId || isSending || isRunning}
                  >
                    Tự chạy AI từ đây
                  </Button>
                  {(isRunning || isSending) && (
                    <Button danger type="primary" icon={<StopOutlined />} onClick={handleStop}>
                      Dừng AI
                    </Button>
                  )}
                </Space>
              </Space>

              {(framesProcessed > 0 || isRunning || isSending) && (
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
                  {isSending && (
                    <Progress percent={100} status="active" showInfo={false} strokeColor="#faad14" style={{ marginTop: 8, marginBottom: 0 }} />
                  )}
                  {isRunning && !isSending && (
                    <Progress percent={100} status="active" showInfo={false} strokeColor="#52c41a" style={{ marginTop: 8, marginBottom: 0 }} />
                  )}
                </Card>
              )}

              <Card size="small" title="📋 Nhật ký sự kiện AI" style={{ maxHeight: 260, overflowY: "auto" }}>
                {logs.length === 0 ? (
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    Chưa có sự kiện. Phát video tới đoạn quầy, tạm dừng, rồi Kích hoạt AI.
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
                    style={{
                      width: "100%",
                      maxHeight: 480,
                      display: "block",
                      objectFit: "contain",
                      background: "#000",
                    }}
                    onEnded={() => { if (isRunning) handleStop(); }}
                    onLoadedData={() => drawDetectionsOverlay(lastDetectionsRef.current)}
                    onLoadedMetadata={() => drawDetectionsOverlay(lastDetectionsRef.current)}
                    onPause={() => {
                      if (autoPausingRef.current) return;
                      setIsPaused(true);
                    }}
                    onPlay={() => {
                      if (autoPausingRef.current) return;
                      setIsPaused(false);
                      if (runningRef.current) {
                        stopRef.current = true;
                        runningRef.current = false;
                        setIsRunning(false);
                      }
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
                  <Typography.Text style={{ color: "#888" }}>Thêm video vào thư viện, rồi chọn file để phân tích</Typography.Text>
                </div>
              )}
              <canvas ref={canvasRef} style={{ display: "none" }} />
              {isSending && (
                <div style={{ position: "absolute", top: 10, right: 10, background: "rgba(250,140,22,0.92)", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 700, boxShadow: "0 2px 8px rgba(0,0,0,0.25)" }}>
                  ⚡ Đang gửi AI
                </div>
              )}
              {isRunning && !isSending && (
                <div style={{ position: "absolute", top: 10, right: 10, background: "rgba(82,196,26,0.92)", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 700, boxShadow: "0 2px 8px rgba(0,0,0,0.25)" }}>
                  AI tự chạy từ đây
                </div>
              )}
              {isPaused && !isSending && !isRunning && videoUrl && (
                <div style={{ position: "absolute", top: 10, right: 10, background: "rgba(250,140,22,0.92)", color: "#fff", padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 700 }}>
                  ⏸ Đã tạm dừng
                </div>
              )}
            </div>

            {!videoUrl && (
              <Alert
                message="Hướng dẫn sử dụng"
                description={
                  <ol style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                    <li>Chọn chi nhánh và camera quầy (để ghi giỏ vào đúng chi nhánh)</li>
                    <li>Nhấn <strong>"Thêm video vào thư viện"</strong> — hiện dạng lưới. Bấm ô để chọn</li>
                    <li>Vẽ vùng thanh toán <strong>một lần cho từng video</strong>; lần sau chọn lại ô đó là dùng bản đồ đã lưu</li>
                    <li>Phát/tua video <strong>bình thường</strong> tới đoạn cần quét (chưa gửi AI)</li>
                    <li>Tạm dừng, nhấn <strong>Kích hoạt AI tại khung này</strong> — quét vùng thanh toán, một giỏ</li>
                    <li>Tuỳ chọn <strong>Tự chạy AI từ đây</strong> nếu muốn tua từng bước (VPS không GPU)</li>
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
          const vidId = selectedVideoIdRef.current;
          if (vidId) {
            void saveLibraryRoi(vidId, zones).then(() =>
              setLibraryItems((prev) =>
                prev.map((it) => (it.id === vidId ? { ...it, roiZones: zones } : it)),
              ),
            );
          }
          drawDetectionsOverlay([]);
        }}
      />
    </>
  );
}
