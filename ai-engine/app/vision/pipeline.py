"""Orchestrates the vision/ modules into the two insertion points identified
in the Sprint 1 review:

  1. `preprocess_for_detection()` — decode + ROI + enhancement + quality,
     called right before `model.track()` / `model.predict()`. Returns the
     ndarray to feed YOLO plus whatever metadata was computed.
  2. `record_pipeline_timing()` — called by the caller after the YOLO/
     ByteTrack call, since that timing can only be measured by whoever
     actually makes that call (this module doesn't call ultralytics).
  3. `build_debug_overlay_jpeg()` — optional, only when explicitly
     requested (see `app/api/frame.py`'s `debug_overlay` form field).

Important compatibility note: `model.track(source=<ndarray>, ...)` (this
project already calls this for both raw-bytes-as-PIL-image *and* would
accept a numpy array) treats a raw numpy ndarray as **BGR** — the same
convention `cv2.imdecode` produces. The pre-Sprint code passed a PIL Image
(which ultralytics reads as RGB) instead. Both are "correct" *as long as
you don't mix them* — this module always hands ultralytics a BGR ndarray
and never converts it to RGB, so YOLO sees a consistently-BGR frame end to
end. (Converting to RGB here would silently swap the R/B channels from
YOLO's point of view and degrade detection accuracy without any error.)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.vision.config import VisionConfig, get_vision_config
from app.vision.enhancement.enhance import enhance_frame
from app.vision.metrics.timers import MetricsRegistry, StageTimer
from app.vision.preprocessing.decode import decode_image_bytes
from app.vision.quality.analyzer import FrameQuality, analyze_quality
from app.vision.roi.zones import RoiZone, apply_roi, load_roi_config
from app.vision.trace import PipelineTrace, TraceRecorder, should_trace


@dataclass(frozen=True)
class PipelineResult:
    frame: np.ndarray               # post ROI + enhancement — this is what YOLO sees
    raw_frame: np.ndarray           # decoded frame, before ROI/enhancement
    zones: list[RoiZone]
    quality: FrameQuality | None
    opencv_ms: float
    camera_key: str
    trace: PipelineTrace | None = None  # populated only when tracing is on


def preprocess_for_detection(
    image_bytes: bytes,
    camera_key: str,
    cfg: VisionConfig | None = None,
    *,
    force_trace: bool = False,
    roi_zones: list | None = None,
) -> PipelineResult:
    """Decode + (optional) ROI + (optional) enhancement + (optional)
    quality analysis. With every ``ENABLE_*`` flag off (the default), this
    is exactly "decode the image" — the same outcome as the old
    ``PIL.Image.open(...).convert("RGB")`` call it replaces, just producing
    a BGR ndarray instead of a PIL RGB image (see module docstring for why
    that's safe for the ultralytics call that follows).
    """
    cfg = cfg or get_vision_config()
    recorder = TraceRecorder(camera_key, should_trace(cfg, force=force_trace))
    timer = StageTimer()
    with timer:
        frame = decode_image_bytes(image_bytes)
        raw_frame = frame
        recorder.capture("decode", "Decoded frame (input)", frame)

        # Vùng vẽ trên Admin luôn được áp dụng (kể cả khi ENABLE_ROI tắt):
        # đó là ranh giới nghiệp vụ "chỉ nhận diện trong vùng thanh toán".
        # YAML + ENABLE_ROI vẫn là đường dự phòng cho camera chưa vẽ vùng.
        zones: list[RoiZone] = list(roi_zones or [])
        if cfg.enable_roi and not zones:
            zones = load_roi_config(cfg.roi_config_path, camera_key)
        if zones:
            frame = apply_roi(frame, zones)
            recorder.capture("roi", "ROI mask", frame, {"zones": len(zones)})

        if cfg.any_enhancement_enabled:
            frame = enhance_frame(frame, cfg, recorder=recorder)

        quality: FrameQuality | None = None
        if cfg.enable_image_quality or cfg.enable_blur_analysis:
            quality = analyze_quality(frame, cfg)

        # Final snapshot is what YOLO actually receives — the answer to
        # "what did the model see?", which is the whole point of the view.
        recorder.capture("final", "Final frame (sent to YOLO)", frame)

    return PipelineResult(
        frame=frame,
        raw_frame=raw_frame,
        zones=zones,
        quality=quality,
        opencv_ms=timer.elapsed_ms,
        camera_key=camera_key,
        trace=recorder.trace,
    )


def record_pipeline_timing(
    camera_key: str,
    *,
    opencv_ms: float,
    yolo_bytetrack_ms: float,
    cfg: VisionConfig | None = None,
) -> None:
    """Always updates the cheap in-process `MetricsRegistry` (a couple of
    dict/float operations — negligible next to a YOLO forward pass), but
    only pushes to Prometheus when `ENABLE_PERFORMANCE_METRICS` is on,
    since that involves label-matching + the exporter's own bookkeeping
    and isn't free at high frame rates / camera counts.
    """
    MetricsRegistry.record_frame(
        camera_key, opencv_ms=opencv_ms, yolo_bytetrack_ms=yolo_bytetrack_ms
    )
    cfg = cfg or get_vision_config()
    if not cfg.enable_performance_metrics:
        return
    from app.metrics import (
        VISION_CAMERA_FPS,
        VISION_OPENCV_SECONDS,
        VISION_PIPELINE_TOTAL_SECONDS,
        VISION_YOLO_BYTETRACK_SECONDS,
    )

    VISION_OPENCV_SECONDS.labels(camera_key=camera_key).observe(opencv_ms / 1000.0)
    VISION_YOLO_BYTETRACK_SECONDS.labels(camera_key=camera_key).observe(
        yolo_bytetrack_ms / 1000.0
    )
    VISION_PIPELINE_TOTAL_SECONDS.labels(camera_key=camera_key).observe(
        (opencv_ms + yolo_bytetrack_ms) / 1000.0
    )
    stats = MetricsRegistry.get(camera_key)
    if stats is not None:
        VISION_CAMERA_FPS.labels(camera_key=camera_key).set(stats.fps)


def record_dropped_frame(camera_key: str, cfg: VisionConfig | None = None) -> None:
    MetricsRegistry.record_dropped(camera_key)
    cfg = cfg or get_vision_config()
    if not cfg.enable_performance_metrics:
        return
    from app.metrics import VISION_DROPPED_FRAMES_TOTAL

    VISION_DROPPED_FRAMES_TOTAL.labels(camera_key=camera_key).inc()
