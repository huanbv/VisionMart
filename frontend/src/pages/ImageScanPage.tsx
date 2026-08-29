/**
 * Tải ảnh & Quét — phòng lab cho luận văn: từng giai đoạn AI + ảnh + nhật ký.
 * Tách khỏi Giỏ hàng Live để cashier không lẫn với màn hình báo cáo.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Image,
  List,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Steps,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  Upload,
  message,
} from "antd";
import {
  CameraOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  FileWordOutlined,
  PrinterOutlined,
  QrcodeOutlined,
  ReloadOutlined,
  ShoppingCartOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { isAxiosError } from "axios";

import { listBranches, type Branch } from "@/api/tenancy";
import {
  analyzeCameraFrame,
  getTraceStageImageBlob,
  listCameras,
  previewCameraStream,
  tracePipeline,
  type AnalyzeResult,
  type Camera,
  type DebugStep,
  type PipelineTraceResult,
  type TraceStage,
} from "@/api/cameras";
import {
  abandonCart,
  cancelCheckout,
  checkoutCart,
  confirmCheckoutStaff,
  getCart,
  getCheckoutQr,
  removeCartLine,
  type Cart,
  type CartCheckoutQrResponse,
  type CartLine,
} from "@/api/carts";
import { listTrainingJobs, type TrainingJob } from "@/api/aiTraining";
import { listModels } from "@/api/aiReview";
import {
  downloadThesisWord,
  loadThesisImageFromBase64,
  loadThesisImageFromUrl,
} from "@/lib/thesisWordExport";
import CartLinePhoto from "@/components/CartLinePhoto";
import CartLineSkuButton from "@/components/CartLineSkuButton";
import {
  AlgorithmSnippet,
  THESIS_CODE_CSS,
  ThesisAppendix,
} from "@/components/ThesisPipelineLab";
import {
  formatAppendixMarkdown,
  lookupAlgorithm,
  PARAM_GLOSSARY,
} from "@/pages/imageScanAlgorithms";

const { Title, Paragraph, Text } = Typography;

const PHASES = [
  "Nhận ảnh",
  "Tiền xử lý OpenCV",
  "Nhận diện YOLO + SKU",
  "Tạo giỏ hàng",
  "Hoàn tất",
] as const;

function trainingJobKind(job: TrainingJob): "bbox" | "crop" {
  return job.class_map?.["mode"] === "labeled_scenes" ? "bbox" : "crop";
}

function jobMetricHint(job: TrainingJob): string {
  const metrics = job.metrics || {};
  const entry = Object.entries(metrics).find(([k]) => /map50/i.test(k));
  if (!entry || typeof entry[1] !== "number") return "";
  const value = entry[1] <= 1 ? entry[1] * 100 : entry[1];
  return ` · mAP50 ${value.toFixed(0)}%`;
}

function jobSelectLabel(job: TrainingJob): string {
  const date = new Date(job.created_at).toLocaleDateString("vi-VN");
  const live = job.deployed_at ? " · đang live" : "";
  return `${job.name}${jobMetricHint(job)}${live} — ${date}`;
}

function fileName(path: string | null | undefined): string {
  if (!path) return "";
  return path.split(/[\\/]/).pop() || path;
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

function describeDetector(
  weightKey: string,
  jobs: TrainingJob[],
  liveFile: string,
): { kind: "bbox" | "crop" | "live" | "stock"; title: string; detail: string; color: string } {
  if (weightKey && weightKey !== "live") {
    const job = jobs.find((j) => j.weight_key === weightKey);
    const kind = job ? trainingJobKind(job) : "crop";
    const title = kind === "bbox" ? "Train từ nhãn bbox (Gán nhãn bbox)" : "Train AI (crop 1 SKU)";
    return {
      kind,
      title,
      detail: job ? `${job.name} · ${weightKey}` : weightKey,
      color: kind === "bbox" ? "purple" : "cyan",
    };
  }
  const deployed = jobs
    .filter((j) => j.deployed_at)
    .sort((a, b) => +new Date(b.deployed_at || 0) - +new Date(a.deployed_at || 0))[0];
  const liveBase = fileName(liveFile) || "yolov8n.pt";
  if (deployed) {
    const kind = trainingJobKind(deployed);
    const title =
      kind === "bbox"
        ? "Model live — Train từ nhãn bbox"
        : "Model live — Train AI (crop 1 SKU)";
    return {
      kind: "live",
      title,
      detail: `${deployed.name} · ${deployed.weight_key || liveBase}`,
      color: kind === "bbox" ? "purple" : "cyan",
    };
  }
  const stock = !liveBase || liveBase === "yolov8n.pt";
  return {
    kind: stock ? "stock" : "live",
    title: stock ? "Model live — YOLOv8n COCO (chưa deploy job)" : "Model đang triển khai (live)",
    detail: liveBase,
    color: stock ? "default" : "blue",
  };
}

type LogKind = "info" | "ok" | "warn" | "err";
interface ScanLog {
  id: string;
  time: string;
  phase: string;
  kind: LogKind;
  message: string;
  detail?: string;
}

function axiosDetail(err: unknown, fallback: string): string {
  if (isAxiosError(err) && err.response?.data?.detail) {
    return String(err.response.data.detail);
  }
  return fallback;
}

function fileFromJpegBase64(b64: string, name: string): File {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new File([bytes], name, { type: "image/jpeg" });
}

function downloadDataUrl(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}

function copyText(text: string, ok = "Đã copy vào clipboard") {
  void navigator.clipboard.writeText(text).then(
    () => message.success(ok),
    () => message.error("Trình duyệt không cho copy"),
  );
}

export default function ImageScanPage() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchId] = useState<string | undefined>();
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<string | undefined>();
  const [phase, setPhase] = useState(0);
  const [busy, setBusy] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [trace, setTrace] = useState<PipelineTraceResult | null>(null);
  const [stageUrls, setStageUrls] = useState<Record<number, string>>({});
  const [analyze, setAnalyze] = useState<AnalyzeResult | null>(null);
  const [debugSteps, setDebugSteps] = useState<DebugStep[]>([]);
  const [carts, setCarts] = useState<Cart[]>([]);
  const [qrByCart, setQrByCart] = useState<Record<string, CartCheckoutQrResponse>>({});
  const scanCartIdsRef = useRef<string[]>([]);
  const [logs, setLogs] = useState<ScanLog[]>([]);
  const [traceHint, setTraceHint] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [trainingJobs, setTrainingJobs] = useState<TrainingJob[]>([]);
  const [weightKey, setWeightKey] = useState("live");
  const [liveModelFile, setLiveModelFile] = useState("");
  const [exportingWord, setExportingWord] = useState(false);
  const [scanSourceLabel, setScanSourceLabel] = useState("");
  const stageUrlsRef = useRef<string[]>([]);
  const previewRef = useRef<string | null>(null);

  const addLog = useCallback((phaseName: string, kind: LogKind, messageText: string, detail?: string) => {
    setLogs((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random()}`,
        time: new Date().toLocaleTimeString("vi-VN"),
        phase: phaseName,
        kind,
        message: messageText,
        detail,
      },
    ]);
  }, []);

  const revokeStages = () => {
    stageUrlsRef.current.forEach((u) => URL.revokeObjectURL(u));
    stageUrlsRef.current = [];
    setStageUrls({});
  };

  useEffect(() => {
    return () => {
      revokeStages();
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    listTrainingJobs()
      .then((res) => {
        setTrainingJobs(res.items.filter((j) => j.status === "succeeded" && Boolean(j.weight_key)));
      })
      .catch(() => setTrainingJobs([]));
    listModels()
      .then((res) => setLiveModelFile(res.active || "yolov8n.pt"))
      .catch(() => setLiveModelFile("yolov8n.pt"));
  }, []);

  useEffect(() => {
    listBranches({ limit: 100 })
      .then((res) => {
        setBranches(res.items);
        if (res.items.length) setBranchId((id) => id ?? res.items[0]!.id);
      })
      .catch(() => message.error("Không tải được chi nhánh"));
  }, []);

  useEffect(() => {
    if (!branchId) {
      setCameras([]);
      setCameraId(undefined);
      return;
    }
    listCameras({ branch_id: branchId, is_active: true, limit: 100 })
      .then((res) => {
        setCameras(res.items);
        const preferred = res.items.find((c) => c.is_checkout_zone) ?? res.items[0];
        setCameraId(preferred?.id);
      })
      .catch(() => {
        setCameras([]);
        setCameraId(undefined);
      });
  }, [branchId]);

  const loadStageImages = async (camera: string, result: PipelineTraceResult) => {
    revokeStages();
    const next: Record<number, string> = {};
    const created: string[] = [];
    for (const stage of result.stages) {
      if (!stage.image_key) continue;
      try {
        const blob = await getTraceStageImageBlob(camera, result.trace_id, stage.image_key);
        const url = URL.createObjectURL(blob);
        created.push(url);
        next[stage.order] = url;
      } catch {
        /* missing stage image is non-fatal */
      }
    }
    stageUrlsRef.current = created;
    setStageUrls(next);
  };

  const loadScanCarts = useCallback(async () => {
    const ids = scanCartIdsRef.current;
    if (!ids.length) {
      setCarts([]);
      return;
    }
    const loaded = await Promise.all(
      ids.map(async (id) => {
        try {
          return await getCart(id);
        } catch {
          return null;
        }
      }),
    );
    setCarts(loaded.filter((c): c is Cart => Boolean(c)));
  }, []);

  useEffect(() => {
    scanCartIdsRef.current = [];
    setCarts([]);
    setQrByCart({});
  }, [branchId]);

  const onCheckout = async (cart: Cart) => {
    try {
      const res = await checkoutCart(cart.id);
      message.success(`Đã tạo đơn ${res.order_code}`);
      await loadScanCarts();
    } catch (err) {
      message.error(
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không thể checkout",
      );
    }
  };

  const onAbandon = async (cart: Cart) => {
    try {
      await abandonCart(cart.id);
      message.success("Đã hủy giỏ hàng");
      await loadScanCarts();
    } catch {
      message.error("Không thể hủy giỏ hàng");
    }
  };

  const onRemoveLine = async (cart: Cart, lineId: string) => {
    try {
      await removeCartLine(cart.id, lineId);
      await loadScanCarts();
    } catch {
      message.error("Không xóa được sản phẩm");
    }
  };

  const onShowQr = async (cart: Cart) => {
    try {
      const qr = await getCheckoutQr(cart.id);
      setQrByCart((prev) => ({ ...prev, [cart.id]: qr }));
    } catch {
      message.error("Không tải được mã QR");
    }
  };

  const onConfirmStaff = async (cart: Cart) => {
    try {
      const res = await confirmCheckoutStaff(cart.id);
      message.success(`Đã xác nhận — đơn ${res.order_code}`);
      setQrByCart((prev) => {
        const n = { ...prev };
        delete n[cart.id];
        return n;
      });
      await loadScanCarts();
    } catch (err) {
      message.error(
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không thể xác nhận",
      );
    }
  };

  const onCancelCheckout = async (cart: Cart) => {
    try {
      await cancelCheckout(cart.id);
      setQrByCart((prev) => {
        const n = { ...prev };
        delete n[cart.id];
        return n;
      });
      message.info("Đã huỷ chờ xác nhận");
      await loadScanCarts();
    } catch {
      message.error("Không thể huỷ");
    }
  };

  const runScan = async (file: File, source: "upload" | "live") => {
    if (!cameraId) {
      message.warning("Chọn camera (chi nhánh) trước");
      return;
    }
    setBusy(true);
    setFailed(false);
    setTrace(null);
    setAnalyze(null);
    setDebugSteps([]);
    setTraceHint(null);
    revokeStages();
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    const localUrl = URL.createObjectURL(file);
    previewRef.current = localUrl;
    setPreviewUrl(localUrl);
    setScanSourceLabel(source === "live" ? "Khung camera live (JPEG)" : `Ảnh tải lên: ${file.name}`);
    setLogs([]);
    setPhase(0);
    addLog(
      PHASES[0],
      "ok",
      source === "live" ? "Đã chụp khung camera" : `Đã nhận file ${file.name}`,
      `${(file.size / 1024).toFixed(0)} KB`,
    );

    try {
      setPhase(1);
      addLog(PHASES[1], "info", "Đang chạy chuỗi tiền xử lý OpenCV…");
      try {
        const traced = await tracePipeline(cameraId, file);
        setTrace(traced);
        addLog(
          PHASES[1],
          "ok",
          `${traced.stages.length} bước OpenCV · ${traced.opencv_ms.toFixed(0)} ms`,
          traced.quality
            ? `quality=${traced.quality.quality_score.toFixed(2)}${traced.quality.is_blurry ? " · mờ" : ""}`
            : undefined,
        );
        await loadStageImages(cameraId, traced);
      } catch (err) {
        const detail = axiosDetail(err, "Không lưu vết OpenCV");
        setTraceHint(detail);
        addLog(PHASES[1], "warn", "Bỏ qua ảnh từng bước OpenCV", detail);
      }

      setPhase(2);
      const detector = describeDetector(weightKey, trainingJobs, liveModelFile);
      addLog(PHASES[2], "info", "Đang nhận diện YOLO, crop và gán SKU…", detector.title);
      const analyzed = await analyzeCameraFrame(cameraId, file, {
        includeDebugSteps: true,
        weightKey: weightKey !== "live" ? weightKey : undefined,
      });
      setAnalyze(analyzed);
      const steps = analyzed.frame_pipeline?.debug_steps ?? [];
      setDebugSteps(steps);
      if (analyzed.frame_pipeline_error) {
        addLog(PHASES[2], "err", "Pipeline giỏ lỗi", analyzed.frame_pipeline_error);
      }
      const dets = analyzed.detections ?? [];
      const skus = dets
        .filter((d) => d.sku)
        .map((d) => `${d.name || d.sku} (${Math.round(d.confidence * 100)}%)`)
        .join(", ");
      addLog(
        PHASES[2],
        dets.length ? "ok" : "warn",
        skus ? `SKU: ${skus}` : `${dets.length} box, chưa map SKU`,
        `model=${fileName(analyzed.model)} · ${detector.title} · ${analyzed.elapsed_ms} ms · ${steps.length} ảnh giai đoạn AI`,
      );
      for (const step of steps) {
        addLog(
          PHASES[2],
          "ok",
          `${step.label} (${step.step})`,
          step.elapsed_ms != null ? `${step.elapsed_ms} ms` : undefined,
        );
      }

      setPhase(3);
      addLog(PHASES[3], "info", "Đang tải giỏ hàng vừa tạo…");
      const cartIds = [
        ...new Set(
          (analyzed.frame_pipeline?.emitted_events ?? [])
            .map((e) => e.backend?.body?.cart_id)
            .filter((id): id is string => Boolean(id)),
        ),
      ];
      if (cartIds.length) {
        scanCartIdsRef.current = [...new Set([...scanCartIdsRef.current, ...cartIds])];
      }
      await loadScanCarts();
      const n = scanCartIdsRef.current.length;
      if (cartIds.length) {
        addLog(PHASES[3], "ok", `${cartIds.length} giỏ mới · tổng ${n} giỏ từ hình ảnh trên trang này`);
      } else if (n) {
        addLog(PHASES[3], "warn", `Ảnh này không tạo giỏ mới · vẫn còn ${n} giỏ trên trang`);
      } else {
        addLog(PHASES[3], "warn", "Không có giỏ — SKU chưa khớp catalog hoặc pipeline lỗi");
      }

      setPhase(4);
      message.success("Quét xong — cuộn xuống để tải ảnh từng giai đoạn cho luận văn");
    } catch (err) {
      setFailed(true);
      addLog(PHASES[phase] || "Lỗi", "err", axiosDetail(err, "Quét thất bại"));
      message.error(axiosDetail(err, "Quét thất bại"));
    } finally {
      setBusy(false);
    }
  };

  const onLiveCapture = async () => {
    if (!cameraId) {
      message.warning("Chọn camera có luồng live");
      return;
    }
    setBusy(true);
    try {
      const preview = await previewCameraStream(cameraId);
      if (!preview.frame_base64) {
        message.error("Camera không trả về JPEG");
        return;
      }
      const file = fileFromJpegBase64(preview.frame_base64, `live-${Date.now()}.jpg`);
      await runScan(file, "live");
    } catch (err) {
      setFailed(true);
      message.error(axiosDetail(err, "Không chụp được khung live"));
    } finally {
      setBusy(false);
    }
  };

  const downloadStage = (stage: TraceStage) => {
    const url = stageUrls[stage.order];
    if (!url) return;
    downloadDataUrl(url, `${String(stage.order).padStart(2, "0")}_${stage.stage}.jpg`);
  };

  const downloadDebug = (step: DebugStep, index: number) => {
    downloadDataUrl(
      `data:image/jpeg;base64,${step.image_jpeg_b64}`,
      `${String(index + 1).padStart(2, "0")}_${step.step}.jpg`,
    );
  };

  const percent = busy ? Math.min(95, 12 + phase * 22) : phase >= 4 ? 100 : failed ? 100 : 0;
  const camera = useMemo(() => cameras.find((c) => c.id === cameraId), [cameras, cameraId]);
  const stepStatus = busy ? "process" : failed ? "error" : phase >= 4 ? "finish" : "wait";
  const detectorDesc = useMemo(
    () => describeDetector(weightKey, trainingJobs, liveModelFile),
    [weightKey, trainingJobs, liveModelFile],
  );
  const modelSelectOptions = useMemo(() => {
    const bbox = trainingJobs.filter((j) => trainingJobKind(j) === "bbox");
    const crop = trainingJobs.filter((j) => trainingJobKind(j) === "crop");
    const toOpts = (jobs: TrainingJob[]) =>
      jobs.map((j) => ({
        label: jobSelectLabel(j),
        value: j.weight_key as string,
      }));
    return [
      { label: "Model đang triển khai (live)", value: "live" },
      ...(bbox.length ? [{ label: "Train từ nhãn bbox (Gán nhãn bbox)", options: toOpts(bbox) }] : []),
      ...(crop.length ? [{ label: "Train AI (crop 1 SKU)", options: toOpts(crop) }] : []),
    ];
  }, [trainingJobs]);

  const appendixSections = useMemo(() => {
    const fromTrace = (trace?.stages ?? []).map((s) => ({
      stage: s.stage,
      title: s.label,
      params: s.params,
      elapsedMs: s.elapsed_ms,
    }));
    const fromDebug = debugSteps.map((s) => ({
      stage: s.step,
      title: s.label,
      params: s.params,
      elapsedMs: s.elapsed_ms,
    }));
    const seen = new Set<string>();
    const merged = [...fromTrace, ...fromDebug].filter((s) => {
      if (!lookupAlgorithm(s.stage) || seen.has(s.stage)) return false;
      seen.add(s.stage);
      return true;
    });
    const fallback = ["original", "preprocess", "detection", "crop", "classifier", "result"];
    for (const key of fallback) {
      if (!seen.has(key) && lookupAlgorithm(key)) {
        merged.push({ stage: key, title: lookupAlgorithm(key)!.algorithm, params: undefined, elapsedMs: null });
        seen.add(key);
      }
    }
    return merged;
  }, [trace, debugSteps]);

  const appendixMarkdown = useMemo(
    () => formatAppendixMarkdown(appendixSections),
    [appendixSections],
  );

  const totalRevenue = useMemo(
    () => carts.reduce((sum, c) => sum + Number(c.total_amount || 0), 0),
    [carts],
  );
  const totalLines = useMemo(
    () => carts.reduce((sum, c) => sum + (c.lines?.length ?? 0), 0),
    [carts],
  );

  const exportThesisWord = async () => {
    if (!analyze && !trace) {
      message.warning("Quét một ảnh trước khi xuất Word");
      return;
    }
    setExportingWord(true);
    try {
      const [preview, opencvStages, aiStages] = await Promise.all([
        loadThesisImageFromUrl(previewUrl),
        Promise.all(
          (trace?.stages ?? []).map(async (s) => ({
            key: s.stage,
            title: s.label,
            elapsedMs: s.elapsed_ms,
            params: s.params,
            metrics: s.metrics,
            image: await loadThesisImageFromUrl(stageUrls[s.order]),
          })),
        ),
        Promise.all(
          debugSteps.map(async (s) => ({
            key: s.step,
            title: s.label,
            elapsedMs: s.elapsed_ms,
            params: s.params,
            image: await loadThesisImageFromBase64(s.image_jpeg_b64),
          })),
        ),
      ]);
      const branchName = branches.find((b) => b.id === branchId)?.name;
      const cameraName = cameras.find((c) => c.id === cameraId)?.name;
      const filename = await downloadThesisWord({
        kind: "image",
        context: {
          branchName,
          cameraName,
          detectorTitle: detectorDesc.title,
          detectorDetail: detectorDesc.detail,
          modelFile: analyze?.model ? fileName(analyze.model) : liveModelFile,
          elapsedMs: analyze?.elapsed_ms,
          sourceLabel: scanSourceLabel || "Ảnh tĩnh",
          opencvMs: trace?.opencv_ms,
          quality: trace?.quality
            ? {
                quality_score: trace.quality.quality_score,
                brightness: trace.quality.brightness,
                contrast: trace.quality.contrast,
                blur_score: trace.quality.blur_score,
                is_blurry: trace.quality.is_blurry,
                is_low_quality: trace.quality.is_low_quality,
                reason: trace.quality.reason,
              }
            : undefined,
        },
        notes: logs.map((l) => ({
          time: l.time,
          phase: l.phase,
          kind: l.kind,
          message: l.message,
          detail: l.detail,
        })),
        detections: (analyze?.detections ?? []).map((d) => ({
          label: d.name || d.class_name,
          sku: d.sku,
          confidence: d.confidence,
        })),
        preview,
        opencvStages,
        aiStages,
        carts: carts.map((c) => ({
          id: c.id,
          status: c.status,
          sessionId: c.session_id,
          total: c.total_amount,
          currency: c.currency,
          lines: (c.lines || []).map((line) => ({
            sku: line.sku,
            name: line.product_name,
            qty: line.quantity,
            subtotal: line.subtotal,
            confidence: line.confidence,
            lineId: line.line_id,
            hasPhoto: Boolean(line.has_photo),
          })),
        })),
      });
      message.success(`Đã tải ${filename}`);
    } catch (err) {
      message.error(axiosDetail(err, "Không xuất được file Word"));
    } finally {
      setExportingWord(false);
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }} className="image-scan-lab">
      <style>{`
        ${THESIS_CODE_CSS}
        .image-scan-qr svg { width: 100%; height: 100%; display: block; }
        @media print {
          .no-print, .ant-layout-sider, .ant-layout-header, .ant-layout-footer { display: none !important; }
          .ant-layout, .ant-layout-content { margin: 0 !important; padding: 0 !important; }
          .image-scan-lab { color: #000; }
        }
      `}</style>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          Tải ảnh &amp; Quét — nhật ký giai đoạn (luận văn)
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Tải một ảnh quầy (hoặc chụp live). Chọn <strong>Train AI</strong> (crop 1 SKU) hoặc{" "}
          <strong>Train từ nhãn bbox</strong> để so sánh; mặc định là model đang triển khai (live).
          Hệ thống ghi từng bước OpenCV rồi YOLO / crop / SKU kèm ảnh, công thức, thuộc tính và mã nguồn.
          Giỏ tạo từ ảnh nằm riêng phía dưới — không lẫn giỏ live của quầy.
          Sau khi quét xong, <strong>Xuất Word (A4, luận văn)</strong> tạo file .docx Times New Roman 13pt:
          mô tả thí nghiệm, nhật ký, ảnh trung gian, công thức và giỏ hàng — bố cục báo cáo, không phải ảnh chụp giao diện.
        </Paragraph>
      </div>

      <Card className="no-print">
        <Space wrap>
          <Select
            style={{ minWidth: 220 }}
            placeholder="Chi nhánh"
            value={branchId}
            onChange={setBranchId}
            options={branches.map((b) => ({ label: b.name, value: b.id }))}
          />
          <Select
            style={{ minWidth: 260 }}
            placeholder="Camera quầy"
            value={cameraId}
            onChange={setCameraId}
            options={cameras.map((c) => ({
              label: `${c.name}${c.is_checkout_zone ? " (quầy)" : ""}`,
              value: c.id,
            }))}
          />
          <Select
            style={{ minWidth: 320 }}
            placeholder="Model YOLO"
            value={weightKey}
            onChange={setWeightKey}
            disabled={busy}
            options={modelSelectOptions}
            showSearch
            optionFilterProp="label"
          />
          <Tag color={detectorDesc.color}>{detectorDesc.title}</Tag>
          <Upload
            accept="image/jpeg,image/png,image/webp,image/bmp"
            showUploadList={false}
            beforeUpload={(file) => {
              if (file.size > 10 * 1024 * 1024) {
                message.error("Ảnh vượt quá 10 MB");
                return Upload.LIST_IGNORE;
              }
              void runScan(file as File, "upload");
              return Upload.LIST_IGNORE;
            }}
          >
            <Button type="primary" icon={<CloudUploadOutlined />} loading={busy} disabled={!cameraId}>
              Tải ảnh &amp; quét
            </Button>
          </Upload>
          <Button icon={<CameraOutlined />} loading={busy} disabled={!cameraId} onClick={() => void onLiveCapture()}>
            Chụp khung live rồi quét
          </Button>
          <Button icon={<PrinterOutlined />} onClick={() => window.print()} disabled={!trace && !analyze}>
            In / lưu PDF
          </Button>
          <Button
            type="primary"
            ghost
            icon={<FileWordOutlined />}
            loading={exportingWord}
            disabled={(!trace && !analyze) || busy}
            onClick={() => void exportThesisWord()}
          >
            Xuất Word (A4, luận văn)
          </Button>
          <Button
            icon={<CopyOutlined />}
            disabled={appendixSections.length === 0}
            onClick={() => copyText(appendixMarkdown, "Đã copy phụ lục thuật toán (Markdown)")}
          >
            Sao chép phụ lục thuật toán
          </Button>
        </Space>
        <Alert
          style={{ marginTop: 12 }}
          type="info"
          showIcon
          message={detectorDesc.title}
          description={
            <>
              {detectorDesc.detail}
              {weightKey === "live"
                ? " — quét dùng đúng weight đang chạy trên camera live (sau khi Deploy tại Train AI / Gán nhãn bbox)."
                : " — chỉ lần quét này; camera live không đổi."}
            </>
          }
        />
      </Card>

      <Card size="small">
        <Steps size="small" current={phase} status={stepStatus} items={PHASES.map((title) => ({ title }))} />
        <Progress
          percent={percent}
          status={busy ? "active" : failed ? "exception" : phase >= 4 ? "success" : "normal"}
          style={{ marginTop: 12 }}
        />
      </Card>

      {traceHint && (
        <Alert
          className="no-print"
          type="warning"
          showIcon
          message="Chưa có ảnh từng bước OpenCV"
          description={
            <>
              {traceHint} Bật tại <Text strong>Cấu hình xử lý ảnh → Bật lưu vết</Text> rồi quét lại.
              Ảnh YOLO / crop / SKU bên dưới vẫn có nếu nhận diện chạy được.
            </>
          }
        />
      )}

      <Row gutter={16}>
        <Col xs={24} lg={10}>
          <Card title="Ảnh đầu vào" size="small">
            {previewUrl ? (
              <Image src={previewUrl} alt="Ảnh quét" style={{ maxHeight: 320, objectFit: "contain" }} />
            ) : (
              <Empty description="Chưa tải ảnh" />
            )}
            {camera && (
              <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
                Camera: {camera.name}
                {analyze ? ` · ${analyze.elapsed_ms} ms · ${fileName(analyze.model)}` : ""}
              </Text>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card title="Nhật ký giai đoạn" size="small" styles={{ body: { maxHeight: 360, overflow: "auto" } }}>
            {logs.length === 0 ? (
              <Empty description="Nhật ký hiện khi bắt đầu quét" />
            ) : (
              <Timeline
                items={logs.map((l) => ({
                  color: l.kind === "err" ? "red" : l.kind === "warn" ? "orange" : l.kind === "ok" ? "green" : "blue",
                  children: (
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {l.time} · {l.phase}
                      </Text>
                      <div>
                        <Text>{l.message}</Text>
                      </div>
                      {l.detail && (
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {l.detail}
                        </Text>
                      )}
                    </div>
                  ),
                }))}
              />
            )}
          </Card>
        </Col>
      </Row>

      {debugSteps.length > 0 && (
        <Card title={`Ảnh từng giai đoạn AI (${debugSteps.length} bước)`}>
          <Paragraph type="secondary" style={{ marginTop: 0 }}>
            Chuỗi DEBUG: ảnh gốc → OpenCV → YOLO → crop → phân loại SKU. Mở mục công thức để chép diễn giải ký hiệu vào luận văn.
          </Paragraph>
          <Row gutter={[12, 12]}>
            {debugSteps.map((s, i) => (
              <Col xs={24} sm={12} lg={8} key={`${s.step}-${i}`}>
                <Card
                  className="print-break"
                  size="small"
                  title={`${i + 1}. ${s.label}`}
                  extra={
                    <Button
                      className="no-print"
                      size="small"
                      type="link"
                      icon={<DownloadOutlined />}
                      onClick={() => downloadDebug(s, i)}
                    />
                  }
                >
                  <Image
                    src={`data:image/jpeg;base64,${s.image_jpeg_b64}`}
                    alt={s.label}
                    style={{ width: "100%", maxHeight: 200, objectFit: "contain" }}
                  />
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {s.step}
                    {s.elapsed_ms != null ? ` · ${s.elapsed_ms} ms` : ""}
                  </Text>
                  <AlgorithmSnippet
                    stage={s.step}
                    title={s.label}
                    params={s.params}
                    elapsedMs={s.elapsed_ms}
                  />
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {trace && trace.stages.length > 0 && (
        <Card
          title={`Chi tiết tiền xử lý OpenCV (${trace.stages.length} bước · ${trace.opencv_ms.toFixed(0)} ms)`}
          extra={
            trace.quality ? (
              <Tag color={trace.quality.is_low_quality ? "red" : "green"}>
                quality {trace.quality.quality_score.toFixed(2)}
              </Tag>
            ) : null
          }
        >
          <Row gutter={[12, 12]}>
            {trace.stages.map((s) => (
              <Col xs={24} sm={12} lg={8} key={s.order}>
                <Card
                  className="print-break"
                  size="small"
                  title={`${s.order + 1}. ${s.label}`}
                  extra={
                    stageUrls[s.order] ? (
                      <Button
                        className="no-print"
                        size="small"
                        type="link"
                        icon={<DownloadOutlined />}
                        onClick={() => downloadStage(s)}
                      />
                    ) : null
                  }
                >
                  {stageUrls[s.order] ? (
                    <Image src={stageUrls[s.order]} alt={s.label} style={{ width: "100%", maxHeight: 180, objectFit: "contain" }} />
                  ) : (
                    <Empty description="Không có JPEG" />
                  )}
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {s.stage} · {s.elapsed_ms.toFixed(1)} ms ·{" "}
                    <Tooltip title={PARAM_GLOSSARY.brightness}>sáng {s.metrics.brightness.toFixed(0)}</Tooltip>
                    {" · "}
                    <Tooltip title={PARAM_GLOSSARY.contrast}>tương phản {s.metrics.contrast.toFixed(0)}</Tooltip>
                    {" · "}
                    <Tooltip title={PARAM_GLOSSARY.blur_score}>nét {s.metrics.blur_score.toFixed(0)}</Tooltip>
                  </Text>
                  <AlgorithmSnippet
                    stage={s.stage}
                    title={s.label}
                    params={s.params}
                    elapsedMs={s.elapsed_ms}
                  />
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {analyze && (
        <Card title="Kết quả nhận diện / giỏ" className="print-break">
          <Space wrap style={{ marginBottom: 12 }}>
            <Tag color={detectorDesc.color}>{detectorDesc.title}</Tag>
            <Text type="secondary">{detectorDesc.detail}</Text>
            {analyze.model && <Text code>{fileName(analyze.model)}</Text>}
          </Space>
          <Row gutter={16} style={{ marginBottom: 12 }}>
            <Col span={8}>
              <Statistic title="Box" value={(analyze.detections ?? []).length} />
            </Col>
            <Col span={8}>
              <Statistic title="Có SKU" value={(analyze.detections ?? []).filter((d) => d.sku).length} />
            </Col>
            <Col span={8}>
              <Statistic title="Thời gian AI" value={analyze.elapsed_ms} suffix="ms" />
            </Col>
          </Row>
          <Space wrap>
            {(analyze.detections ?? []).map((d, i) => (
              <Tag key={i} color={d.sku ? "blue" : "default"}>
                {d.name || d.sku || d.class_name} {Math.round(d.confidence * 100)}%
              </Tag>
            ))}
          </Space>
        </Card>
      )}

      <Row gutter={16}>
        <Col span={8}>
          <Card>
            <Statistic title="Giỏ hàng từ hình ảnh" value={carts.length} prefix={<ShoppingCartOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Tổng giá trị chờ thanh toán"
              value={totalRevenue}
              formatter={(v) =>
                new Intl.NumberFormat("vi-VN", {
                  style: "currency",
                  currency: "VND",
                  maximumFractionDigits: 0,
                }).format(Number(v))
              }
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="Tổng sản phẩm trong giỏ" value={totalLines} prefix={<CheckCircleOutlined />} />
          </Card>
        </Col>
      </Row>

      <Card
        className="print-break"
        title={
          <Space>
            <ShoppingCartOutlined />
            <Typography.Text strong>Giỏ hàng được tạo từ hình ảnh</Typography.Text>
          </Space>
        }
        extra={
          <Button
            className="no-print"
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => void loadScanCarts()}
            disabled={busy}
          >
            Làm mới
          </Button>
        }
      >
        {carts.length === 0 ? (
          <Empty description="Chưa có giỏ từ ảnh đã quét trên trang này. Tải ảnh (SKU khớp catalog) rồi quét." />
        ) : (
          <List
            dataSource={carts}
            renderItem={(cart) => (
              <List.Item key={cart.id}>
                <Card
                  size="small"
                  style={{ width: "100%", borderRadius: 8 }}
                  title={
                    <Space>
                      <Tag
                        color={
                          cart.status === "active"
                            ? "green"
                            : cart.status === "pending_checkout"
                              ? "orange"
                              : "default"
                        }
                      >
                        {cart.status === "active"
                          ? "ACTIVE"
                          : cart.status === "pending_checkout"
                            ? "CHỜ XÁC NHẬN"
                            : cart.status}
                      </Tag>
                      <Typography.Text style={{ fontSize: 12, color: "#888" }}>
                        {cart.id.slice(0, 8)}
                      </Typography.Text>
                      <Tag color="purple">{cart.session_id ?? "ảnh"}</Tag>
                    </Space>
                  }
                  extra={
                    <Space size="small" className="no-print">
                      {cart.status === "active" && (
                        <>
                          <Tooltip title="Thanh toán ngay">
                            <Button
                              size="small"
                              type="primary"
                              icon={<CheckCircleOutlined />}
                              onClick={() => void onCheckout(cart)}
                            >
                              Checkout
                            </Button>
                          </Tooltip>
                          <Tooltip title="Xem QR xác nhận">
                            <Button size="small" icon={<QrcodeOutlined />} onClick={() => void onShowQr(cart)} />
                          </Tooltip>
                          <Popconfirm
                            title="Hủy giỏ hàng?"
                            onConfirm={() => void onAbandon(cart)}
                            okText="Hủy"
                            cancelText="Không"
                          >
                            <Button size="small" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        </>
                      )}
                      {cart.status === "pending_checkout" && (
                        <>
                          <Button
                            size="small"
                            type="primary"
                            icon={<CheckCircleOutlined />}
                            onClick={() => void onConfirmStaff(cart)}
                          >
                            Xác nhận hộ
                          </Button>
                          <Button size="small" onClick={() => void onCancelCheckout(cart)}>
                            Huỷ chờ
                          </Button>
                        </>
                      )}
                    </Space>
                  }
                >
                  {qrByCart[cart.id] && (
                    <div style={{ textAlign: "center", marginBottom: 8 }}>
                      <div
                        className="image-scan-qr"
                        style={{ width: 100, height: 100, margin: "0 auto" }}
                        // eslint-disable-next-line react/no-danger
                        dangerouslySetInnerHTML={{ __html: qrByCart[cart.id].qr_svg }}
                      />
                      <Typography.Text copyable style={{ fontSize: 11 }}>
                        {qrByCart[cart.id].confirm_url}
                      </Typography.Text>
                    </div>
                  )}
                  {(cart.lines || []).length === 0 ? (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      Giỏ trống
                    </Typography.Text>
                  ) : (
                    <List
                      size="small"
                      dataSource={cart.lines}
                      renderItem={(line: CartLine) => (
                        <List.Item
                          key={line.line_id}
                          extra={
                            <Space>
                              <Typography.Text strong style={{ fontSize: 12 }}>
                                {formatMoney(line.subtotal, cart.currency)}
                              </Typography.Text>
                              {cart.status === "active" && (
                                <>
                                  <CartLineSkuButton cart={cart} line={line} onDone={() => void loadScanCarts()} />
                                  <Tooltip title="Xóa dòng">
                                    <Button
                                      size="small"
                                      danger
                                      icon={<DeleteOutlined />}
                                      onClick={() => void onRemoveLine(cart, line.line_id)}
                                    />
                                  </Tooltip>
                                </>
                              )}
                            </Space>
                          }
                        >
                          <List.Item.Meta
                            avatar={
                              line.has_photo ? (
                                <CartLinePhoto
                                  cartId={cart.id}
                                  lineId={line.line_id}
                                  size={56}
                                  alt={line.product_name || line.sku}
                                />
                              ) : undefined
                            }
                            title={
                              <Space size="small" wrap>
                                <Typography.Text strong style={{ fontSize: 13 }}>
                                  {line.product_name}
                                </Typography.Text>
                                <Tag color="blue" style={{ fontWeight: 600 }}>
                                  {line.sku}
                                </Tag>
                                <Tag>x{line.quantity}</Tag>
                                {line.added_via === "staff_correction" && <Tag color="green">Admin sửa</Tag>}
                                {line.added_via === "ai" && line.confidence != null && line.confidence < 0.7 && (
                                  <Tooltip title={`Độ tin cậy AI: ${(line.confidence * 100).toFixed(0)}%`}>
                                    <Tag color="orange" icon={<WarningOutlined />}>
                                      {(line.confidence * 100).toFixed(0)}%
                                    </Tag>
                                  </Tooltip>
                                )}
                              </Space>
                            }
                          />
                        </List.Item>
                      )}
                    />
                  )}
                  <Divider style={{ margin: "8px 0" }} />
                  <Row justify="space-between">
                    <Col>
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        {cart.lines?.length ?? 0} sản phẩm
                      </Typography.Text>
                    </Col>
                    <Col>
                      <Typography.Text strong>
                        Tổng: {formatMoney(cart.total_amount, cart.currency)}
                      </Typography.Text>
                    </Col>
                  </Row>
                </Card>
              </List.Item>
            )}
          />
        )}
      </Card>

      <ThesisAppendix
        sections={appendixSections}
        intro="Mỗi mục: mục đích trong pipeline siêu thị, công thức (ký hiệu dùng để làm gì), tham số lần quét, rồi mã nguồn. Dán Markdown vào Word hoặc In / lưu PDF."
      />
    </Space>
  );
}
