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

# Per-camera snapshot of the most recent frame's vision metadata (quality,
# ROI zones, timings, optional debug-overlay JPEG). Additive/optional —
# nothing reads this unless it explicitly asks via `get_last_vision_result`.
_LAST_VISION_RESULT: dict[str, dict[str, Any]] = {}


def reset_trackers() -> None:
    """Clear the per-camera tracker cache so YOLO_MODEL changes take effect."""
    _TRACKERS.clear()


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


def _get_model(camera_key: str):
    from ultralytics import YOLO

    if camera_key in _TRACKERS:
        return _TRACKERS[camera_key]
    weights = os.getenv("YOLO_MODEL", "yolov8n.pt")
    model = YOLO(weights)
    _TRACKERS[camera_key] = model
    return model


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


async def track_frame(
    image_bytes: bytes,
    camera_key: str,
    *,
    is_checkout_zone: bool = False,
) -> list[TrackedObject]:
    cfg = get_vision_config()

    # Decode + optional ROI/enhancement/quality — see app/vision/pipeline.py.
    # Raises ValueError on bad input, same as the PIL decode this replaces.
    vision_result = preprocess_for_detection(image_bytes, camera_key, cfg)
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
    with yolo_timer:
        detections = await loop.run_in_executor(None, _run)

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

    return detections
