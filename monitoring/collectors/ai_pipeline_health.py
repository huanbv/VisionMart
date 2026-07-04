"""AI pipeline health monitoring.

Reads ai-engine's existing `/metrics` Prometheus endpoint and, for queue
depth, the Celery broker (Redis) directly. Nothing here calls into
`ai-engine/app/vision/*` or `ai-engine/app/services/*` — no code in
either service was modified to support this collector.

Metrics exposed here and where each comes from:

  - `inference_latency_ms` — `ai_engine_inference_seconds` histogram
    (already existed; emitted per `/ai/detect` and `/ai/frame` call).
  - `opencv_stage_ms` / `yolo_bytetrack_stage_ms` / `pipeline_total_ms` —
    the vision/ pipeline histograms added in the OpenCV Integration
    Sprint (`ai_engine_vision_opencv_seconds`,
    `ai_engine_vision_yolo_bytetrack_seconds`,
    `ai_engine_vision_pipeline_total_seconds`), aggregated across all
    cameras. Only populated when `ENABLE_PERFORMANCE_METRICS=true`.
  - `queue_length` — read directly from the Celery broker (Redis LLEN on
    each configured queue name), independent of any backend import.

Explicitly NOT measured, and why (see module list below rather than a
fabricated number):

  - **ByteTrack time in isolation.** ultralytics fuses YOLO inference and
    ByteTrack association into a single `model.track()` call in
    production (`person_tracker.py`); the histogram above is the combined
    time, exactly as documented in `docs/22_VIDEO_PIPELINE.md` and the
    Sprint 1 report. Splitting it would need either patching ultralytics
    internals in production code (out of scope; production AI logic is
    off-limits) or the two-call `predict()`+`track()` trick the
    `evaluation/` framework uses offline — not something to do against a
    live production camera feed on every frame (it would double real
    inference cost).
  - **Active track count.** `person_tracker.py` keeps per-camera tracker
    state in-process but does not currently publish it as a Prometheus
    gauge, and adding that would require an edit inside the tracking
    module itself, which this monitoring layer intentionally does not
    touch (see the "Do not modify ... AI logic" constraint this package
    was built under). Reported as `not_available` with that reason.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from monitoring.collectors.http_metrics import scrape


@dataclass
class QueueStatus:
    queue_name: str
    length: int | None
    reason: str | None = None


@dataclass
class AiPipelineSnapshot:
    checked_at: float
    ai_engine_reachable: bool
    ai_engine_reason: str | None
    inference_latency_ms: float | None
    opencv_stage_ms: float | None
    yolo_bytetrack_stage_ms: float | None
    pipeline_total_ms: float | None
    detect_requests_ok_total: float | None
    detect_requests_error_total: float | None
    active_tracks: str = "not_available"
    active_tracks_reason: str = (
        "person_tracker.py does not publish an active-track-count gauge; adding one would "
        "require editing production tracking code, which this monitoring layer avoids per its "
        "read-only, non-invasive design constraint."
    )
    queues: list[QueueStatus] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = dict(vars(self))
        d["queues"] = [vars(q) for q in self.queues]
        return d


async def _queue_lengths(redis_url: str, queue_names: list[str]) -> list[QueueStatus]:
    import redis.asyncio as aioredis

    out: list[QueueStatus] = []
    try:
        client = aioredis.from_url(redis_url, socket_timeout=5)
        try:
            for q in queue_names:
                try:
                    length = await client.llen(q)
                    out.append(QueueStatus(queue_name=q, length=int(length)))
                except Exception as exc:  # noqa: BLE001
                    out.append(QueueStatus(queue_name=q, length=None, reason=str(exc)))
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        for q in queue_names:
            out.append(QueueStatus(queue_name=q, length=None, reason=f"Redis not reachable: {exc}"))
    return out


async def collect_ai_pipeline_health(
    ai_engine_url: str,
    redis_url: str,
    *,
    queue_names: list[str] | None = None,
) -> AiPipelineSnapshot:
    now = time.time()
    queue_names = queue_names or ["celery"]

    result = await scrape(f"{ai_engine_url}/metrics")
    queues = await _queue_lengths(redis_url, queue_names)

    if not result.reachable:
        return AiPipelineSnapshot(
            checked_at=now, ai_engine_reachable=False, ai_engine_reason=result.reason,
            inference_latency_ms=None, opencv_stage_ms=None, yolo_bytetrack_stage_ms=None,
            pipeline_total_ms=None, detect_requests_ok_total=None, detect_requests_error_total=None,
            queues=queues,
        )

    inf_stats = result.histogram_stats("ai_engine_inference_seconds")
    opencv_stats = result.histogram_stats("ai_engine_vision_opencv_seconds")
    yolo_stats = result.histogram_stats("ai_engine_vision_yolo_bytetrack_seconds")
    total_stats = result.histogram_stats("ai_engine_vision_pipeline_total_seconds")

    ok_total = sum(s.value for s in result.metrics.get("ai_engine_detect_requests_total", []) if s.labels.get("outcome") == "ok")
    err_total = sum(s.value for s in result.metrics.get("ai_engine_detect_requests_total", []) if s.labels.get("outcome") == "error")

    return AiPipelineSnapshot(
        checked_at=now,
        ai_engine_reachable=True,
        ai_engine_reason=None,
        inference_latency_ms=inf_stats["mean"] * 1000.0 if inf_stats else None,
        opencv_stage_ms=opencv_stats["mean"] * 1000.0 if opencv_stats else None,
        yolo_bytetrack_stage_ms=yolo_stats["mean"] * 1000.0 if yolo_stats else None,
        pipeline_total_ms=total_stats["mean"] * 1000.0 if total_stats else None,
        detect_requests_ok_total=ok_total if result.metrics.get("ai_engine_detect_requests_total") else None,
        detect_requests_error_total=err_total if result.metrics.get("ai_engine_detect_requests_total") else None,
        queues=queues,
    )
