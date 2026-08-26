import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  Row,
  Select,
  Space,
  Statistic,
  Steps,
  Switch,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CameraOutlined,
  CheckCircleOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EyeOutlined,
  QrcodeOutlined,
  ReloadOutlined,
  ScanOutlined,
  ShoppingCartOutlined,
  StopOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { isAxiosError } from "axios";

import {
  abandonCart,
  bulkAbandonCarts,
  cancelCheckout,
  checkoutCart,
  confirmCheckoutStaff,
  getCartCustomerPhotoUrl,
  getCheckoutQr,
  listCarts,
  removeCartLine,
  type Cart,
  type CartCheckoutQrResponse,
  type CartStatus,
} from "@/api/carts";
import { type Branch, listBranches } from "@/api/tenancy";
import { type Camera, analyzeCameraFrame, getAiAutoScan, listCameras, setAiAutoScan, triggerCameraScan } from "@/api/cameras";
import { tokenStore } from "@/api/client";
import LiveCameraView, { type LiveStreamStatus } from "@/components/LiveCameraView";

const REFRESH_MS = 5_000;

const STATUS_COLOR: Record<CartStatus, string> = {
  active: "green",
  abandoned: "default",
  converted: "blue",
  pending_checkout: "orange",
};

const STATUS_LABEL: Record<CartStatus, string> = {
  active: "ACTIVE",
  abandoned: "ABANDONED",
  converted: "CONVERTED",
  pending_checkout: "CHỜ KHÁCH XÁC NHẬN",
};

const SOURCE_LABEL: Record<string, string> = {
  ai_vision: "AI Camera",
  manual: "Thủ công",
  mobile_app: "Mobile",
};

type ScanDetection = { sku?: string | null; class_name?: string };
type ScanEvent = {
  event?: { product_sku?: string | null };
  backend?: {
    status?: number;
    body?: { accepted?: boolean; reason?: string | null };
  };
};

function reportScanOutcome(
  detections: ScanDetection[],
  events: ScanEvent[],
  addLog: (type: AiLogItem["type"], messageText: string, detail?: string) => void,
  sourceLabel: string,
) {
  const withSku = detections.filter((d) => d.sku);
  const newlyAdded = events.filter(
    (e) => e.backend?.body?.accepted && !e.backend?.body?.reason,
  );
  const accepted = events.filter((e) => e.backend?.body?.accepted);
  const reasons = [
    ...new Set(
      events
        .map((e) => e.backend?.body?.reason)
        .filter((r): r is string => Boolean(r)),
    ),
  ];
  const addedSkus = [
    ...new Set(
      newlyAdded
        .map((e) => e.event?.product_sku)
        .filter((s): s is string => Boolean(s)),
    ),
  ];
  const skuList = addedSkus.join(", ") || [...new Set(withSku.map((d) => d.sku))].join(", ");

  if (newlyAdded.length > 0) {
    const n = addedSkus.length || newlyAdded.length;
    message.success(`Đã thêm ${n} sản phẩm vào giỏ AI${skuList ? ` (${skuList})` : ""}`);
    addLog("add", `${sourceLabel} — đã tạo/cập nhật giỏ`, skuList || `${n} SKU`);
  } else if (accepted.length > 0) {
    message.info(`Sản phẩm đã có trong giỏ AI${skuList ? ` (${skuList})` : ""}`);
    addLog("info", `${sourceLabel} — SKU đã có trong giỏ`, skuList);
  } else if (events.length > 0) {
    const why = reasons.join(", ") || `HTTP ${events[0]?.backend?.status ?? "?"}`;
    const hint =
      why.includes("unknown_product")
        ? " — SKU chưa có trong Danh mục sản phẩm"
        : why.includes("low_confidence")
          ? " — độ tin cậy thấp hơn ngưỡng giỏ"
          : "";
    message.warning(`Nhận diện được nhưng chưa vào giỏ: ${why}${hint}`);
    addLog("remove", `${sourceLabel} — box bị backend từ chối`, why);
  } else if (detections.length > 0 && withSku.length === 0) {
    const names = detections.map((d) => d.class_name).join(", ");
    message.warning(`Phát hiện ${detections.length} đối tượng (${names}) nhưng chưa map được SKU`);
    addLog("remove", `${sourceLabel} — không map SKU`, names);
  } else if (detections.length > 0) {
    message.warning(
      `Phát hiện ${withSku.length || detections.length} sản phẩm nhưng không phát sự kiện giỏ`,
    );
    addLog("remove", `${sourceLabel} — không emit product_scanned`, skuList);
  } else {
    message.warning("Không phát hiện sản phẩm");
    addLog("remove", `${sourceLabel} — không có detection`, "");
  }
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

function getPersonInfoFromSessionId(sessionId?: string | null) {
  if (!sessionId) return null;
  const match = sessionId.match(/cam:([^:]+):track:person-(\d+)/);
  if (match) {
    return {
      cameraId: match[1],
      mappedId: parseInt(match[2], 10),
    };
  }
  return null;
}

// session_id dạng "cam:<camera_uuid>:track:checkout-p<mapped_id>-<epoch>"
// (xem ai-engine/app/api/frame.py::_checkout_person_session) — chỉ cần
// mappedId để hiện nhãn "Khách hàng ID: N", ảnh thật lấy qua
// cart.has_customer_photo + CartCustomerPhoto bên dưới, không qua session_id.
function getCheckoutPersonId(sessionId?: string | null): number | null {
  if (!sessionId) return null;
  const match = sessionId.match(/track:checkout-p(\d+)-\d+/);
  return match ? parseInt(match[1], 10) : null;
}

/**
 * Ảnh chủ giỏ hàng, tự tải khi mount và tự dọn blob URL khi unmount —
 * xem getCartCustomerPhotoUrl (api/carts.ts) cho lý do phải đi qua fetch
 * blob thay vì gắn thẳng vào src (endpoint có xác thực JWT).
 */
function CartCustomerPhoto({ cartId, size = 36 }: { cartId: string; size?: number }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    getCartCustomerPhotoUrl(cartId)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        objectUrl = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setUrl(null);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [cartId]);

  if (!url) {
    return (
      <div
        style={{
          width: size,
          height: size * 1.5,
          borderRadius: 4,
          background: "#f5f5f5",
          border: "1.5px solid #2f54eb",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: size * 0.5,
        }}
      >
        👤
      </div>
    );
  }
  return (
    <img
      src={url}
      alt="Ảnh khách hàng"
      style={{
        width: size,
        height: size * 1.5,
        objectFit: "cover",
        borderRadius: 4,
        border: "1.5px solid #2f54eb",
        backgroundColor: "#f5f5f5",
      }}
    />
  );
}

interface AiLogItem {
  id: string;
  time: string;
  type: "scan" | "add" | "remove" | "checkout" | "info";
  message: string;
  detail?: string;
}

interface ActivePerson {
  mapped_id: number;
  crop_url: string;
}

function ActivePersonsPanel({ camera, paused = false }: { camera: Camera; paused?: boolean }) {
  const [activePersons, setActivePersons] = useState<ActivePerson[]>([]);

  useEffect(() => {
    if (paused) {
      // Tạm dừng nhận diện AI thì panel này cũng phải dừng theo — poll tiếp
      // vừa tốn request vô ích (không có gì mới để lấy, luồng đã dừng) vừa
      // khiến admin thấy "khách đang ở quầy" cập nhật liên tục dù đã bấm
      // Tạm dừng, ngỡ rằng AI vẫn đang chạy ngầm.
      setActivePersons([]);
      return;
    }

    let active = true;
    const fetchActive = async () => {
      try {
        const res = await fetch(`/ai/active-persons/${camera.id}`);
        if (!res.ok) return;
        const data = await res.json();
        if (active && data.active_persons) {
          setActivePersons(data.active_persons);
        }
      } catch (err) {
        // ignore
      }
    };

    fetchActive();
    const id = setInterval(fetchActive, 2000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [camera.id, paused]);

  if (activePersons.length === 0) return null;

  return (
    <Card size="small" title="👤 Khách hàng đang ở khu vực quầy" style={{ borderRadius: 8, marginTop: 12 }}>
      <div style={{ display: "flex", gap: 16, overflowX: "auto", padding: "8px 0" }}>
        {activePersons.map((p) => (
          <div key={p.mapped_id} style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 80 }}>
            <img
              src={p.crop_url}
              alt={`Person ${p.mapped_id}`}
              style={{
                width: 60,
                height: 90,
                objectFit: "cover",
                borderRadius: 4,
                border: "2px solid #1677ff",
                boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
                backgroundColor: "#f0f0f0"
              }}
              onError={(e) => {
                (e.target as HTMLImageElement).src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='60' height='90'><rect width='60' height='90' fill='%23ccc'/><text x='15' y='50' fill='%23666' font-size='10'>👤</text></svg>";
              }}
            />
            <Tag color="blue" style={{ marginTop: 6, fontWeight: "bold" }}>
              ID: {p.mapped_id}
            </Tag>
          </div>
        ))}
      </div>
    </Card>
  );
}


export default function LiveCartPage() {
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchId] = useState<string | undefined>();
  const [carts, setCarts] = useState<Cart[]>([]);
  const [loading, setLoading] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastRefreshInfo, setLastRefreshInfo] = useState<string>("");
  const [qrByCart, setQrByCart] = useState<Record<string, CartCheckoutQrResponse>>({});
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [liveCameraId, setLiveCameraId] = useState<string | undefined>();
  const [showLive, setShowLive] = useState(true);
  const [liveDetect, setLiveDetect] = useState(true);
  const [showAiProgress, setShowAiProgress] = useState(true);
  const [aiPaused, setAiPaused] = useState(false);
  const [aiPauseSaving, setAiPauseSaving] = useState(false);
  const [streamStatus, setStreamStatus] = useState<LiveStreamStatus>("connecting");
  const [aiLogs, setAiLogs] = useState<AiLogItem[]>([]);

  const addLog = useCallback((type: AiLogItem["type"], messageText: string, detail?: string) => {
    const time = new Date().toLocaleTimeString("vi-VN");
    setAiLogs((prev) => [
      { id: `${Date.now()}-${Math.random()}`, time, type, message: messageText, detail },
      ...prev.slice(0, 29),
    ]);
  }, []);

  useEffect(() => {
    if (!branchId) {
      setCameras([]);
      setLiveCameraId(undefined);
      return;
    }
    (async () => {
      try {
        const res = await listCameras({ branch_id: branchId, is_active: true, limit: 100 });
        setCameras(res.items);
        const preferred =
          res.items.find((c) => c.is_checkout_zone) ?? res.items[0];
        setLiveCameraId(preferred?.id);
      } catch {
        setCameras([]);
        setLiveCameraId(undefined);
      }
    })();
  }, [branchId]);

  useEffect(() => {
    if (!branchId) {
      setAiPaused(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await getAiAutoScan(branchId);
        if (!cancelled) setAiPaused(res.paused);
      } catch {
        if (!cancelled) setAiPaused(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [branchId]);

  const liveCamera = useMemo(
    () => cameras.find((c) => c.id === liveCameraId),
    [cameras, liveCameraId],
  );

  const onToggleAiAutoScan = async (enabled: boolean) => {
    if (!branchId) return;
    setAiPauseSaving(true);
    const nextPaused = !enabled;
    const previous = aiPaused;
    setAiPaused(nextPaused);
    try {
      const res = await setAiAutoScan(branchId, nextPaused);
      setAiPaused(res.paused);
      if (res.paused) {
        message.info("Đã tắt AI tự động thêm giỏ — live vẫn đánh dấu sản phẩm bằng chấm màu trong vùng thanh toán");
        addLog("info", "⏸️ Tắt AI tự động", "Không tự thêm giỏ; live overlay, Chụp & Quét và Tải ảnh vẫn chạy");
      } else {
        message.success("Đã bật lại nhận diện AI tự động");
        addLog("info", "▶️ Bật AI tự động", "Luồng live lại thêm SKU vào giỏ");
      }
    } catch (err) {
      setAiPaused(previous);
      const detail =
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không đổi được trạng thái AI tự động";
      message.error(detail);
    } finally {
      setAiPauseSaving(false);
    }
  };

  useEffect(() => {
    (async () => {
      try {
        const res = await listBranches({ skip: 0, limit: 200 });
        setBranches(res.items);
        if (res.items.length && !branchId) setBranchId(res.items[0].id);
      } catch {
        message.error("Không tải được danh sách chi nhánh");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback(async () => {
    if (!branchId) return;
    setLoading(true);
    try {
      const [activeRes, pendingRes] = await Promise.all([
        listCarts({ branch_id: branchId, status: "active", limit: 100 }),
        listCarts({ branch_id: branchId, status: "pending_checkout", limit: 100 }),
      ]);
      const allCarts = [...pendingRes.items, ...activeRes.items];
      setCarts(allCarts);
    } catch (err) {
      console.error("[LiveCart] load error:", err);
      message.error("Không tải được danh sách giỏ hàng");
    } finally {
      setLoading(false);
    }
  }, [branchId]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  useEffect(() => {
    if (!branchId) return;
    let ws: WebSocket | null = null;
    let retry: number | null = null;
    let cancelled = false;

    const connect = () => {
      const token = tokenStore.getAccess();
      if (!token || cancelled) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      const host = window.location.port === "3000" ? `${window.location.hostname}:8000` : window.location.host;
      const url = `${proto}://${host}/ws/carts?token=${encodeURIComponent(token)}&branch_id=${branchId}`;
      try {
        ws = new WebSocket(url);
      } catch {
        return;
      }
      ws.onopen = () => {
        setWsConnected(true);
        addLog("info", "Kết nối Realtime AI thành công", "Sẵn sàng nhận dữ liệu trực tiếp 0.1s");
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data?.type === "cart_update") {
            const act = data.action;
            if (act === "cart_line_added" || act === "line_added") {
              addLog("add", `🛒 AI đã nhận diện & thêm sản phẩm vào giỏ`, `Giỏ ${data.cart_id?.slice(0, 8)} • Tổng: ${formatMoney(data.total_amount || "0", data.currency || "VND")}`);
            } else if (act === "checkout_pending" || act === "checkout_requested") {
              addLog("checkout", `⚡ Khách vào vùng quầy — Đã đóng băng hoá đơn`, `Mã giỏ: ${data.cart_id?.slice(0, 8)}`);
            } else if (act === "cart_created") {
              addLog("scan", `Mở giỏ hàng AI mới cho phiên quầy`, `Phiên ${data.cart_id?.slice(0, 8)}`);
            } else if (act === "cart_abandoned") {
              addLog("remove", `Đã hủy giỏ hàng — Reset phiên quầy`, `AI đang tự động quét tạo giỏ mới cho sản phẩm trên quầy (2s)...`);
            } else {
              addLog("info", `Cập nhật giỏ AI (${act})`, `Mã giỏ: ${data.cart_id?.slice(0, 8)}`);
            }
          }
        } catch {
          // ignore
        }
        load();
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
  }, [branchId, load, addLog]);

  const totalRevenuePending = useMemo(
    () =>
      carts.reduce((sum, c) => sum + Number(c.total_amount || 0), 0),
    [carts],
  );

  const onCheckout = async (cart: Cart) => {
    try {
      const res = await checkoutCart(cart.id);
      message.success(`Đã tạo đơn ${res.order_code}`);
      load();
    } catch (err) {
      const detail =
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không thể checkout";
      message.error(detail);
    }
  };

  const onAbandon = async (cart: Cart) => {
    try {
      await abandonCart(cart.id);
      message.success("Đã hủy giỏ hàng");
      load();
    } catch {
      message.error("Không thể hủy giỏ hàng");
    }
  };

  const [manualScanning, setManualScanning] = useState(false);
  const [uploadingScan, setUploadingScan] = useState(false);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  const onManualTriggerScan = async () => {
    if (!liveCameraId) {
      message.warning("Chưa chọn camera để chụp/quét");
      return;
    }
    setManualScanning(true);
    try {
      const res = await triggerCameraScan(liveCameraId);
      reportScanOutcome(res.detections ?? [], res.emitted_events ?? [], addLog, "📸 Quét khung live");
      load();
    } catch (err) {
      const detail =
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không chụp/quét được khung hình camera";
      message.error(detail);
    } finally {
      setManualScanning(false);
    }
  };

  const onUploadImageScan = async (file: File) => {
    if (!liveCameraId) {
      message.warning("Chọn camera (chi nhánh) trước khi tải ảnh");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      message.error("Ảnh vượt quá 10 MB");
      if (uploadInputRef.current) uploadInputRef.current.value = "";
      return;
    }
    setUploadingScan(true);
    try {
      const res = await analyzeCameraFrame(liveCameraId, file);
      if (res.frame_pipeline_error) {
        message.error(`Phân tích ảnh lỗi: ${res.frame_pipeline_error}`);
        addLog("remove", "🖼️ Tải ảnh — pipeline lỗi", res.frame_pipeline_error);
        return;
      }
      const pipeline = res.frame_pipeline;
      reportScanOutcome(
        pipeline?.detections ?? res.detections ?? [],
        pipeline?.emitted_events ?? [],
        addLog,
        "🖼️ Tải ảnh",
      );
      load();
    } catch (err) {
      const detail =
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không phân tích được ảnh";
      message.error(detail);
    } finally {
      setUploadingScan(false);
      if (uploadInputRef.current) uploadInputRef.current.value = "";
    }
  };

  const onBulkAbandonCarts = async () => {
    // Không gửi ID của riêng trang đang hiển thị (carts state chỉ tải tối
    // đa 100 giỏ/loại) — gọi KHÔNG kèm cart_ids để backend tự gom HẾT các
    // trang rồi hủy toàn bộ trong một lượt, tránh phải bấm lại nhiều lần
    // khi số giỏ tồn đọng vượt quá 1 trang.
    try {
      const res = await bulkAbandonCarts(undefined, branchId);
      message.success(`Đã hủy ${res.abandoned} giỏ hàng thành công`);
      addLog("remove", `Đã xóa / hủy hàng loạt ${res.abandoned} giỏ hàng`);
      load();
    } catch {
      message.error("Hủy hàng loạt giỏ hàng thất bại");
    }
  };

  const onRemoveLine = async (cart: Cart, lineId: string) => {
    try {
      await removeCartLine(cart.id, lineId);
      load();
    } catch {
      message.error("Không xóa được sản phẩm");
    }
  };

  const onShowQr = async (cart: Cart) => {
    try {
      const qr = await getCheckoutQr(cart.id);
      setQrByCart((prev) => ({ ...prev, [cart.id]: qr }));
    } catch {
      message.error("Không tải được mã QR xác nhận");
    }
  };

  const onConfirmStaff = async (cart: Cart) => {
    try {
      const res = await confirmCheckoutStaff(cart.id);
      message.success(`Đã xác nhận hộ khách — đơn ${res.order_code}`);
      setQrByCart((prev) => {
        const next = { ...prev };
        delete next[cart.id];
        return next;
      });
      load();
    } catch (err) {
      const detail =
        isAxiosError(err) && err.response?.data?.detail
          ? String(err.response.data.detail)
          : "Không thể xác nhận thanh toán";
      message.error(detail);
    }
  };

  const onCancelCheckout = async (cart: Cart) => {
    try {
      await cancelCheckout(cart.id);
      setQrByCart((prev) => {
        const next = { ...prev };
        delete next[cart.id];
        return next;
      });
      message.info("Đã huỷ, khách tiếp tục mua sắm");
      load();
    } catch {
      message.error("Không thể huỷ chờ xác nhận");
    }
  };

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card>
        <Row gutter={16} align="middle">
          <Col flex="auto">
            <Space size="large" wrap>
              <Space>
                <Typography.Text strong>Chi nhánh:</Typography.Text>
                <Select
                  style={{ minWidth: 240 }}
                  placeholder="Chọn chi nhánh"
                  value={branchId}
                  onChange={setBranchId}
                  options={branches.map((b) => ({
                    label: `${b.code} — ${b.name}`,
                    value: b.id,
                  }))}
                />
              </Space>
              <Badge
                status={wsConnected ? "success" : "default"}
                text={wsConnected ? "Realtime đang bật" : "Realtime tắt"}
              />
            </Space>
          </Col>
          <Col>
            <Space>
              <Button
                icon={<ReloadOutlined />}
                onClick={load}
                loading={loading}
              >
                Làm mới
              </Button>
              {carts.length > 0 && (
                <Popconfirm
                  title="Bạn có chắc muốn HỦY/XÓA TOÀN BỘ giỏ hàng đang mở không?"
                  description={`Đang hiển thị ${carts.length} giỏ — nhưng thao tác này xóa TẤT CẢ giỏ đang mở của chi nhánh, kể cả những giỏ chưa tải lên trang này.`}
                  onConfirm={onBulkAbandonCarts}
                  okText="Xóa tất cả"
                  cancelText="Bỏ qua"
                >
                  <Button danger type="primary" icon={<DeleteOutlined />} style={{ fontWeight: 600 }}>
                    🗑️ Xóa / Hủy tất cả
                  </Button>
                </Popconfirm>
              )}
            </Space>
          </Col>
        </Row>
      </Card>

      <Card
        title={
          <Space>
            <Typography.Text strong>Camera trực tiếp</Typography.Text>
            <Typography.Text type="secondary" style={{ fontWeight: 400 }}>
              (đối chiếu giỏ hàng với cảnh thật trên quầy)
            </Typography.Text>
          </Space>
        }
        extra={
          <Space size="middle" wrap>
            <input
              ref={uploadInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/bmp"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void onUploadImageScan(file);
              }}
            />
            <Button
              type="primary"
              icon={<CameraOutlined />}
              loading={manualScanning}
              disabled={!liveCameraId || uploadingScan}
              onClick={onManualTriggerScan}
              style={{ fontWeight: 600, backgroundColor: "#1677ff" }}
            >
              📸 Chụp & Quét AI Khung Hình Này
            </Button>
            <Tooltip title="JPEG / PNG / WebP / BMP, tối đa 10 MB. Ảnh có sản phẩm trên quầy — AI nhận diện và thêm vào giỏ giống Chụp & Quét.">
              <span>
                <Button
                  icon={<UploadOutlined />}
                  loading={uploadingScan}
                  disabled={!liveCameraId || manualScanning}
                  onClick={() => {
                    if (!liveCameraId) {
                      message.warning("Chọn camera (chi nhánh) trước khi tải ảnh");
                      return;
                    }
                    uploadInputRef.current?.click();
                  }}
                >
                  Tải ảnh & Quét
                </Button>
              </span>
            </Tooltip>
            <Space>
              <Typography.Text type="secondary">AI tự động</Typography.Text>
              <Switch
                checked={!aiPaused}
                loading={aiPauseSaving}
                disabled={!branchId}
                onChange={onToggleAiAutoScan}
              />
            </Space>
            <Space>
              <Typography.Text type="secondary">Khung nhận diện</Typography.Text>
              <Switch checked={liveDetect} onChange={setLiveDetect} size="small" />
            </Space>
            <Space>
              <Typography.Text type="secondary">Hiện camera</Typography.Text>
              <Switch checked={showLive} onChange={setShowLive} size="small" />
            </Space>
          </Space>
        }
      >
        {showLive ? (
          <Row gutter={[16, 16]}>
            {aiPaused && (
              <Col span={24}>
                <Alert
                  type="warning"
                  showIcon
                  message="AI tự động đang tắt"
                  description="Luồng live vẫn nhận diện và đánh dấu sản phẩm bằng chấm màu trong vùng thanh toán. Chỉ không tự thêm vào giỏ — dùng Chụp & Quét hoặc Tải ảnh & Quét khi cần nhập đơn. Bật lại công tắc AI tự động khi xong."
                />
              </Col>
            )}
            <Col xs={24} md={10} lg={9}>
              <Space direction="vertical" style={{ width: "100%" }} size="small">
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>Chọn camera đối chiếu</Typography.Text>
                  <Select
                    style={{ width: "100%", marginTop: 2 }}
                    placeholder="Chọn camera"
                    value={liveCameraId}
                    onChange={setLiveCameraId}
                    notFoundContent="Chi nhánh chưa có camera"
                    options={cameras.map((c) => ({
                      label: `${c.name}${c.is_checkout_zone ? " — Quầy thanh toán" : ""}`,
                      value: c.id,
                    }))}
                  />
                  {liveCamera && !liveCamera.is_checkout_zone && (
                    <Typography.Text type="warning" style={{ fontSize: 11, marginTop: 4, display: "block" }}>
                      ⚠️ Camera này không phải quầy thanh toán.
                    </Typography.Text>
                  )}
                </div>

                <Card
                  size="small"
                  style={{ background: "#fafafa", borderRadius: 8 }}
                  styles={{ body: { paddingBottom: 8 } }}
                >
                  <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 6 }}>
                    <Typography.Text strong style={{ fontSize: 13 }}>
                      ⚡ Tiến độ nhận diện AI
                    </Typography.Text>
                    <Switch
                      checked={showAiProgress}
                      checkedChildren="Hiện"
                      unCheckedChildren="Ẩn"
                      onChange={setShowAiProgress}
                    />
                  </Space>
                  {!liveDetect ? (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      Khung nhận diện đang tắt — bật công tắc <Typography.Text strong style={{ fontSize: 12 }}>Khung nhận diện</Typography.Text> để hiện chấm màu sản phẩm trên live.
                    </Typography.Text>
                  ) : streamStatus === "error" ? (
                    <Typography.Text type="warning" style={{ fontSize: 12 }}>
                      ⚠️ Mất luồng camera — đang tự động thử kết nối lại…
                    </Typography.Text>
                  ) : !showAiProgress ? (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      Ẩn bước tiến độ. Camera live vẫn nhận diện và hiển thị sản phẩm trong vùng thanh toán
                      {aiPaused ? " (không tự thêm vào giỏ)." : "."}
                    </Typography.Text>
                  ) : (
                    <Steps
                      direction="vertical"
                      size="small"
                      current={
                        streamStatus === "connecting"
                          ? 0
                          : carts.length > 0
                            ? 3
                            : 1
                      }
                      items={[
                        {
                          title: "Luồng Camera Live",
                          description: streamStatus === "live" ? "RTSP 8 FPS đang mở" : "Đang kết nối…",
                          icon: streamStatus === "live" ? <EyeOutlined /> : <SyncOutlined spin />,
                        },
                        {
                          title: "AI YOLOv8 Nhận dạng",
                          description: "Đang quét ROI payzone (Min 40%)",
                          icon: <SyncOutlined spin />,
                        },
                        {
                          title: "Gửi sự kiện cart-events",
                          description: "Tự động phát hiện & khớp SKU",
                          icon: <CloudUploadOutlined />,
                        },
                        {
                          title: "Xác nhận & Vào giỏ",
                          description: carts.length > 0 ? `Có ${carts.reduce((s, c) => s + c.lines.length, 0)} món trong giỏ` : "Chờ đặt món lên quầy",
                          icon: <ShoppingCartOutlined />,
                        },
                      ]}
                    />
                  )}
                </Card>

                <Card size="small" title="📋 Nhật ký sự kiện AI & Realtime" style={{ maxHeight: 200, overflowY: "auto", borderRadius: 8 }}>
                  {aiLogs.length === 0 ? (
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      Chưa có sự kiện mới. AI đang theo dõi khung hình...
                    </Typography.Text>
                  ) : (
                    <Timeline
                      pending={false}
                      items={aiLogs.map((log) => ({
                        color: log.type === "add" ? "green" : log.type === "checkout" ? "orange" : log.type === "remove" ? "red" : "blue",
                        children: (
                          <div style={{ fontSize: 11, marginBottom: 2 }}>
                            <Space size={4}>
                              <Tag color="default" style={{ fontSize: 10, margin: 0, padding: "0 4px" }}>{log.time}</Tag>
                              <Typography.Text strong style={{ fontSize: 11 }}>{log.message}</Typography.Text>
                            </Space>
                            {log.detail && (
                              <div style={{ color: "#666", fontSize: 10, marginTop: 1 }}>{log.detail}</div>
                            )}
                          </div>
                        ),
                      }))}
                    />
                  )}
                </Card>
              </Space>
            </Col>
            <Col xs={24} md={14} lg={15}>
              <div style={{ width: "100%", margin: "0 auto" }}>
                {liveCamera ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                    <LiveCameraView
                      camera={liveCamera}
                      detect={liveDetect}
                      detectEveryN={6}
                      paused={false}
                      onStatusChange={setStreamStatus}
                    />
                    <ActivePersonsPanel camera={liveCamera} paused={false} />
                  </div>
                ) : (
                  <Empty description="Chưa chọn camera" />
                )}
              </div>
            </Col>
          </Row>
        ) : (
          <Typography.Text type="secondary">
            Đã ẩn camera — bật lại bằng công tắc "Hiện camera".
          </Typography.Text>
        )}
      </Card>

      <Row gutter={16}>
        <Col span={8}>
          <Card
            extra={
              carts.length > 0 && (
                <Popconfirm
                  title="Xóa TOÀN BỘ giỏ hàng đang mở của chi nhánh?"
                  description={`Không chỉ ${carts.length} giỏ đang hiển thị — kể cả những giỏ chưa tải lên trang này.`}
                  onConfirm={onBulkAbandonCarts}
                  okText="Xóa hết"
                  cancelText="Bỏ qua"
                >
                  <Button danger size="small" type="primary" icon={<DeleteOutlined />}>
                    Xóa tất cả
                  </Button>
                </Popconfirm>
              )
            }
          >
            <Statistic
              title="Giỏ hàng đang mở"
              value={carts.length}
              prefix={<ShoppingCartOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Tổng giá trị chờ thanh toán"
              value={totalRevenuePending}
              precision={0}
              suffix="VND"
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic
              title="Tổng sản phẩm"
              value={carts.reduce((s, c) => s + c.lines.length, 0)}
            />
          </Card>
        </Col>
      </Row>

      {carts.length === 0 ? (
        <Card>
          <Empty description="Chưa có giỏ hàng nào đang mở tại chi nhánh này" />
        </Card>
      ) : (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <Typography.Text strong style={{ fontSize: 16 }}>
              Danh sách Giỏ hàng đang mở ({carts.length})
            </Typography.Text>
            <Popconfirm
              title="Bạn có chắc muốn hủy/xóa TOÀN BỘ giỏ hàng đang mở không?"
              description={`Đang hiển thị ${carts.length} giỏ — thao tác này xóa tất cả, kể cả giỏ chưa tải lên trang này.`}
              onConfirm={onBulkAbandonCarts}
              okText="Xóa tất cả"
              cancelText="Hủy"
            >
              <Button danger icon={<DeleteOutlined />}>
                Xóa / Hủy tất cả giỏ hàng
              </Button>
            </Popconfirm>
          </div>
          <Row gutter={[16, 16]}>
            {carts.map((cart) => (
            <Col span={12} key={cart.id}>
              <Card
                title={
                  <Space>
                    <Tag color={STATUS_COLOR[cart.status]}>
                      {STATUS_LABEL[cart.status]}
                    </Tag>
                    <Tag color={cart.source === "ai_vision" ? "purple" : "geekblue"}>
                      {SOURCE_LABEL[cart.source] ?? cart.source}
                    </Tag>
                    <Typography.Text code>
                      {cart.session_id ?? cart.id.slice(0, 8)}
                    </Typography.Text>
                  </Space>
                }
                extra={
                  cart.status === "pending_checkout" ? (
                    <Space>
                      <Button icon={<QrcodeOutlined />} onClick={() => onShowQr(cart)}>
                        Hiện QR
                      </Button>
                      <Popconfirm
                        title="Xác nhận hộ khách (không có QR)?"
                        onConfirm={() => onConfirmStaff(cart)}
                      >
                        <Button type="primary">Xác nhận hộ</Button>
                      </Popconfirm>
                      <Tooltip title="Huỷ chờ xác nhận, khách tiếp tục mua sắm">
                        <Button
                          danger
                          icon={<StopOutlined />}
                          onClick={() => onCancelCheckout(cart)}
                        />
                      </Tooltip>
                    </Space>
                  ) : (
                    <Space>
                      <Button
                        type="primary"
                        onClick={() => onCheckout(cart)}
                        disabled={cart.lines.length === 0}
                      >
                        Checkout
                      </Button>
                      <Popconfirm
                        title="Hủy giỏ hàng này?"
                        onConfirm={() => onAbandon(cart)}
                      >
                        <Button danger>Hủy</Button>
                      </Popconfirm>
                    </Space>
                  )
                }
              >
                {(() => {
                  const personInfo = getPersonInfoFromSessionId(cart.session_id);
                  const isCheckoutCart = cart.session_id?.includes(":track:checkout-");
                  if (cart.has_customer_photo) {
                    const checkoutPersonId = getCheckoutPersonId(cart.session_id);
                    return (
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, padding: "8px 12px", background: "#f0f5ff", border: "1px solid #adc6ff", borderRadius: 6 }}>
                        <CartCustomerPhoto cartId={cart.id} />
                        <div>
                          <div style={{ fontWeight: "bold", fontSize: 13, color: "#1d39c4" }}>
                            👤 Khách hàng{checkoutPersonId !== null ? ` #${checkoutPersonId}` : ""}
                          </div>
                          <div style={{ fontSize: 11, color: "#595959" }}>
                            Ảnh chụp lúc AI ghép sản phẩm đầu tiên vào giỏ
                          </div>
                        </div>
                      </div>
                    );
                  }
                  if (personInfo) {
                    return (
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, padding: "8px 12px", background: "#f0f5ff", border: "1px solid #adc6ff", borderRadius: 6 }}>
                        <img
                          src={`/ai/person-crop/${personInfo.cameraId}/${personInfo.mappedId}`}
                          alt={`Khách hàng ${personInfo.mappedId}`}
                          style={{
                            width: 36,
                            height: 54,
                            objectFit: "cover",
                            borderRadius: 4,
                            border: "1.5px solid #2f54eb",
                            backgroundColor: "#f5f5f5"
                          }}
                          onError={(e) => {
                            (e.target as HTMLImageElement).src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='36' height='54'><rect width='36' height='54' fill='%23ccc'/><text x='6' y='32' fill='%23666' font-size='10'>👤</text></svg>";
                          }}
                        />
                        <div>
                          <div style={{ fontWeight: "bold", fontSize: 13, color: "#1d39c4" }}>
                            👤 Khách hàng ID: {personInfo.mappedId}
                          </div>
                          <div style={{ fontSize: 11, color: "#595959" }}>
                            Liên kết giỏ hàng tự động qua ngoại hình
                          </div>
                        </div>
                      </div>
                    );
                  }
                  if (isCheckoutCart) {
                    return (
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, padding: "8px 12px", background: "#fffbe6", border: "1px solid #ffe58f", borderRadius: 6 }}>
                        <ScanOutlined style={{ fontSize: 20, color: "#d4b106" }} />
                        <div>
                          <div style={{ fontWeight: "bold", fontSize: 13, color: "#ad8b00" }}>
                            ⚡ Phiên quầy thanh toán
                          </div>
                          <div style={{ fontSize: 11, color: "#595959" }}>
                            Đang xử lý sản phẩm đặt trên quầy thu ngân
                          </div>
                        </div>
                      </div>
                    );
                  }
                  return null;
                })()}

                {cart.status === "pending_checkout" && cart.overall_confidence < 0.75 && (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type="error"
                    showIcon
                    message={`Độ tin cậy AI thấp (${Math.round(cart.overall_confidence * 100)}%)`}
                    description="Nên kiểm tra lại từng sản phẩm trước khi xác nhận hộ khách — AI có thể đã nhận diện sai."
                  />
                )}
                {cart.status === "pending_checkout" && qrByCart[cart.id] && (
                  <Alert
                    style={{ marginBottom: 12 }}
                    type="warning"
                    showIcon
                    message="Đang chờ khách xác nhận thanh toán"
                    description={
                      <Space direction="vertical" align="center" style={{ width: "100%" }}>
                        <div
                          style={{ width: 160, height: 160 }}
                          // eslint-disable-next-line react/no-danger
                          dangerouslySetInnerHTML={{
                            __html: qrByCart[cart.id].qr_svg,
                          }}
                        />
                        <Typography.Text code copyable style={{ fontSize: 11 }}>
                          {qrByCart[cart.id].confirm_url}
                        </Typography.Text>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          Khách quét mã này bằng điện thoại để xem hoá đơn và
                          xác nhận thanh toán.
                        </Typography.Text>
                      </Space>
                    }
                  />
                )}
                <List
                  size="small"
                  dataSource={cart.lines}
                  locale={{ emptyText: "Chưa có sản phẩm" }}
                  renderItem={(line) => (
                    <List.Item
                      actions={[
                        <Tooltip key="del" title="Xóa dòng">
                          <Button
                            size="small"
                            danger
                            icon={<DeleteOutlined />}
                            onClick={() => onRemoveLine(cart, line.line_id)}
                          />
                        </Tooltip>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space>
                            <Typography.Text strong>{line.product_name}</Typography.Text>
                            <Tag>{line.sku}</Tag>
                            {line.added_via === "ai" && (
                              <Tooltip title="Độ tin cậy nhận diện của AI cho sản phẩm này">
                                <Tag color={line.confidence < 0.75 ? "red" : "purple"}>
                                  AI {Math.round(line.confidence * 100)}%
                                </Tag>
                              </Tooltip>
                            )}
                          </Space>
                        }
                        description={
                          <Space split="•">
                            <span>SL: {line.quantity}</span>
                            <span>
                              Đơn giá: {formatMoney(line.unit_price, cart.currency)}
                            </span>
                            <span>
                              Thành tiền: {formatMoney(line.subtotal, cart.currency)}
                            </span>
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
                <div style={{ textAlign: "right", marginTop: 12 }}>
                  <Typography.Text strong>
                    Tổng: {formatMoney(cart.total_amount, cart.currency)}
                  </Typography.Text>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      </div>
      )}

      <Alert
        type="info"
        showIcon
        message="Cách hoạt động"
        description={
          <>
            AI Engine gửi sự kiện <code>product_picked_up</code>, <code>product_returned</code>,{" "}
            <code>checkout_initiated</code> tới{" "}
            <code>POST /api/v1/ai/cart-events</code>. Backend tự tạo/mở giỏ theo{" "}
            <code>track_id</code> và cập nhật realtime qua WebSocket{" "}
            <code>/ws/carts</code>. Khi AI phát hiện khách vào khu vực checkout,
            giỏ chuyển sang <code>PENDING_CHECKOUT</code> (đóng băng hoá đơn,
            <b> chưa trừ tiền</b>) — khách quét mã QR hiển thị ở đây để xem hoá
            đơn và tự xác nhận thanh toán, hoặc nhân viên bấm "Xác nhận hộ" nếu
            khách không có điện thoại. Nếu không ai xác nhận trong{" "}
            {"CART_CHECKOUT_CONFIRM_TIMEOUT_MINUTES"} phút, giỏ tự quay lại
            ACTIVE để khách tiếp tục mua sắm. Có thể test bằng{" "}
            <code>POST http://ai-engine:8100/cart/simulate</code>.
          </>
        }
      />
    </Space>
  );
}
