"""Pipeline performance metrics: timing, FPS, CPU/memory/GPU, throughput,
dropped frames.

Honesty note on ByteTrack timing: ultralytics' `model.track()` runs YOLO
inference AND tracker association in one internal call — there is no
public API to time them separately from inside a single `track()` call
(see the Sprint 1 report's discussion of this same limitation in
production code). This *offline evaluation* framework works around it by
calling `model.predict()` (detection only) and `model.track()` (detection
+ tracking) separately **on the same frame** and computing
``bytetrack_ms = track_ms - predict_ms`` (clamped to >= 0). This is a
derived estimate from two real, wall-clock measurements, not a guess — but
it does mean the frame is run through YOLO's forward pass twice (once via
`predict()`, once inside `track()`), which is acceptable for an offline,
one-off evaluation run but would be wasteful in production, which is
exactly why production code (`person_tracker.py`) does not do this and
instead reports one combined `yolo_bytetrack_ms` figure. Every report this
framework produces labels `bytetrack_ms` as "(derived: track() - predict(),
same frame)" so this is never mistaken for a direct hardware trace.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(len(s) * pct))
    return s[idx]


@dataclass
class FrameRecord:
    frame_name: str
    opencv_ms: float
    yolo_ms: float | None = None
    bytetrack_ms: float | None = None
    total_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


class GpuSampler:
    """Best-effort GPU usage sampling via `pynvml` if installed and an
    NVIDIA GPU is present; otherwise every call returns ``None`` and the
    report states GPU metrics were not available rather than reporting 0%
    (0% would misleadingly imply a GPU exists and is idle)."""

    def __init__(self) -> None:
        self.available = False
        self._handle = None
        try:
            import pynvml

            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._pynvml = pynvml
            self.available = True
        except Exception:  # noqa: BLE001 — no GPU, no driver, or no pynvml; all equally "not available"
            self.available = False

    def sample(self) -> dict | None:
        if not self.available:
            return None
        util = self._pynvml.nvmlDeviceGetUtilizationRates(self._handle)
        mem = self._pynvml.nvmlDeviceGetMemoryInfo(self._handle)
        return {
            "gpu_util_percent": util.gpu,
            "gpu_mem_used_mb": round(mem.used / (1024 * 1024), 1),
        }


class ResourceSampler:
    """CPU% / RSS memory via psutil, if installed. Returns None fields
    (never 0) when psutil is unavailable."""

    def __init__(self) -> None:
        self._proc = None
        try:
            import os

            import psutil

            self._proc = psutil.Process(os.getpid())
            self._proc.cpu_percent(interval=None)
        except ImportError:
            self._proc = None

    @property
    def available(self) -> bool:
        return self._proc is not None

    def sample(self) -> dict | None:
        if self._proc is None:
            return None
        return {
            "cpu_percent": self._proc.cpu_percent(interval=None),
            "rss_mb": round(self._proc.memory_info().rss / (1024 * 1024), 1),
        }


class PipelineMetricsCollector:
    """Accumulates per-frame timing across one (dataset, configuration)
    run and produces the aggregate metrics listed in the framework brief:
    average/min/max FPS, CPU/memory/GPU usage, dropped frames, camera
    throughput, per-frame processing time.
    """

    def __init__(self, config_name: str) -> None:
        self.config_name = config_name
        self.records: list[FrameRecord] = []
        self.resource_sampler = ResourceSampler()
        self.gpu_sampler = GpuSampler()
        self._resource_samples: list[dict] = []
        self._gpu_samples: list[dict] = []
        self._wall_start: float | None = None
        self._wall_end: float | None = None
        self.dropped_frames = 0

    def start(self) -> None:
        self._wall_start = time.perf_counter()

    def record(self, frame_name: str, opencv_ms: float, yolo_ms: float | None, bytetrack_ms: float | None) -> None:
        total = opencv_ms + (yolo_ms or 0.0) + (bytetrack_ms or 0.0)
        self.records.append(
            FrameRecord(frame_name=frame_name, opencv_ms=opencv_ms, yolo_ms=yolo_ms, bytetrack_ms=bytetrack_ms, total_ms=total)
        )
        r = self.resource_sampler.sample()
        if r:
            self._resource_samples.append(r)
        g = self.gpu_sampler.sample()
        if g:
            self._gpu_samples.append(g)

    def stop(self) -> None:
        self._wall_end = time.perf_counter()

    def _stage_stats(self, values: list[float]) -> dict | None:
        if not values:
            return None
        return {
            "mean_ms": round(statistics.mean(values), 3),
            "min_ms": round(min(values), 3),
            "max_ms": round(max(values), 3),
            "p50_ms": round(_percentile(values, 0.50), 3),
            "p95_ms": round(_percentile(values, 0.95), 3),
        }

    def summary(self) -> dict:
        n = len(self.records)
        wall_s = (self._wall_end - self._wall_start) if (self._wall_start and self._wall_end) else None
        opencv_vals = [r.opencv_ms for r in self.records]
        yolo_vals = [r.yolo_ms for r in self.records if r.yolo_ms is not None]
        bytetrack_vals = [r.bytetrack_ms for r in self.records if r.bytetrack_ms is not None]
        total_vals = [r.total_ms for r in self.records]

        per_frame_fps = [1000.0 / t for t in total_vals if t > 0]

        cpu_vals = [s["cpu_percent"] for s in self._resource_samples]
        rss_vals = [s["rss_mb"] for s in self._resource_samples]
        gpu_util_vals = [s["gpu_util_percent"] for s in self._gpu_samples]
        gpu_mem_vals = [s["gpu_mem_used_mb"] for s in self._gpu_samples]

        return {
            "config_name": self.config_name,
            "frame_count": n,
            "dropped_frames": self.dropped_frames,
            "wall_elapsed_s": round(wall_s, 3) if wall_s is not None else None,
            "avg_fps": round(n / wall_s, 2) if wall_s and wall_s > 0 else None,
            "min_fps_per_frame": round(min(per_frame_fps), 2) if per_frame_fps else None,
            "max_fps_per_frame": round(max(per_frame_fps), 2) if per_frame_fps else None,
            "camera_throughput_fps": round(n / wall_s, 2) if wall_s and wall_s > 0 else None,
            "avg_processing_time_per_frame_ms": round(statistics.mean(total_vals), 3) if total_vals else None,
            "opencv_stage": self._stage_stats(opencv_vals),
            "yolo_stage": self._stage_stats(yolo_vals) if yolo_vals else None,
            "bytetrack_stage": self._stage_stats(bytetrack_vals) if bytetrack_vals else None,
            "bytetrack_stage_method": (
                "derived: track() - predict() wall time, same frame — see module docstring"
                if bytetrack_vals else None
            ),
            "total_stage": self._stage_stats(total_vals),
            "cpu_percent_avg": round(statistics.mean(cpu_vals), 1) if cpu_vals else None,
            "rss_mb_avg": round(statistics.mean(rss_vals), 1) if rss_vals else None,
            "rss_mb_max": round(max(rss_vals), 1) if rss_vals else None,
            "gpu_available": self.gpu_sampler.available,
            "gpu_util_percent_avg": round(statistics.mean(gpu_util_vals), 1) if gpu_util_vals else None,
            "gpu_mem_used_mb_avg": round(statistics.mean(gpu_mem_vals), 1) if gpu_mem_vals else None,
        }
