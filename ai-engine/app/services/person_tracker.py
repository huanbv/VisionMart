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
import logging
import os
from dataclasses import dataclass
from typing import Any

from app.vision.config import get_vision_config
from app.vision.metrics.timers import StageTimer
from app.vision.overlay.debug_overlay import OverlayDetection, draw_debug_overlay
from app.vision.pipeline import preprocess_for_detection, record_pipeline_timing

logger = logging.getLogger("ai-engine.person_tracker")

_TRACKERS: dict[str, Any] = {}
_LOCK = asyncio.Lock()

# Shared-weights mode (SHARE_YOLO_WEIGHTS, the default): one model object
# for the whole process instead of one per camera. See `_get_model`.
_SHARED_MODEL: Any = None
_SHARED_WEIGHTS: str | None = None
# ByteTrack state stays per-camera even when the weights are shared —
# sharing tracker state would merge two shoppers into one cart.
_TRACKER_STATE: dict[str, Any] = {}
_ACTIVE_CAMERA: dict[str, str] = {}
# Serialises inference when one model serves many cameras: the tracker-state
# swap plus the forward pass must not interleave between cameras.
_MODEL_LOCK = asyncio.Lock()

# Per-camera snapshot of the most recent frame's vision metadata (quality,
# ROI zones, timings, optional debug-overlay JPEG). Additive/optional —
# nothing reads this unless it explicitly asks via `get_last_vision_result`.
_LAST_VISION_RESULT: dict[str, dict[str, Any]] = {}


def reset_trackers() -> None:
    """Clear cached models so a YOLO_MODEL change takes effect.

    Clears the shared model too — after a retrained weight is deployed the
    process must pick it up, and leaving the old object cached would keep
    serving the previous model until the next restart.
    """
    global _SHARED_MODEL, _SHARED_WEIGHTS
    _TRACKERS.clear()
    _TRACKER_STATE.clear()
    _ACTIVE_CAMERA.clear()
    _SHARED_MODEL = None
    _SHARED_WEIGHTS = None


@dataclass(frozen=True)
class TrackedObject:
    track_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0


# Track-id của đề xuất contour bắt đầu từ đây, tách hẳn khỏi id của
# ByteTrack (đếm từ 1 lên) để hai bên không bao giờ đè id lên nhau.
_PROPOSAL_ID_BASE = 1_000_000


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
                confidence=float(r.score),
                x1=float(r.x1),
                y1=float(r.y1),
                x2=float(r.x2),
                y2=float(r.y2),
            )
        )
    return merged


def _get_model(camera_key: str):
    """Return the YOLO model this camera should use.

    Two modes, selected by ``SHARE_YOLO_WEIGHTS``:

    **Shared (default).** One ``YOLO`` object for the whole process. The
    weights are identical for every camera — the same ``YOLO_MODEL`` file
    was being loaded N times — so N copies bought nothing but memory:
    roughly 6 MB of parameters plus ~150-250 MB of resident CUDA/inference
    context *per camera*. At 8 cameras that is over a gigabyte of duplicate
    state, and it is the main reason RAM scaled with camera count.

    Tracker state stays per-camera regardless of this setting. ultralytics
    keeps ByteTrack state on the *model object*, keyed by nothing — so a
    naively shared model would let two cameras' tracks overwrite each
    other's ids, merging two different shoppers into one cart. The shared
    path therefore serialises calls through ``_MODEL_LOCK`` and swaps the
    per-camera tracker state in around each call (see
    ``_use_camera_tracker``).

    **Per-camera.** The previous behaviour, kept behind the flag: it
    genuinely parallelises better on a multi-GPU box, where the memory is
    available and the lock would be the bottleneck instead.
    """
    from ultralytics import YOLO

    cfg = get_vision_config()
    weights = os.getenv("YOLO_MODEL", "yolov8n.pt")

    if not getattr(cfg, "share_yolo_weights", True):
        if camera_key in _TRACKERS:
            return _TRACKERS[camera_key]
        model = YOLO(weights)
        _TRACKERS[camera_key] = model
        logger.info("YOLO loaded for camera=%s (per-camera mode)", camera_key)
        return model

    global _SHARED_MODEL, _SHARED_WEIGHTS
    if _SHARED_MODEL is None or _SHARED_WEIGHTS != weights:
        _SHARED_MODEL = YOLO(weights)
        _SHARED_WEIGHTS = weights
        logger.info("YOLO loaded once, shared across all cameras: %s", weights)
    return _SHARED_MODEL


def _use_camera_tracker(model, camera_key: str) -> None:
    """Swap in this camera's ByteTrack state before a shared-model call.

    ultralytics stores the active trackers on ``model.predictor.trackers``.
    When one model serves several cameras, that list must be exchanged per
    call or track ids from different cameras collide — and a collision here
    is not cosmetic: ``frame.py`` derives the cart session id from the
    track id, so two shoppers would share one cart.

    Best-effort by design: if ultralytics changes where it keeps this (it
    is not public API), the swap silently does nothing and tracking
    degrades to what a single shared tracker gives — still correct
    detections, just less stable ids. That is an acceptable failure; raising
    here would take the camera offline over an internal-attribute rename.
    """
    predictor = getattr(model, "predictor", None)
    if predictor is None:
        return  # first call for this model — nothing to preserve yet
    try:
        current = getattr(predictor, "trackers", None)
        if current is not None:
            _TRACKER_STATE[_ACTIVE_CAMERA.get("key", camera_key)] = current
        saved = _TRACKER_STATE.get(camera_key)
        if saved is not None:
            predictor.trackers = saved
        elif current is not None:
            # Camera mới trên model đã ấm: XOÁ thuộc tính, tuyệt đối không
            # gán None. ultralytics khởi tạo tracker trong on_predict_start
            # bằng đúng một điều kiện:
            #
            #     if hasattr(predictor, "trackers") and persist: return
            #
            # nghĩa là chỉ cần thuộc tính TỒN TẠI (kể cả None) là nó bỏ qua
            # khởi tạo, rồi bước postprocess truy cập trackers[i] và nổ
            # "TypeError: 'NoneType' object is not subscriptable" — đánh sập
            # cả /ai/frame cho camera đó vĩnh viễn, trong khi camera có
            # trạng thái cũ vẫn chạy (đúng kiểu lỗi 200/500 xen kẽ đã gặp
            # trên VPS khi hai camera thay phiên trên một model dùng chung).
            # delattr khiến hasattr trả False và ultralytics tự tạo tracker
            # mới sạch cho camera này.
            try:
                delattr(predictor, "trackers")
            except AttributeError:
                pass
    except Exception:  # noqa: BLE001 — see docstring
        logger.debug("tracker state swap unavailable", exc_info=True)
    finally:
        _ACTIVE_CAMERA["key"] = camera_key


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


async def track_frame(
    image_bytes: bytes,
    camera_key: str,
    *,
    is_checkout_zone: bool = False,
    roi_zones: list | None = None,
) -> list[TrackedObject]:
    """Unchanged contract — see module docstring. Delegates to
    :func:`track_frame_detailed` so both paths share one implementation."""
    outcome = await track_frame_detailed(
        image_bytes,
        camera_key,
        is_checkout_zone=is_checkout_zone,
        roi_zones=roi_zones,
    )
    return outcome.detections


async def track_frame_detailed(
    image_bytes: bytes,
    camera_key: str,
    *,
    is_checkout_zone: bool = False,
    roi_zones: list | None = None,
) -> TrackingOutcome:
    cfg = get_vision_config()

    # Decode + optional ROI/enhancement/quality — see app/vision/pipeline.py.
    # Raises ValueError on bad input, same as the PIL decode this replaces.
    vision_result = preprocess_for_detection(
        image_bytes, camera_key, cfg, roi_zones=roi_zones
    )
    frame_bgr = vision_result.frame

    async with _LOCK:
        model = _get_model(camera_key)

    loop = asyncio.get_event_loop()

    def _run() -> list[TrackedObject]:
        # ultralytics treats a raw ndarray as BGR (OpenCV's native order) —
        # do NOT convert to RGB here, see app/vision/pipeline.py docstring.
        results = model.track(
            source=frame_bgr,
            persist=True,
            tracker="bytetrack.yaml",
            verbose=False,
        )
        out: list[TrackedObject] = []
        if not results:
            return out
        first = results[0]
        names = first.names or {}
        if first.boxes is None:
            return out
        for box in first.boxes:
            tid = box.id
            if tid is None:
                continue
            cls_idx = int(box.cls[0]) if box.cls is not None else -1
            class_name = names.get(cls_idx, str(cls_idx))
            conf = float(box.conf[0]) if box.conf is not None else 0.0
            xy = box.xyxy[0].tolist()
            out.append(
                TrackedObject(
                    track_id=int(tid[0]),
                    class_name=str(class_name),
                    confidence=conf,
                    x1=float(xy[0]),
                    y1=float(xy[1]),
                    x2=float(xy[2]),
                    y2=float(xy[3]),
                )
            )
        return out

    yolo_timer = StageTimer()
    if getattr(cfg, "share_yolo_weights", True):
        # One model object serves every camera, so the tracker-state swap
        # and the forward pass must be atomic with respect to other
        # cameras — otherwise camera B's swap lands between camera A's swap
        # and its inference, and A tracks with B's state.
        async with _MODEL_LOCK:
            _use_camera_tracker(model, camera_key)
            with yolo_timer:
                detections = await loop.run_in_executor(None, _run)
    else:
        with yolo_timer:
            detections = await loop.run_in_executor(None, _run)

    # Lấp chỗ detector COCO bỏ sót bằng đề xuất vùng contour — chủ yếu là
    # gói mì mà yolov8n không có lớp nào để nhận. Chỉ chạy khi camera đã vẽ
    # ROI (vision_result.zones khác rỗng): ngoài ROI cách cổ điển sinh rác.
    if cfg.enable_classical_proposals and vision_result.zones:
        detections = _merge_classical_proposals(
            frame_bgr, detections, camera_key
        )

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
    )
