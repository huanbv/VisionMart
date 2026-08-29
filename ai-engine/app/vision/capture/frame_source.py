"""Instruments the existing `_grab_frame` (cv2.VideoCapture-based) RTSP/video
grab with FPS and dropped-frame bookkeeping.

Honesty note on "FPS" here: `_grab_frame` opens a fresh `cv2.VideoCapture`,
reads exactly one frame, and releases it — it is called periodically (by
`frame_pipeline.py`'s Celery beat tick, or `rtsp_capture.py`'s alert scan),
not in a tight continuous-read loop. So "FPS" for this module means *how
often a frame was successfully grabbed for this camera* (1 / time-since-
last-successful-grab), which is the honest measurement available at this
call site — not the video source's native frame rate. This is documented
explicitly in the Sprint report rather than presented as true stream FPS.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from app.vision.metrics.timers import MetricsRegistry, StageTimer

logger = logging.getLogger("ai-engine.vision.capture")

_CAPTURE_KEY_PREFIX = "capture:"


@dataclass(frozen=True)
class CaptureOutcome:
    frame: np.ndarray | None
    success: bool
    error: str | None
    capture_ms: float
    timestamp: float
    fps: float
    dropped_count: int


def instrumented_capture(
    grab_fn: Callable[[], np.ndarray], camera_key: str
) -> CaptureOutcome:
    """Runs ``grab_fn`` (typically ``lambda: _grab_frame(url, timeout_ms)``)
    and records the outcome. Never raises — capture failures are reported
    via ``CaptureOutcome.success=False`` so callers keep their existing
    try/except-and-return-502 behaviour unchanged; this function only adds
    bookkeeping around it, it doesn't change error handling semantics.
    """
    stats_key = f"{_CAPTURE_KEY_PREFIX}{camera_key}"
    timer = StageTimer()
    try:
        with timer:
            frame = grab_fn()
        stats = MetricsRegistry.record_frame(
            stats_key, opencv_ms=timer.elapsed_ms, yolo_bytetrack_ms=0.0
        )
        return CaptureOutcome(
            frame=frame,
            success=True,
            error=None,
            capture_ms=timer.elapsed_ms,
            timestamp=time.time(),
            fps=stats.fps,
            dropped_count=stats.dropped_count,
        )
    except Exception as exc:  # noqa: BLE001
        MetricsRegistry.record_dropped(stats_key)
        stats = MetricsRegistry.get(stats_key)
        logger.warning("frame capture failed for camera=%s: %s", camera_key, exc)
        return CaptureOutcome(
            frame=None,
            success=False,
            error=str(exc),
            capture_ms=timer.elapsed_ms,
            timestamp=time.time(),
            fps=stats.fps if stats else 0.0,
            dropped_count=stats.dropped_count if stats else 1,
        )
