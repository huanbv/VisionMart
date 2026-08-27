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
  Collapse,
  Empty,
  Image,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Steps,
  Tag,
  Timeline,
  Typography,
  Upload,
  message,
} from "antd";
import {
  CameraOutlined,
  CloudUploadOutlined,
  CopyOutlined,
  DownloadOutlined,
  PrinterOutlined,
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
import { getCart, listCarts, type Cart } from "@/api/carts";
import CartLinePhoto from "@/components/CartLinePhoto";
import {
  formatAlgorithmMarkdown,
  formatAppendixMarkdown,
  lookupAlgorithm,
} from "@/pages/imageScanAlgorithms";

const { Title, Paragraph, Text } = Typography;

const PHASES = [
  "Nhận ảnh",
  "Tiền xử lý OpenCV",
  "Nhận diện YOLO + SKU",
  "Tạo giỏ hàng",
  "Hoàn tất",
] as const;

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

function AlgorithmSnippet({
  stage,
  title,
  params,
  elapsedMs,
}: {
  stage: string;
  title?: string;
  params?: Record<string, unknown>;
  elapsedMs?: number | null;
}) {
  const def = lookupAlgorithm(stage);
  if (!def) return null;
  const md = formatAlgorithmMarkdown(stage, { title: title ?? def.algorithm, params, elapsedMs });
  return (
    <div style={{ marginTop: 8 }}>
      <Tag color="geekblue" style={{ whiteSpace: "normal", height: "auto" }}>
        {def.algorithm}
      </Tag>
      <div>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {def.algorithmEn}
        </Text>
      </div>
      <Collapse
        size="small"
        style={{ marginTop: 6 }}
        items={[
          {
            key: "code",
            label: "Mã nguồn + tài liệu",
            children: (
              <div>
                <Paragraph style={{ marginBottom: 6, fontSize: 12 }}>
                  {def.citation}
                  <br />
                  <Text code>{def.file}</Text>
                </Paragraph>
                <pre className="algo-code">{def.code}</pre>
                <Button
                  className="no-print"
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => copyText(md, "Đã copy mục này (Markdown)")}
                >
                  Sao chép mục này
                </Button>
              </div>
            ),
          },
        ]}
      />
    </div>
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
  const [logs, setLogs] = useState<ScanLog[]>([]);
  const [traceHint, setTraceHint] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
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
    setCarts([]);
    setTraceHint(null);
    revokeStages();
    if (previewRef.current) URL.revokeObjectURL(previewRef.current);
    const localUrl = URL.createObjectURL(file);
    previewRef.current = localUrl;
    setPreviewUrl(localUrl);
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
      addLog(PHASES[2], "info", "Đang nhận diện YOLO, crop và gán SKU…");
      const analyzed = await analyzeCameraFrame(cameraId, file, { includeDebugSteps: true });
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
        `model=${analyzed.model} · ${analyzed.elapsed_ms} ms · ${steps.length} ảnh giai đoạn AI`,
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
      if (cartIds[0]) {
        try {
          const cart = await getCart(cartIds[0]);
          setCarts([cart]);
          addLog(PHASES[3], "ok", `Giỏ ${cart.id.slice(0, 8)} · ${cart.lines.length} dòng`);
        } catch {
          addLog(PHASES[3], "warn", "Có cart_id nhưng không tải được giỏ");
        }
      } else if (branchId) {
        const [active, pending] = await Promise.all([
          listCarts({ branch_id: branchId, status: "active", limit: 8 }),
          listCarts({ branch_id: branchId, status: "pending_checkout", limit: 8 }),
        ]);
        setCarts([...pending.items, ...active.items].slice(0, 4));
        addLog(PHASES[3], "ok", "Đã ghi giỏ (nếu SKU khớp catalog)");
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

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }} className="image-scan-lab">
      <style>{`
        pre.algo-code {
          background: #f6f8fa;
          border: 1px solid #eaeaea;
          border-radius: 6px;
          padding: 8px 10px;
          font-size: 11px;
          line-height: 1.45;
          white-space: pre-wrap;
          word-break: break-word;
        }
        @media print {
          .no-print, .ant-layout-sider, .ant-layout-header, .ant-layout-footer { display: none !important; }
          .ant-layout, .ant-layout-content { margin: 0 !important; padding: 0 !important; }
          .image-scan-lab { color: #000; }
          .print-break { break-inside: avoid; page-break-inside: avoid; }
          .ant-collapse-content { display: block !important; height: auto !important; }
        }
      `}</style>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>
          Tải ảnh &amp; Quét — nhật ký giai đoạn (luận văn)
        </Title>
        <Paragraph type="secondary" style={{ marginBottom: 0 }}>
          Tải một ảnh quầy (hoặc chụp live). Hệ thống ghi từng bước OpenCV rồi YOLO / crop / SKU
          kèm ảnh, <strong>tên thuật toán và mã nguồn</strong>. Sao chép từng mục hoặc cả phụ lục Markdown để dán Word.
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
            icon={<CopyOutlined />}
            disabled={appendixSections.length === 0}
            onClick={() => copyText(appendixMarkdown, "Đã copy phụ lục thuật toán (Markdown)")}
          >
            Sao chép phụ lục thuật toán
          </Button>
        </Space>
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
                {analyze ? ` · ${analyze.elapsed_ms} ms · ${analyze.model}` : ""}
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
            Chuỗi DEBUG: ảnh gốc → OpenCV → YOLO → crop → phân loại SKU → khung kết quả. Tải từng JPEG để chèn luận văn.
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
                    {s.stage} · {s.elapsed_ms.toFixed(1)} ms · sáng {s.metrics.brightness.toFixed(0)} · nét{" "}
                    {s.metrics.blur_score.toFixed(0)}
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
          {carts[0] && (
            <div style={{ marginTop: 16 }}>
              <Text strong>
                Giỏ {carts[0].id.slice(0, 8)} · {carts[0].status}
              </Text>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8 }}>
                {carts[0].lines.map((line) => (
                  <Space key={line.line_id} direction="vertical" size={4} align="center">
                    {line.has_photo ? (
                      <CartLinePhoto cartId={carts[0]!.id} lineId={line.line_id} size={72} alt={line.product_name} />
                    ) : null}
                    <Text style={{ fontSize: 12 }}>
                      {line.product_name} ({line.sku})
                    </Text>
                  </Space>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}

      {appendixSections.length > 0 && (
        <Card
          title="Phụ lục thuật toán & mã nguồn (copy vào luận văn)"
          extra={
            <Button
              className="no-print"
              size="small"
              icon={<CopyOutlined />}
              onClick={() => copyText(appendixMarkdown, "Đã copy phụ lục thuật toán (Markdown)")}
            >
              Sao chép toàn bộ
            </Button>
          }
        >
          <Paragraph type="secondary">
            Dán vào Word: giữ định dạng Markdown hoặc In / lưu PDF. Tên thuật toán kèm tài liệu gốc (Gonzalez &amp; Woods,
            YOLOv8, ByteTrack, MobileNetV3, CLAHE, …).
          </Paragraph>
          {appendixSections.map((s, i) => {
            const def = lookupAlgorithm(s.stage);
            if (!def) return null;
            return (
              <div key={`${s.stage}-${i}`} className="print-break" style={{ marginBottom: 20 }}>
                <Title level={5} style={{ marginBottom: 4 }}>
                  {i + 1}. {s.title}
                </Title>
                <Space wrap size={[4, 4]}>
                  <Tag color="geekblue">{def.algorithm}</Tag>
                  <Tag>{def.algorithmEn}</Tag>
                </Space>
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {def.citation}
                  </Text>
                </div>
                <Text code>{def.file}</Text>
                {s.elapsedMs != null && (
                  <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                    {s.elapsedMs} ms
                  </Text>
                )}
                <pre className="algo-code">{def.code}</pre>
                <Button
                  className="no-print"
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() =>
                    copyText(
                      formatAlgorithmMarkdown(s.stage, {
                        title: `${i + 1}. ${s.title}`,
                        params: s.params,
                        elapsedMs: s.elapsedMs,
                      }),
                      "Đã copy mục này",
                    )
                  }
                >
                  Sao chép mục này
                </Button>
              </div>
            );
          })}
        </Card>
      )}
    </Space>
  );
}
