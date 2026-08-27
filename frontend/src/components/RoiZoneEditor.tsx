import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  List,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from "antd";
import { DeleteOutlined, ReloadOutlined } from "@ant-design/icons";

import {
  ZONE_TYPES,
  colorOf,
  labelOf,
  type ZoneType,
} from "@/components/RoiOverlay";
import {
  getRoiZones,
  previewCameraStream,
  updateRoiZones,
  type Camera,
  type RoiZone,
} from "@/api/cameras";

const { Text } = Typography;


/**
 * Vẽ vùng nhận diện lên ảnh chụp thật từ camera.
 *
 * Toạ độ lưu ở dạng PHÂN SỐ (0–1) chứ không phải pixel. Đây là điểm mấu
 * chốt: canvas hiển thị co giãn theo bề rộng modal, và luồng camera có thể
 * đổi độ phân giải bất cứ lúc nào — nếu lưu pixel thì vùng vẽ hôm nay sẽ
 * trượt đi khi đổi camera hoặc khi người khác mở trên màn hình khác.
 */
export default function RoiZoneEditor({
  camera,
  open,
  onClose,
  onSaved,
  snapshotSrc,
  initialZones,
  persistToCamera = true,
  onApply,
  title,
}: {
  camera: Camera | null;
  open: boolean;
  onClose: () => void;
  /** Gọi sau khi lưu thành công, để bảng camera nạp lại roi_zones mới —
   *  nếu không, cột "Vùng nhận diện" và overlay xem trực tiếp vẫn dùng dữ
   *  liệu cũ cho tới khi người dùng tự tải lại trang. */
  onSaved?: () => void;
  /** Ảnh nền sẵn (khung video). Khi có thì không chụp camera. */
  snapshotSrc?: string | null;
  initialZones?: RoiZone[];
  /** false = chỉ dùng vùng cho phiên hiện tại, không ghi vào camera. */
  persistToCamera?: boolean;
  onApply?: (zones: RoiZone[]) => void;
  title?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [snapshotErr, setSnapshotErr] = useState<string | null>(null);
  const [zones, setZones] = useState<RoiZone[]>([]);
  const [draft, setDraft] = useState<[number, number][]>([]);
  const [draftName, setDraftName] = useState("");
  const [draftType, setDraftType] = useState<ZoneType>("checkout");

  // Tăng mỗi lần mở một camera. Mọi kết quả bất đồng bộ (ảnh chụp, danh
  // sách vùng) đều phải khai đúng "phiên" của mình mới được dùng: nếu
  // người dùng đóng modal rồi mở camera khác trong lúc chờ, phản hồi đến
  // muộn của camera cũ sẽ bị bỏ qua thay vì vẽ đè lên camera mới.
  const epochRef = useRef(0);
  // Đếm số lần ảnh nền thay đổi. Đây là lý do tồn tại: trước đây ảnh tải
  // xong thì gọi thẳng redraw() trong callback, nhưng callback đó giữ bản
  // redraw của lần render CŨ — khi ấy `zones` vẫn là vùng của camera
  // trước. Ảnh luôn tải xong sau lời gọi API, nên bản redraw cũ chạy sau
  // cùng và vẽ đè vùng camera cũ lên ảnh camera mới. Đổi thành state để
  // useEffect bên dưới lo việc vẽ, luôn với `zones` mới nhất.
  const [imgEpoch, setImgEpoch] = useState(0);

  const applySnapshot = useCallback((src: string, epoch: number) => {
    const img = new Image();
    img.onload = () => {
      if (epoch !== epochRef.current) return;
      imgRef.current = img;
      const cv = canvasRef.current;
      if (cv && img.naturalWidth && img.naturalHeight) {
        cv.width = img.naturalWidth;
        cv.height = img.naturalHeight;
      }
      setLoading(false);
      setImgEpoch((n) => n + 1);
    };
    img.onerror = () => {
      if (epoch !== epochRef.current) return;
      setSnapshotErr("Không đọc được ảnh nền để vẽ vùng.");
      setLoading(false);
    };
    img.src = src;
  }, []);

  // ---- tải ảnh nền + vùng đã lưu -----------------------------------
  const loadSnapshot = useCallback(async () => {
    if (snapshotSrc) {
      const myEpoch = epochRef.current;
      setLoading(true);
      setSnapshotErr(null);
      applySnapshot(snapshotSrc, myEpoch);
      return;
    }
    if (!camera) return;
    const myEpoch = epochRef.current;
    setLoading(true);
    setSnapshotErr(null);
    try {
      const res = await previewCameraStream(camera.id);
      if (myEpoch !== epochRef.current) return;
      const img = new Image();
      img.onload = () => {
        if (myEpoch !== epochRef.current) return;
        imgRef.current = img;
        // Đặt canvas đúng tỉ lệ ảnh thật thay vì để mặc định 640×480:
        // nếu kéo giãn, vùng vẽ vẫn lưu đúng (toạ độ phân số không đổi khi
        // co giãn) nhưng người dùng nhìn thấy hình bị bóp, khác với màn
        // hình xem trực tiếp — dễ vẽ lệch so với ý muốn.
        const cv = canvasRef.current;
        if (cv && img.naturalWidth && img.naturalHeight) {
          cv.width = img.naturalWidth;
          cv.height = img.naturalHeight;
        }
        setLoading(false);
        setImgEpoch((n) => n + 1);
      };
      img.onerror = () => {
        if (myEpoch !== epochRef.current) return;
        setSnapshotErr("Không giải mã được ảnh chụp từ camera.");
        setLoading(false);
      };
      img.src = `data:image/jpeg;base64,${res.frame_base64}`;
    } catch (e: any) {
      if (myEpoch !== epochRef.current) return;
      // Vẫn cho vẽ trên nền trống: camera có thể đang tắt, nhưng người
      // dùng đã biết bố cục cửa hàng và vẫn muốn khoanh vùng trước.
      setSnapshotErr(
        e?.response?.data?.detail ??
          "Không chụp được ảnh từ camera — bạn vẫn có thể vẽ trên nền trống.",
      );
      setLoading(false);
    }
  }, [camera, snapshotSrc, applySnapshot]);

  useEffect(() => {
    if (!open) return;
    if (persistToCamera && !camera) return;
    const myEpoch = ++epochRef.current;
    setDraft([]);
    setDraftName(persistToCamera ? "" : "Vùng Thanh Toán");
    imgRef.current = null;
    setZones(initialZones ? [...initialZones] : []);
    setImgEpoch((n) => n + 1);
    if (persistToCamera && camera) {
      getRoiZones(camera.id)
        .then((z) => {
          if (myEpoch === epochRef.current) setZones(z);
        })
        .catch(() => {
          if (myEpoch === epochRef.current) setZones([]);
        });
    }
    void loadSnapshot();
  }, [open, camera, loadSnapshot, persistToCamera, snapshotSrc]);

  // ---- vẽ ------------------------------------------------------------
  const redraw = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const { width: W, height: H } = cv;

    ctx.clearRect(0, 0, W, H);
    if (imgRef.current) {
      ctx.drawImage(imgRef.current, 0, 0, W, H);
    } else {
      ctx.fillStyle = "#1f1f1f";
      ctx.fillRect(0, 0, W, H);
    }

    const drawPoly = (
      pts: [number, number][],
      color: string,
      closed: boolean,
      label?: string,
    ) => {
      if (!pts.length) return;
      ctx.beginPath();
      pts.forEach(([fx, fy], i) => {
        const x = fx * W;
        const y = fy * H;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      if (closed) ctx.closePath();
      ctx.lineWidth = 2;
      ctx.strokeStyle = color;
      ctx.stroke();
      if (closed) {
        ctx.fillStyle = color + "33";
        ctx.fill();
      }
      pts.forEach(([fx, fy]) => {
        ctx.beginPath();
        ctx.arc(fx * W, fy * H, 4, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      });
      if (label) {
        const [fx, fy] = pts[0];
        ctx.font = "13px sans-serif";
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = color;
        ctx.fillRect(fx * W, fy * H - 18, tw + 8, 18);
        ctx.fillStyle = "#fff";
        ctx.fillText(label, fx * W + 4, fy * H - 5);
      }
    };

    zones.forEach((z) =>
      drawPoly(z.points, colorOf(z.type), true, `${z.name} (${labelOf(z.type)})`),
    );
    drawPoly(draft, colorOf(draftType), false);
    // imgEpoch nằm trong deps để việc ảnh nền tải xong cũng kích hoạt vẽ
    // lại — thay cho lời gọi redraw() trực tiếp trong callback tải ảnh,
    // vốn dùng lại `zones` cũ của camera trước.
  }, [zones, draft, draftType, imgEpoch]);

  useEffect(redraw, [redraw]);

  const onCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const cv = canvasRef.current;
    if (!cv) return;
    const r = cv.getBoundingClientRect();
    // Chia cho kích thước HIỂN THỊ (rect) chứ không phải cv.width: canvas
    // bị CSS co lại, hai giá trị này khác nhau và dùng nhầm sẽ làm điểm
    // vẽ lệch khỏi vị trí con trỏ.
    const fx = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const fy = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    setDraft((d) => [...d, [fx, fy]]);
  };

  const finishZone = () => {
    if (draft.length < 3) {
      message.warning("Cần ít nhất 3 điểm để tạo một vùng.");
      return;
    }
    const name = draftName.trim();
    if (!name) {
      message.warning("Hãy đặt tên cho vùng (ví dụ: Quầy thanh toán).");
      return;
    }
    setZones((z) => [...z, { name, type: draftType, points: draft }]);
    setDraft([]);
    setDraftName(persistToCamera ? "" : "Vùng Thanh Toán");
  };

  const onSave = async () => {
    if (!persistToCamera) {
      onApply?.(zones);
      message.success(
        zones.length
          ? `Dùng ${zones.length} vùng cho video này — AI chỉ nhận diện trong vùng.`
          : "Không có vùng — AI quét toàn khung video.",
      );
      onClose();
      return;
    }
    if (!camera) return;
    setSaving(true);
    try {
      await updateRoiZones(camera.id, zones);
      message.success(
        zones.length
          ? `Đã lưu ${zones.length} vùng — có hiệu lực trong khoảng 30 giây.`
          : "Đã xoá hết vùng — camera nhận diện lại toàn khung hình.",
      );
      onSaved?.();
      onClose();
    } catch (e: any) {
      message.error(e?.response?.data?.detail ?? "Lưu vùng thất bại.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={title ?? `Vẽ vùng nhận diện — ${camera?.name ?? ""}`}
      open={open}
      onCancel={onClose}
      width={980}
      onOk={onSave}
      okText={persistToCamera ? "Lưu vùng" : "Dùng vùng này"}
      confirmLoading={saving}
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message="Bấm lần lượt lên ảnh để tạo các đỉnh của vùng, đặt tên rồi bấm “Hoàn tất vùng”."
        description={
          persistToCamera
            ? "Hệ thống sẽ che mọi thứ nằm ngoài các vùng đã vẽ trước khi đưa vào nhận diện, nên kệ hàng phía sau hay người qua lại không còn bị tính nhầm. Nếu không vẽ vùng nào, camera vẫn quét toàn khung hình như trước."
            : "Vùng chỉ áp dụng cho video đang phân tích, không ghi đè vùng camera live. Toạ độ theo khung video (phân số 0–1)."
        }
      />

      {snapshotErr && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={snapshotErr}
        />
      )}

      <div style={{ display: "flex", gap: 16 }}>
        <div style={{ flex: "1 1 auto", minWidth: 0 }}>
          <Spin spinning={loading}>
            <canvas
              ref={canvasRef}
              width={640}
              height={480}
              onClick={onCanvasClick}
              style={{
                width: "100%",
                cursor: "crosshair",
                border: "1px solid #434343",
                borderRadius: 4,
                background: "#1f1f1f",
              }}
            />
          </Spin>
          <Space style={{ marginTop: 8 }} wrap>
            <Input
              placeholder="Tên vùng"
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              style={{ width: 180 }}
            />
            <Select
              value={draftType}
              onChange={(v) => setDraftType(v)}
              options={ZONE_TYPES.map((t) => ({
                value: t.value,
                label: t.label,
              }))}
              style={{ width: 160 }}
            />
            <Button type="primary" onClick={finishZone}>
              Hoàn tất vùng ({draft.length} điểm)
            </Button>
            <Button onClick={() => setDraft((d) => d.slice(0, -1))} disabled={!draft.length}>
              Bỏ điểm cuối
            </Button>
            <Button icon={<ReloadOutlined />} onClick={loadSnapshot}>
              {persistToCamera ? "Chụp lại ảnh" : "Tải lại khung"}
            </Button>
          </Space>
        </div>

        <div style={{ width: 260, flex: "0 0 260px" }}>
          <Text strong>Các vùng đã có</Text>
          {zones.length === 0 ? (
            <Empty
              description="Chưa có vùng nào"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ) : (
            <List
              size="small"
              dataSource={zones}
              renderItem={(z, i) => (
                <List.Item
                  actions={[
                    <Button
                      key="del"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() =>
                        setZones((all) => all.filter((_, j) => j !== i))
                      }
                    />,
                  ]}
                >
                  <Space direction="vertical" size={0}>
                    <Text>{z.name}</Text>
                    <Tag color={colorOf(z.type)}>{labelOf(z.type)}</Tag>
                  </Space>
                </List.Item>
              )}
            />
          )}
        </div>
      </div>
    </Modal>
  );
}
