"""Module 5 — performance metrics.

`StageTimer` measures one pipeline stage (OpenCV preprocessing, or the
combined YOLO+ByteTrack call — see `timers.py` docstring for why those two
aren't split further). `CameraMetricsRegistry` keeps a small in-process,
per-camera rolling snapshot (FPS, dropped frames, last stage timings) that
callers can read back without re-computing anything, and that
`app.metrics` (Prometheus) is fed from when `ENABLE_PERFORMANCE_METRICS`
is on.
"""

from __future__ import annotations

from app.vision.metrics.timers import CameraStats, MetricsRegistry, StageTimer

__all__ = ["CameraStats", "MetricsRegistry", "StageTimer"]
