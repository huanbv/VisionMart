"""Per-stage pipeline tracing — captures a snapshot after every
preprocessing step so the admin UI can show the full chain
(decode → ROI → enhancement steps → final → what YOLO saw) instead of
only the end result.

Design constraints this follows:

* **Off by default.** Tracing encodes and stores several JPEGs per traced
  frame; that is far more expensive than the preprocessing itself, so it
  must never run on the hot path unless explicitly requested. Gated by
  ``ENABLE_PIPELINE_TRACE`` plus an explicit per-call opt-in.
* **Sampled, not every frame.** Even when enabled, ``TRACE_SAMPLE_RATE``
  keeps this to a fraction of frames so a busy camera doesn't fill object
  storage. A rate of 0 means "only when the caller explicitly asks",
  which is what the admin "trace this frame now" button uses.
* **Never breaks the pipeline.** Any failure while encoding or uploading a
  trace is logged and swallowed — a debugging aid must not take down
  frame processing.

The trace records the *metrics after each stage* as well as the image, so
the admin view can show brightness/contrast/blur moving step by step and
answer "which stage actually changed the frame" rather than just showing
pictures.
"""

from __future__ import annotations

import logging
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger("ai-engine.vision.trace")


@dataclass
class StageSnapshot:
    """One preprocessing stage: what ran, what it produced, what it cost."""

    order: int
    stage: str                       # "decode" | "roi" | "auto_gamma" | ...
    label: str                       # human-readable, shown in the admin UI
    params: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    image_key: str | None = None     # object-storage key, filled on flush
    _image: np.ndarray | None = None  # kept in memory until flush


@dataclass
class PipelineTrace:
    trace_id: str
    camera_key: str
    started_at: float
    stages: list[StageSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialisable form for the API — drops the in-memory ndarrays."""
        return {
            "trace_id": self.trace_id,
            "camera_key": self.camera_key,
            "started_at": self.started_at,
            "stages": [
                {k: v for k, v in asdict(s).items() if k != "_image"}
                for s in self.stages
            ],
        }


def _quick_metrics(frame_bgr: np.ndarray) -> dict[str, float]:
    """Cheap per-stage measurements. Deliberately a subset of
    `quality/analyzer.py` (no noise estimate — that runs a median blur,
    too costly to repeat after every stage)."""
    import cv2

    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return {
        "brightness": round(float(gray.mean()), 2),
        "contrast": round(float(gray.std()), 2),
        "blur_score": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
    }


class TraceRecorder:
    """Collects stage snapshots for a single frame.

    Used as a no-op when tracing is disabled, so `pipeline.py` can call
    `recorder.capture(...)` unconditionally without branching everywhere.
    """

    def __init__(self, camera_key: str, enabled: bool) -> None:
        self.enabled = enabled
        self.trace: PipelineTrace | None = None
        if enabled:
            self.trace = PipelineTrace(
                trace_id=uuid.uuid4().hex,
                camera_key=camera_key,
                started_at=time.time(),
            )
        self._t0 = time.perf_counter()

    def capture(
        self,
        stage: str,
        label: str,
        frame_bgr: np.ndarray,
        params: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or self.trace is None:
            return
        now = time.perf_counter()
        try:
            snap = StageSnapshot(
                order=len(self.trace.stages),
                stage=stage,
                label=label,
                params=params or {},
                metrics=_quick_metrics(frame_bgr),
                elapsed_ms=round((now - self._t0) * 1000.0, 2),
                _image=frame_bgr.copy(),
            )
            self.trace.stages.append(snap)
        except Exception:  # never break the pipeline for a debug aid
            logger.exception("trace capture failed at stage=%s", stage)
        self._t0 = now


def should_trace(cfg, force: bool = False) -> bool:
    """Decide whether this frame gets traced.

    ``force=True`` is the admin "trace this frame" path and bypasses the
    sample rate (but still respects the master ``ENABLE_PIPELINE_TRACE``
    switch, so tracing can be turned off globally in production).
    """
    if not getattr(cfg, "enable_pipeline_trace", False):
        return False
    if force:
        return True
    rate = getattr(cfg, "trace_sample_rate", 0.0)
    return rate > 0 and random.random() < rate


def flush_trace(trace: PipelineTrace, storage_module: Any = None) -> dict[str, Any]:
    """Encode each stage image to JPEG and upload it, returning the
    serialisable trace with ``image_key`` populated.

    ``storage_module`` is injected so tests can pass a fake; production
    passes ``app.services.object_storage``. If upload fails for a stage,
    that stage keeps ``image_key=None`` and the rest still succeed — a
    partial trace is more useful than none.
    """
    import cv2

    if storage_module is None:
        from app.services import object_storage as storage_module  # type: ignore

    for snap in trace.stages:
        if snap._image is None:
            continue
        key = f"traces/{trace.camera_key}/{trace.trace_id}/{snap.order:02d}_{snap.stage}.jpg"
        try:
            ok, buf = cv2.imencode(".jpg", snap._image, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                logger.warning("trace: imencode failed for stage=%s", snap.stage)
                continue
            storage_module.put_bytes(key, buf.tobytes(), content_type="image/jpeg")
            snap.image_key = key
        except Exception:
            logger.exception("trace: upload failed for stage=%s", snap.stage)
        finally:
            snap._image = None  # release memory regardless of outcome

    return trace.to_dict()
