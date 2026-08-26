"""YOLOv8 + ByteTrack person tracker.

Reuses the shared `YoloDetector` weights but calls `model.track()` with
`persist=True` to maintain stable track ids across successive frames from the
same camera.

Track ids are namespaced by `camera_id` because ultralytics resets state per
model call, so we keep an in-process cache of per-camera detector instances.

OpenCV Integration Sprint 1: image decode + optional ROI/enhancement/
quality analysis now goes through `app.vision.pipeline` instead of a raw
PIL decode — see that module's docstring for the exact insertion point and
why handing ultralytics a BGR ndarray (instead of a PIL RGB image) is safe.
`track_frame`'s signature and return type are unchanged on purpose: every
existing caller (`app/api/frame.py`) keeps working without modification.
Quality/timing/overlay data is stashed per-camera and available via
`get_last_vision_result()` for callers that want it (additive, optional).
"""

from __future__ import annotations

import asyncio
import base64
import collections
import logging
import os
from dataclasses import dataclass
from typing import Any

from app.services.det_nms import dense_tile_origins, merge_tiled_detections
from app.vision.config import get_vision_config
from app.vision.metrics.timers import StageTimer
from app.vision.overlay.debug_overlay import OverlayDetection, draw_debug_overlay
from app.vision.pipeline import preprocess_for_detection, record_pipeline_timing

logger = logging.getLogger("ai-engine.person_tracker")

_TRACKERS: dict[str, Any] = {}
_LOCK = asyncio.Lock()

_SHARED_POSE_MODEL: Any = None
_SHARED_DET_MODEL: Any = None
# Path the currently-loaded detection weight came from, so _get_det_model
# can notice when the admin points YOLO_MODEL_PATH at a different weight and
# hot-swap it without a container restart.
_LOADED_DET_PATH: str | None = None
_POSE_TRACKER_STATE: dict[str, Any] = {}
_DET_TRACKER_STATE: dict[str, Any] = {}
_ACTIVE_CAMERA: dict[str, str] = {}
_MODEL_LOCK = asyncio.Lock()

_LAST_VISION_RESULT: dict[str, dict[str, Any]] = {}
_LATEST_PERSON_BOXES: dict[str, list[dict]] = {}

def get_latest_person_boxes(camera_key: str) -> list[dict]:
    import time
    now = time.time()
    boxes = _LATEST_PERSON_BOXES.get(camera_key, [])
    valid_boxes = [b for b in boxes if now - b["timestamp"] < 10.0]
    _LATEST_PERSON_BOXES[camera_key] = valid_boxes
    return valid_boxes


# --- Quỹ đạo di chuyển từng người (vài giây gần nhất) ---
#
# Dùng cho 2 việc: (1) vẽ đường đi lên debug overlay để admin xác minh
# bằng mắt, (2) làm tín hiệu ghép chủ sở hữu sản phẩm ở quầy — xem
# frame.py::_person_reached_near. Đặt ở đây (không phải frame.py) vì đây
# là thông tin thuộc về TRACKING của người, không phải nghiệp vụ giỏ hàng,
# và overlay (cũng ở tầng tracking) cần đọc cùng dữ liệu này.
#
# camera_key -> { mapped_person_id: deque[(cx, cy, ts)] }. maxlen chặn một
# người đứng yên rất lâu không làm phình bộ nhớ — 60 điểm ~ đủ vài chục
# giây ở nhịp xử lý thường gặp.
_PERSON_TRAJECTORIES: dict[str, dict[int, collections.deque]] = {}
_TRAJECTORY_MAXLEN = 60
# Người không xuất hiện lại quá lâu thì dọn quỹ đạo của họ — tách biệt
# với TTL của ReID (features_db) vì mục đích khác nhau.
_TRAJECTORY_STALE_SECONDS = 300.0
# Bảng màu chung cho overlay quỹ đạo — dùng ở cả live.py lẫn debug_overlay.py
# để màu nhất quán khi xem cả hai nơi cùng lúc.
TRAJECTORY_PALETTE: list[tuple[int, int, int]] = [
    (255, 0, 0), (0, 165, 255), (255, 0, 255),
    (0, 255, 255), (255, 255, 0), (128, 0, 255),
]


def record_person_position(
    camera_key: str, mapped_id: int, cx: float, cy: float, ts: float,
    frame_w: float, frame_h: float,
) -> None:
    """Lưu vị trí theo toạ độ PHÂN SỐ (0-1), không phải pixel tuyệt đối —
    cùng quy ước với RoiZone (vision/roi/zones.py). Bắt buộc, vì quỹ đạo
    được GHI từ khung hình của pipeline /ai/frame nhưng lại được VẼ trên
    khung hình của luồng live riêng (live.py) — hai nơi có thể khác kích
    thước. Lưu pixel tuyệt đối rồi vẽ thẳng lên một khung hình khác kích
    thước sẽ ra toạ độ sai lệch (từng gặp: đường vẽ toé ra như pháo hoa
    thay vì một đường đi mượt). Người gọi luôn phải quy đổi ngược sang
    pixel bằng kích thước khung hình CỦA CHÍNH MÌNH — xem
    get_person_trajectory_px/get_all_trajectories_xy/trajectory_last_near_ts."""
    if frame_w <= 0 or frame_h <= 0:
        return
    per_cam = _PERSON_TRAJECTORIES.setdefault(camera_key, {})
    traj = per_cam.get(mapped_id)
    if traj is None:
        traj = collections.deque(maxlen=_TRAJECTORY_MAXLEN)
        per_cam[mapped_id] = traj
    traj.append((cx / frame_w, cy / frame_h, ts))


def get_person_trajectory_px(
    camera_key: str, mapped_id: int, frame_w: float, frame_h: float,
) -> list[tuple[float, float, float]]:
    """Quỹ đạo quy đổi ra pixel theo kích thước khung hình CỦA NGƯỜI GỌI
    (frame_w/frame_h) — không phải kích thước lúc ghi."""
    per_cam = _PERSON_TRAJECTORIES.get(camera_key)
    if not per_cam:
        return []
    traj = per_cam.get(mapped_id)
    if not traj:
        return []
    return [(fx * frame_w, fy * frame_h, ts) for fx, fy, ts in list(traj)]


def get_all_trajectories_xy(
    camera_key: str, frame_w: float, frame_h: float,
) -> dict[int, list[tuple[float, float]]]:
    """(x, y) pixel theo kích thước khung hình của người gọi — dùng để vẽ
    overlay, không cần timestamp."""
    per_cam = _PERSON_TRAJECTORIES.get(camera_key)
    if not per_cam:
        return {}
    return {
        mid: [(fx * frame_w, fy * frame_h) for fx, fy, _ts in list(traj)]
        for mid, traj in list(per_cam.items())
    }


def trajectory_last_near_ts(
    camera_key: str, mapped_id: int, px: float, py: float,
    *, frame_w: float, frame_h: float,
    now: float, window_seconds: float, radius_px: float,
) -> float | None:
    """Thời điểm GẦN NHẤT (mới nhất, không phải sớm nhất) mà người này ở
    trong bán kính radius_px quanh (px, py) — toạ độ pixel của CÙNG khung
    hình mà (px, py) thuộc về (frame_w/frame_h phải khớp khung hình đó,
    thường là khung /ai/frame đang xử lý) — trong window_seconds giây gần
    đây. None nếu chưa từng. Trả cả timestamp (không chỉ True/False) để
    xếp hạng nhiều ứng viên: ai chạm gần đây hơn có khả năng cao hơn là
    người vừa đặt/vừa lấy sản phẩm, so với ai đi qua rồi từ lâu.

    KHÔNG xét khoảng cách HIỆN TẠI của người đó — chủ sở hữu thật sự
    thường đã bước ra xa NGAY SAU KHI đặt sản phẩm xuống (đứng chờ thanh
    toán), nên yêu cầu "đang đứng gần" sẽ loại nhầm đúng người mua và giữ
    lại người đứng yên cạnh đó không hề động vào gì."""
    import math
    last: float | None = None
    for x, y, ts in get_person_trajectory_px(camera_key, mapped_id, frame_w, frame_h):
        if now - ts > window_seconds:
            continue
        if math.hypot(x - px, y - py) <= radius_px:
            if last is None or ts > last:
                last = ts
    return last


def get_recent_trajectory_person_ids(camera_key: str, now: float, window_seconds: float) -> list[int]:
    """Trả danh sách mapped_id của những người có ít nhất một điểm quỹ đạo
    trong window_seconds giây gần đây — kể cả người đã rời khung hình.

    Xét điểm ĐẦU TIÊN (cũ nhất) của deque — nếu điểm CŨ NHẤT còn trong
    cửa sổ thì chắc chắn có điểm nào đó trong cửa sổ. Ngược lại xét điểm
    CUỐI (mới nhất) — nếu điểm mới nhất trong cửa sổ thì có điểm trong cửa
    sổ. Đủ để không bỏ sót người có điểm hợp lệ ở bất kỳ vị trí nào."""
    per_cam = _PERSON_TRAJECTORIES.get(camera_key)
    if not per_cam:
        return []
    result = []
    cutoff = now - window_seconds
    for mid, traj in list(per_cam.items()):
        snap = list(traj)
        if snap and (snap[-1][2] >= cutoff or snap[0][2] >= cutoff):
            result.append(mid)
    return result


def prune_stale_trajectories(now: float) -> None:
    for camera_key, per_cam in list(_PERSON_TRAJECTORIES.items()):
        stale_ids = [
            mid for mid, traj in list(per_cam.items())
            if not traj or now - traj[-1][2] > _TRAJECTORY_STALE_SECONDS
        ]
        for mid in stale_ids:
            per_cam.pop(mid, None)
        if not per_cam:
            _PERSON_TRAJECTORIES.pop(camera_key, None)


def reset_trackers() -> None:
    global _SHARED_POSE_MODEL, _SHARED_DET_MODEL, _LOADED_DET_PATH
    _TRACKERS.clear()
    _POSE_TRACKER_STATE.clear()
    _DET_TRACKER_STATE.clear()
    _ACTIVE_CAMERA.clear()
    _PERSON_TRAJECTORIES.clear()
    _SHARED_POSE_MODEL = None
    _SHARED_DET_MODEL = None
    _LOADED_DET_PATH = None


class ReIDManager:
    def __init__(self, similarity_threshold=0.72):
        self.threshold = similarity_threshold
        self.features_db = {}
        self.tracker_to_mapped = {}
        self.next_id = 1
        self.latest_crops = {}

    def _extract_features(self, crop):
        if crop is None or crop.size == 0:
            return None
        import cv2
        import numpy as np
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist.flatten()

    def get_mapped_id(self, tracker_id, frame, bbox):
        if tracker_id in self.tracker_to_mapped:
            mapped_id = self.tracker_to_mapped[tracker_id]
        else:
            import cv2
            import numpy as np
            x1, y1, x2, y2 = map(int, bbox)
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            
            crop = frame[y1:y2, x1:x2]
            new_feat = self._extract_features(crop)
            
            if new_feat is None:
                mapped_id = self.next_id
                self.tracker_to_mapped[tracker_id] = mapped_id
                self.next_id += 1
            else:
                best_match_id = None
                best_score = -1.0
                
                for mid, db_feat in self.features_db.items():
                    score = cv2.compareHist(new_feat, db_feat, cv2.HISTCMP_CORREL)
                    if score > best_score:
                        best_score = score
                        best_match_id = mid

                if best_score >= self.threshold and best_match_id is not None:
                    mapped_id = best_match_id
                    self.features_db[mapped_id] = 0.8 * self.features_db[mapped_id] + 0.2 * new_feat
                    self.features_db[mapped_id] /= np.linalg.norm(self.features_db[mapped_id])
                    logger.info("[ReID] Matched Tracker ID %d to Persistent ID %d (Similarity: %.2f)", tracker_id, mapped_id, best_score)
                else:
                    mapped_id = self.next_id
                    self.features_db[mapped_id] = new_feat
                    self.next_id += 1
                    logger.info("[ReID] Registered Tracker ID %d as new Persistent ID %d", tracker_id, mapped_id)

            self.tracker_to_mapped[tracker_id] = mapped_id

        # Save/update cropped image for this person
        try:
            import cv2
            x1, y1, x2, y2 = map(int, bbox)
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            crop = frame[y1:y2, x1:x2]
            if crop is not None and crop.size > 0:
                ok, buf = cv2.imencode(".jpg", crop)
                if ok:
                    self.latest_crops[mapped_id] = buf.tobytes()
        except Exception:
            pass

        return mapped_id

_REID_MANAGERS: dict[str, ReIDManager] = {}

def reset_reid(camera_key: str) -> None:
    if camera_key in _REID_MANAGERS:
        _REID_MANAGERS[camera_key] = ReIDManager(similarity_threshold=0.72)
        logger.info("[ReID] Reset database for camera=%s", camera_key)

def get_person_crop_bytes(camera_key: str, mapped_id: int) -> bytes | None:
    if camera_key in _REID_MANAGERS:
        return _REID_MANAGERS[camera_key].latest_crops.get(mapped_id)
    return None


@dataclass(frozen=True)
class TrackedObject:
    track_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    left_hand: tuple[float, float] | None = None
    right_hand: tuple[float, float] | None = None

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0


# Track-id của đề xuất contour bắt đầu từ đây, tách hẳn khỏi id của
# ByteTrack (đếm từ 1 lên) để hai bên không bao giờ đè id lên nhau.
_PROPOSAL_ID_BASE = 1_000_000

# Confidence danh nghĩa gán cho một đề xuất contour.
#
# QUAN TRỌNG: điểm số của đề xuất (propose_regions) là TỈ LỆ DIỆN TÍCH của
# vùng (~0.01–0.05 cho một gói mì trên bàn), KHÔNG phải độ tin cậy kiểu
# detector. Nếu đem tỉ lệ đó làm `confidence` thì frame.py sẽ loại vùng ngay
# ở cổng `det.confidence < min_confidence` (mặc định 0.4) — tức mọi gói mì
# do contour đề xuất bị vứt TRƯỚC khi tới classifier, "có thấy nhưng không
# vào đơn". Cổng lọc ĐÚNG cho vùng contour là chính bộ phân loại SKU (ngưỡng
# CLASSIFIER_MIN_CONFIDENCE = 0.55): lớp 'region' không có đường ánh xạ theo
# tên lớp, nên chỉ khi classifier tự tin mới sinh ra SKU; vùng nhiễu vẫn bị
# loại đúng chỗ đó. Vì thế ở đây gán một confidence cố định vượt cổng
# detection để vùng CHẮC CHẮN tới được classifier, rồi để classifier quyết.
_PROPOSAL_CONFIDENCE = 0.60



def _iou(a: "TrackedObject", bx1: int, by1: int, bx2: int, by2: int) -> float:
    ix1, iy1 = max(a.x1, bx1), max(a.y1, by1)
    ix2, iy2 = min(a.x2, bx2), min(a.y2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (a.x2 - a.x1) * (a.y2 - a.y1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)


def _boxes_from_yolo_result(
    result, *, id_base: int, ox: float = 0.0, oy: float = 0.0
) -> list[TrackedObject]:
    """Read every box even when ByteTrack did not assign ids (single-frame scan)."""
    names = result.names or {}
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []
    n = len(boxes)
    if boxes.id is not None:
        ids = boxes.id.int().cpu().tolist()
    else:
        ids = [id_base + i for i in range(n)]
    out: list[TrackedObject] = []
    for i, tid in enumerate(ids):
        cls_idx = int(boxes.cls[i]) if boxes.cls is not None else -1
        class_name = str(names.get(cls_idx, str(cls_idx)))
        if class_name.lower() == "person":
            continue
        conf = float(boxes.conf[i]) if boxes.conf is not None else 0.0
        xy = boxes.xyxy[i].tolist()
        out.append(
            TrackedObject(
                track_id=int(tid),
                class_name=class_name,
                confidence=conf,
                x1=float(xy[0]) + ox,
                y1=float(xy[1]) + oy,
                x2=float(xy[2]) + ox,
                y2=float(xy[3]) + oy,
            )
        )
    return out


_DENSE_ID_BASE = 500_000


def dense_detect_on_model(
    model, img, *, layout: str = "scan", roi_rect: tuple[int, int, int, int] | None = None
) -> list[TrackedObject]:
    """Multi-window predict, then spatial cluster to one box per product.

    Custom weights trained on full-image bboxes (0.5 0.5 1 1) usually emit
    ONE class for the whole frame. Tiling gives each product a close-up,
    then :func:`merge_tiled_detections` collapses duplicate windows of the
    same bottle so a 3-item counter does not become 7 cart lines.

    ``roi_rect`` limits both the full-window pass and tiles to the pay zone.
    """
    import os

    h, w = img.shape[:2]
    conf = float(os.getenv("YOLO_CONF_THRESHOLD", "0.25"))
    # Overlay HUD: tile ghosts on bare wood often sit at 0.22–0.40. Scan
    # still uses a low floor so small noodle packs are not dropped early.
    if layout == "overlay":
        conf = max(conf, 0.40)
    else:
        conf = min(conf, 0.20)
    next_id = _DENSE_ID_BASE
    collected: list[TrackedObject] = []

    def _run_predict(source, ox: float = 0.0, oy: float = 0.0) -> None:
        nonlocal next_id
        results = model.predict(
            source=source,
            conf=conf,
            iou=0.50,
            max_det=30,
            agnostic_nms=False,
            verbose=False,
        )
        if not results:
            return
        boxes = _boxes_from_yolo_result(results[0], id_base=next_id, ox=ox, oy=oy)
        next_id += max(1, len(boxes))
        collected.extend(boxes)

    if roi_rect is not None:
        rx1, ry1, rx2, ry2 = roi_rect
        rx1, ry1 = max(0, rx1), max(0, ry1)
        rx2, ry2 = min(w, max(rx1 + 1, rx2)), min(h, max(ry1 + 1, ry2))
        crop = img[ry1:ry2, rx1:rx2]
        if crop.size:
            _run_predict(crop, float(rx1), float(ry1))
        for ox, oy, tw, th in dense_tile_origins(
            w, h, layout=layout, roi_rect=(rx1, ry1, rx2, ry2)
        ):
            tile = img[oy : oy + th, ox : ox + tw]
            if tile.size == 0:
                continue
            _run_predict(tile, float(ox), float(oy))
    else:
        _run_predict(img)
        for ox, oy, tw, th in dense_tile_origins(w, h, layout=layout):
            tile = img[oy : oy + th, ox : ox + tw]
            if tile.size == 0:
                continue
            _run_predict(tile, float(ox), float(oy))

    if layout != "overlay":
        try:
            from app.vision.region_proposal import propose_regions

            for r in propose_regions(img, max_regions=6):
                if any(
                    not (
                        r.x2 <= d.x1 or r.x1 >= d.x2 or r.y2 <= d.y1 or r.y1 >= d.y2
                    )
                    and ((min(d.x2, r.x2) - max(d.x1, r.x1)) * (min(d.y2, r.y2) - max(d.y1, r.y1)))
                    / max(1.0, (r.x2 - r.x1) * (r.y2 - r.y1))
                    > 0.45
                    for d in collected
                ):
                    continue
                crop = img[r.y1 : r.y2, r.x1 : r.x2]
                if crop.size == 0:
                    continue
                _run_predict(crop, float(r.x1), float(r.y1))
        except Exception:  # noqa: BLE001
            logger.debug("dense region proposals skipped", exc_info=True)

    merged = merge_tiled_detections(collected, w, h)
    if roi_rect is not None:
        from app.services.det_nms import drop_giant_scene_boxes

        rx1, ry1, rx2, ry2 = roi_rect
        merged = drop_giant_scene_boxes(
            merged,
            max(1, rx2 - rx1),
            max(1, ry2 - ry1),
            max_frac=0.55,
        )
    logger.warning(
        "DENSE DET: layout=%s roi=%s raw=%d final=%d classes=%s",
        layout,
        roi_rect,
        len(collected),
        len(merged),
        sorted({d.class_name for d in merged}),
    )
    return merged


def _dense_detect_products(model, img) -> list[TrackedObject]:
    return dense_detect_on_model(model, img, layout="scan")


def _merge_classical_proposals(
    frame_bgr, detections: list["TrackedObject"], camera_key: str
) -> list["TrackedObject"]:
    """Thêm vùng contour KHÔNG trùng detector vào danh sách detection.

    Chỉ lấp chỗ trống: đề xuất nào chồng đáng kể (IoU) lên một box YOLO thì
    bỏ, vì YOLO đã nhận vật đó rồi. Còn lại gán class 'region' để bộ phân
    loại SKU thử — chính nó, không phải contour, quyết định đây là gì.

    track_id suy từ vị trí tâm đã lượng tử hoá: cùng một vật đứng yên qua
    nhiều khung cho ra cùng id, nên hệ bỏ phiếu nhiều khung vẫn tích luỹ
    được cho vật do contour đề xuất, y như với vật do YOLO theo vết.
    """
    from app.vision.region_proposal import propose_regions

    try:
        regions = propose_regions(frame_bgr)
    except Exception:  # noqa: BLE001
        logger.exception("classical region proposal failed for %s", camera_key)
        return detections

    merged = list(detections)
    for r in regions:
        if any(_iou(d, r.x1, r.y1, r.x2, r.y2) > 0.3 for d in detections):
            continue
        cx, cy = (r.x1 + r.x2) // 2, (r.y1 + r.y2) // 2
        # Lượng tử 16px: vật xê dịch nhẹ giữa các khung vẫn cùng id.
        pseudo_id = _PROPOSAL_ID_BASE + (cy // 16) * 4096 + (cx // 16)
        merged.append(
            TrackedObject(
                track_id=int(pseudo_id),
                class_name="region",
                # KHÔNG dùng r.score (tỉ lệ diện tích) làm confidence — xem
                # chú thích _PROPOSAL_CONFIDENCE. Vùng to/nhỏ chênh nhau chút
                # đỉnh để giữ thứ tự ưu tiên, nhưng luôn vượt cổng detection.
                confidence=min(0.95, _PROPOSAL_CONFIDENCE + float(r.score)),
                x1=float(r.x1),
                y1=float(r.y1),
                x2=float(r.x2),
                y2=float(r.y2),
            )
        )
    return merged


def _get_pose_model():
    global _SHARED_POSE_MODEL
    if _SHARED_POSE_MODEL is None:
        from ultralytics import YOLO
        # Search in /models/ first, then fallbacks
        pose_path = "/models/yolov8n-pose.pt"
        if not os.path.exists(pose_path):
            pose_path = "models/yolov8n-pose.pt"
        if not os.path.exists(pose_path):
            pose_path = "yolov8n-pose.pt"
        _SHARED_POSE_MODEL = YOLO(pose_path)
        logger.info("YOLO Pose model loaded: %s", pose_path)
    return _SHARED_POSE_MODEL


def _resolve_det_path() -> str:
    """Which detection weight to load — same resolver as YoloDetector."""
    from app.services.model_path import resolve_detection_weight

    return resolve_detection_weight()


def _get_det_model():
    global _SHARED_DET_MODEL, _LOADED_DET_PATH
    want = _resolve_det_path()
    # Reload when the configured weight changed under us — the admin picked a
    # different model. Cheap: this only re-reads config (throttled) and
    # compares a string on the hot path; the YOLO() load happens only on an
    # actual change or first use.
    if _SHARED_DET_MODEL is not None and want != _LOADED_DET_PATH:
        logger.info("YOLO detection weight changed: %s -> %s", _LOADED_DET_PATH, want)
        _SHARED_DET_MODEL = None
        _TRACKERS.clear()
        _DET_TRACKER_STATE.clear()
    if _SHARED_DET_MODEL is None:
        from ultralytics import YOLO
        _SHARED_DET_MODEL = YOLO(want)
        _LOADED_DET_PATH = want
        logger.info("YOLO Detection model loaded: %s", want)
    return _SHARED_DET_MODEL


def _use_camera_tracker_custom(model, camera_key: str, tracker_state_dict: dict) -> None:
    predictor = getattr(model, "predictor", None)
    if predictor is None:
        return
    try:
        current = getattr(predictor, "trackers", None)
        if current is not None:
            tracker_state_dict[_ACTIVE_CAMERA.get("key_" + str(id(model)), camera_key)] = current
        saved = tracker_state_dict.get(camera_key)
        if saved is not None:
            predictor.trackers = saved
        elif current is not None:
            try:
                delattr(predictor, "trackers")
            except AttributeError:
                pass
    except Exception:
        logger.debug("tracker state swap unavailable", exc_info=True)
    finally:
        _ACTIVE_CAMERA["key_" + str(id(model))] = camera_key


def get_last_vision_result(camera_key: str) -> dict[str, Any] | None:
    """Optional read-back of the most recent frame's quality/timing/overlay
    info for this camera. Returns ``None`` if no frame has been processed
    yet, or (for individual keys) if the corresponding ``ENABLE_*`` flag
    was off for that frame."""
    return _LAST_VISION_RESULT.get(camera_key)


def _build_overlay_jpeg_base64(
    frame_bgr,
    *,
    camera_key: str,
    detections: list[TrackedObject],
    zones,
    quality,
    fps: float,
    total_ms: float,
    is_checkout_zone: bool,
) -> str | None:
    import cv2

    overlay_dets = [
        OverlayDetection(
            track_id=d.track_id,
            class_name=d.class_name,
            confidence=d.confidence,
            x1=d.x1,
            y1=d.y1,
            x2=d.x2,
            y2=d.y2,
            left_hand=d.left_hand,
            right_hand=d.right_hand,
        )
        for d in detections
    ]
    try:
        overlay_frame = draw_debug_overlay(
            frame_bgr,
            camera_name=camera_key,
            fps=fps,
            processing_time_ms=total_ms,
            quality=quality,
            zones=zones,
            detections=overlay_dets,
            is_checkout_zone=is_checkout_zone,
            trajectories=get_all_trajectories_xy(
                camera_key, frame_bgr.shape[1], frame_bgr.shape[0]
            ),
        )
        ok, buf = cv2.imencode(".jpg", overlay_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        return base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception:  # noqa: BLE001 — overlay is debug-only, must never break the pipeline
        logger.exception("debug overlay rendering failed for camera=%s", camera_key)
        return None


@dataclass(frozen=True)
class TrackingOutcome:
    """Everything one tracked frame produced.

    Exists because the SKU-classifier stage needs to crop from *the same*
    preprocessed frame YOLO saw. Reading that frame back from a per-camera
    global would race whenever two requests for one camera overlap (the
    second would overwrite the first's frame before it was used), and
    re-running preprocessing in the caller would pay the CLAHE/bilateral
    cost twice. Returning it keeps the frame in the caller's own scope.
    """

    detections: list[TrackedObject]
    frame_bgr: Any        # post ROI/enhancement — exactly what YOLO received
    opencv_ms: float
    yolo_bytetrack_ms: float
    raw_frame: Any = None


async def track_frame(
    image_bytes: bytes,
    camera_key: str,
    *,
    is_checkout_zone: bool = False,
    roi_zones: list | None = None,
    dense_detect: bool = False,
) -> list[TrackedObject]:
    """Unchanged contract — see module docstring. Delegates to
    :func:`track_frame_detailed` so both paths share one implementation."""
    outcome = await track_frame_detailed(
        image_bytes,
        camera_key,
        is_checkout_zone=is_checkout_zone,
        roi_zones=roi_zones,
        dense_detect=dense_detect,
    )
    return outcome.detections


async def track_frame_detailed(
    image_bytes: bytes,
    camera_key: str,
    *,
    is_checkout_zone: bool = False,
    roi_zones: list | None = None,
    dense_detect: bool = False,
) -> TrackingOutcome:
    cfg = get_vision_config()

    # Decode + optional ROI/enhancement/quality — see app/vision/pipeline.py.
    # Raises ValueError on bad input, same as the PIL decode this replaces.
    vision_result = preprocess_for_detection(
        image_bytes, camera_key, cfg, roi_zones=roi_zones
    )
    frame_bgr = vision_result.frame

    async with _LOCK:
        model_pose = _get_pose_model()
        model_det = _get_det_model()

    loop = asyncio.get_event_loop()

    def _run() -> list[TrackedObject]:
        # Pose stays on the full frame (people stand *beside* the pay zone).
        # Products run on the ROI-masked frame so a statue/plant outside
        # "Vùng Thanh Toán" cannot become a cart line.
        img = vision_result.raw_frame if vision_result.raw_frame is not None else frame_bgr
        det_img = frame_bgr if vision_result.zones else img
        roi_rect = None
        if vision_result.zones:
            from app.vision.roi import zone_union_bbox
            fh, fw = det_img.shape[:2]
            roi_rect = zone_union_bbox(vision_result.zones, fw, fh)
        
        if camera_key not in _REID_MANAGERS:
            _REID_MANAGERS[camera_key] = ReIDManager(similarity_threshold=0.72)
        reid_manager = _REID_MANAGERS[camera_key]

        # 1. Run pose estimation tracking on persons
        pose_results = model_pose.track(
            source=img,
            persist=True,
            tracker="bytetrack.yaml",
            classes=[0],
            verbose=False,
        )
        out: list[TrackedObject] = []
        keypoints_xy = []
        if pose_results:
            first_pose = pose_results[0]
            names_pose = first_pose.names or {}
            if first_pose.boxes is not None and first_pose.boxes.id is not None:
                boxes = first_pose.boxes
                ids = boxes.id.int().cpu().tolist()
                if first_pose.keypoints is not None and first_pose.keypoints.xy is not None:
                    keypoints_xy = first_pose.keypoints.xy.cpu().numpy()
                
                for i, tid in enumerate(ids):
                    cls_idx = int(boxes.cls[i]) if boxes.cls is not None else 0
                    class_name = names_pose.get(cls_idx, "person")
                    conf = float(boxes.conf[i]) if boxes.conf is not None else 0.0
                    xy = boxes.xyxy[i].tolist()
                    
                    mapped_tid = reid_manager.get_mapped_id(tid, img, xy)

                    left_hand = None
                    right_hand = None
                    if i < len(keypoints_xy):
                        kpts = keypoints_xy[i]
                        if len(kpts) > 10:
                            lw = kpts[9]
                            rw = kpts[10]
                            if lw[0] != 0 or lw[1] != 0:
                                left_hand = (float(lw[0]), float(lw[1]))
                            if rw[0] != 0 or rw[1] != 0:
                                right_hand = (float(rw[0]), float(rw[1]))
                                
                    out.append(
                        TrackedObject(
                            track_id=int(mapped_tid),
                            class_name=str(class_name),
                            confidence=conf,
                            x1=float(xy[0]),
                            y1=float(xy[1]),
                            x2=float(xy[2]),
                            y2=float(xy[3]),
                            left_hand=left_hand,
                            right_hand=right_hand,
                        )
                    )
                
                import time
                now_ts = time.time()
                frame_h, frame_w = img.shape[:2]
                latest_boxes = []
                for obj in out:
                    if obj.class_name == "person":
                        latest_boxes.append({
                            "mapped_id": obj.track_id,
                            "bbox": [obj.x1, obj.y1, obj.x2, obj.y2],
                            "timestamp": now_ts
                        })
                        record_person_position(
                            camera_key, obj.track_id, obj.cx, obj.cy, now_ts,
                            frame_w, frame_h,
                        )
                _LATEST_PERSON_BOXES[camera_key] = latest_boxes

        # 2. Products: one-shot scan uses tiled predict (custom full-frame
        # weights only see one class otherwise). Live path keeps ByteTrack
        # but still accepts boxes that have no track id yet.
        if dense_detect:
            out.extend(
                dense_detect_on_model(model_det, det_img, layout="scan", roi_rect=roi_rect)
            )
        else:
            det_results = model_det.track(
                source=det_img,
                persist=True,
                tracker="bytetrack.yaml",
                verbose=False,
            )
            if det_results:
                out.extend(_boxes_from_yolo_result(det_results[0], id_base=1))
        return out

    yolo_timer = StageTimer()
    async with _MODEL_LOCK:
        _use_camera_tracker_custom(model_pose, camera_key, _POSE_TRACKER_STATE)
        _use_camera_tracker_custom(model_det, camera_key, _DET_TRACKER_STATE)
        with yolo_timer:
            detections = await loop.run_in_executor(None, _run)

    # Lấp chỗ detector COCO bỏ sót bằng đề xuất vùng contour — chủ yếu là
    # gói mì mà yolov8n không có lớp nào để nhận. Chỉ chạy khi camera đã vẽ
    # ROI (vision_result.zones khác rỗng): ngoài ROI cách cổ điển sinh rác.
    if cfg.enable_classical_proposals and vision_result.zones:
        detections = _merge_classical_proposals(
            frame_bgr, detections, camera_key
        )

    if vision_result.zones:
        from app.vision.roi import box_mostly_in_zones, point_in_zones
        fh, fw = frame_bgr.shape[:2]
        detections = [
            d for d in detections
            if str(getattr(d, "class_name", "")).lower() == "person"
            or (
                point_in_zones(vision_result.zones, d.cx, d.cy, fw, fh)
                and box_mostly_in_zones(
                    vision_result.zones, d.x1, d.y1, d.x2, d.y2, fw, fh, min_frac=0.62
                )
            )
        ]

    fh, fw = frame_bgr.shape[:2]
    frame_area = float(max(1, fw) * max(1, fh))
    detections = [
        d for d in detections
        if str(getattr(d, "class_name", "")).lower() == "person"
        or ((d.x2 - d.x1) * (d.y2 - d.y1) / frame_area) < 0.35
    ]

    record_pipeline_timing(
        camera_key,
        opencv_ms=vision_result.opencv_ms,
        yolo_bytetrack_ms=yolo_timer.elapsed_ms,
        cfg=cfg,
    )

    from app.vision.metrics.timers import MetricsRegistry

    stats = MetricsRegistry.get(camera_key)
    overlay_b64 = None
    if cfg.enable_debug_overlay:
        overlay_b64 = _build_overlay_jpeg_base64(
            frame_bgr,
            camera_key=camera_key,
            detections=detections,
            zones=vision_result.zones,
            quality=vision_result.quality,
            fps=stats.fps if stats else 0.0,
            total_ms=stats.last_total_ms if stats else 0.0,
            is_checkout_zone=is_checkout_zone,
        )

    _LAST_VISION_RESULT[camera_key] = {
        "opencv_ms": vision_result.opencv_ms,
        "yolo_bytetrack_ms": yolo_timer.elapsed_ms,
        "total_ms": (stats.last_total_ms if stats else None),
        "fps": (stats.fps if stats else None),
        "dropped_count": (stats.dropped_count if stats else 0),
        "zones": [z.name for z in vision_result.zones],
        "quality": (
            {
                "brightness": vision_result.quality.brightness,
                "contrast": vision_result.quality.contrast,
                "blur_score": vision_result.quality.blur_score,
                "quality_score": vision_result.quality.quality_score,
                "is_low_quality": vision_result.quality.is_low_quality,
                "reason": vision_result.quality.reason,
            }
            if vision_result.quality
            else None
        ),
        "debug_overlay_jpeg_base64": overlay_b64,
    }

    return TrackingOutcome(
        detections=detections,
        frame_bgr=frame_bgr,
        opencv_ms=vision_result.opencv_ms,
        yolo_bytetrack_ms=yolo_timer.elapsed_ms,
        raw_frame=vision_result.raw_frame,
    )
