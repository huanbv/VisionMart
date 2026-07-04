"""Stage timing + per-camera FPS/dropped-frame bookkeeping.

Honesty note on what "YOLO time" vs "ByteTrack time" means here:
`person_tracker.py` calls `model.track(...)`, which is a single ultralytics
call that runs detection AND tracking internally — there is no supported,
non-invasive way to split that one call's wall-clock time between "YOLO
inference" and "ByteTrack association" without patching ultralytics
internals, which would be exactly the kind of invasive change this Sprint
is not supposed to make. This module therefore measures it as one combined
``yolo_bytetrack_ms`` stage rather than reporting a fabricated split. If a
true breakdown is ever needed, Sprint 2 could call `model.predict()` and a
standalone ByteTrack association step separately — a real architecture
change, out of scope here.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


class StageTimer:
    """``with StageTimer() as t: ...`` then read ``t.elapsed_ms``."""

    def __init__(self) -> None:
        self._start = 0.0
        self.elapsed_ms = 0.0

    def __enter__(self) -> "StageTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000.0


@dataclass
class CameraStats:
    camera_key: str
    frame_count: int = 0
    dropped_count: int = 0
    last_frame_ts: float | None = None
    fps: float = 0.0
    last_opencv_ms: float = 0.0
    last_yolo_bytetrack_ms: float = 0.0
    last_total_ms: float = 0.0

    def as_dict(self) -> dict:
        return {
            "camera_key": self.camera_key,
            "frame_count": self.frame_count,
            "dropped_count": self.dropped_count,
            "fps": round(self.fps, 2),
            "opencv_ms": round(self.last_opencv_ms, 2),
            "yolo_bytetrack_ms": round(self.last_yolo_bytetrack_ms, 2),
            "total_ms": round(self.last_total_ms, 2),
        }


class MetricsRegistry:
    """Process-local, per-camera stats. Not shared across ai-engine worker
    processes/replicas — fine for a single-instance graduation-thesis
    deployment; a multi-replica production deployment would need to
    aggregate this externally (e.g. from the Prometheus metrics this
    module also feeds, via `app/metrics.py`), which Sprint 2 can revisit
    if the deployment ever scales beyond one ai-engine process."""

    _lock = threading.Lock()
    _stats: dict[str, CameraStats] = {}

    @classmethod
    def record_frame(
        cls,
        camera_key: str,
        *,
        opencv_ms: float,
        yolo_bytetrack_ms: float,
    ) -> CameraStats:
        now = time.time()
        with cls._lock:
            stats = cls._stats.setdefault(camera_key, CameraStats(camera_key=camera_key))
            if stats.last_frame_ts is not None:
                delta = now - stats.last_frame_ts
                if delta > 0:
                    instantaneous_fps = 1.0 / delta
                    # Exponential moving average so FPS doesn't jitter
                    # frame-to-frame on a pipeline that's fed by a Celery
                    # beat tick rather than a tight capture loop.
                    stats.fps = (
                        instantaneous_fps
                        if stats.fps == 0.0
                        else stats.fps * 0.7 + instantaneous_fps * 0.3
                    )
            stats.last_frame_ts = now
            stats.frame_count += 1
            stats.last_opencv_ms = opencv_ms
            stats.last_yolo_bytetrack_ms = yolo_bytetrack_ms
            stats.last_total_ms = opencv_ms + yolo_bytetrack_ms
            return stats

    @classmethod
    def record_dropped(cls, camera_key: str) -> None:
        with cls._lock:
            stats = cls._stats.setdefault(camera_key, CameraStats(camera_key=camera_key))
            stats.dropped_count += 1

    @classmethod
    def get(cls, camera_key: str) -> CameraStats | None:
        with cls._lock:
            stats = cls._stats.get(camera_key)
            return CameraStats(**vars(stats)) if stats else None

    @classmethod
    def snapshot_all(cls) -> dict[str, CameraStats]:
        with cls._lock:
            return {k: CameraStats(**vars(v)) for k, v in cls._stats.items()}

    @classmethod
    def reset(cls) -> None:
        """Test-only: clear all recorded stats."""
        with cls._lock:
            cls._stats.clear()
