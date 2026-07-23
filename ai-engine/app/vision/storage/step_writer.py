"""Background writer for per-step debug artifacts (DEBUG_AI).

The problem this solves
-----------------------
``trace.py`` already captures a snapshot after every preprocessing stage,
but it flushes them *synchronously*: encoding 8 JPEGs and doing 9 network
round-trips to MinIO, inline, while the frame handler waits. Measured
against a ~35 ms detection budget that is not a small overhead — it is
several times the cost of the work being debugged, and it turns "let me see
what the AI did" into "the AI now runs at 4 fps".

So the rule here is: **the pipeline never waits for storage.** A frame's
artifacts are handed to a bounded queue and the request returns
immediately; a pool of worker tasks drains the queue and uploads.

Why bounded, and why dropping is correct
----------------------------------------
An unbounded queue does not remove the problem, it defers it: if uploads
are slower than capture (they will be — MinIO round-trips vs. in-memory
frames), the queue grows without limit and the process dies of memory
exhaustion instead of running slow. Slow is recoverable, OOM is not.

So the queue has a hard cap and ``submit()`` **drops the sample when full**
rather than blocking or growing. That is the right trade for this data
specifically: these are *diagnostic samples*, not business records. Losing
one frame's debug images when the system is under load costs nothing —
whereas stalling detection to save a debug image would degrade the actual
product. Drops are counted and exposed via :func:`get_stats` so they are
visible rather than silent; a rising drop count means "lower
TRACE_SAMPLE_RATE or give MinIO more headroom".

Contrast with ``ai_events`` in the backend, which must never be dropped —
that is business data and goes through the DB, not this queue.

Memory ownership
----------------
``submit()`` takes ownership of the arrays it is given. The caller must not
mutate them afterwards, because the pipeline reuses buffers in place and a
worker uploading 200 ms later would otherwise encode a frame that has since
been overwritten by a later stage. ``StepArtifact.of()`` copies for you.

Layout written per frame
------------------------
    ai-debug/{camera_key}/{yyyy}/{mm}/{dd}/{frame_uid}/
        01_original.jpg  02_preprocess.jpg  03_detection.jpg
        04_crop.jpg      05_enhanced.jpg    06_classifier.jpg
        07_ocr.jpg       08_result.jpg
        pipeline.json     <- timings, params, metrics, decisions

The date path exists so a retention job can delete a whole day with one
prefix scan, and so no single storage prefix accumulates millions of keys.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("ai-engine.vision.step_writer")

# Defaults chosen to bound worst-case memory rather than to maximise
# throughput. A 640x640x3 uint8 frame is ~1.2 MB; at 8 steps per job that
# is ~10 MB per queued job, so 64 jobs caps the queue's own footprint at
# roughly 600 MB worst case — and in practice far less, because most jobs
# carry 3-4 populated steps, not 8.
DEFAULT_QUEUE_SIZE = 64
DEFAULT_WORKERS = 2
DEFAULT_JPEG_QUALITY = 85

# Canonical step order. The dashboard renders steps in this sequence, so
# the names are part of the contract with the frontend — do not rename
# without updating PipelineTracePage.
STEP_ORDER: tuple[str, ...] = (
    "original",
    "preprocess",
    "detection",
    "crop",
    "enhanced",
    "classifier",
    "ocr",
    "result",
)


@dataclass
class StepArtifact:
    """One named image belonging to a frame's debug set."""

    step: str
    image: Any                      # np.ndarray, BGR
    params: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float | None = None

    @classmethod
    def of(cls, step: str, image, **kw) -> "StepArtifact":
        """Copy the frame so the pipeline may keep mutating its own buffer."""
        return cls(step=step, image=image.copy(), **kw)


@dataclass
class StepJob:
    """Everything needed to persist one frame's debug set."""

    camera_key: str
    frame_uid: str
    artifacts: list[StepArtifact]
    metadata: dict[str, Any] = field(default_factory=dict)
    queued_at: float = field(default_factory=time.perf_counter)


@dataclass
class WriterStats:
    submitted: int = 0
    written: int = 0
    dropped: int = 0
    failed: int = 0
    queue_depth: int = 0
    last_write_ms: float | None = None
    # Time a job spent waiting in the queue. If this climbs, storage is the
    # bottleneck and drops are imminent — the useful early-warning signal.
    last_lag_ms: float | None = None


_QUEUE: asyncio.Queue | None = None
_WORKERS: list[asyncio.Task] = []
_STATS = WriterStats()
_JPEG_QUALITY = DEFAULT_JPEG_QUALITY


def should_debug(cfg) -> bool:
    """Whether this frame should produce a debug set.

    Two gates on purpose: the master switch says debugging is permitted at
    all, the sample rate says how much of it to keep. Without the second,
    the only options would be "no visibility" and "write every frame of a
    30 fps camera", and the useful setting is almost always in between.
    """
    if not getattr(cfg, "debug_ai", False):
        return False
    rate = getattr(cfg, "debug_ai_sample_rate", 1.0)
    if rate >= 1.0:
        return True
    return rate > 0 and random.random() < rate


class DebugCollector:
    """Accumulates a frame's steps, then submits them in one job.

    Doubles as a no-op when debugging is off, so callers can write
    ``collector.add(...)`` unconditionally instead of guarding every call
    site — the guards are what rot when new stages are added.
    """

    __slots__ = ("enabled", "camera_key", "frame_uid", "_artifacts", "_meta", "_t0")

    def __init__(self, camera_key: str, enabled: bool) -> None:
        self.enabled = enabled
        self.camera_key = camera_key
        self.frame_uid = new_frame_uid() if enabled else ""
        self._artifacts: list[StepArtifact] = []
        self._meta: dict[str, Any] = {}
        self._t0 = time.perf_counter()

    def add(self, step: str, image, **params: Any) -> None:
        if not self.enabled or image is None:
            return
        try:
            self._artifacts.append(
                StepArtifact.of(
                    step,
                    image,
                    params=params,
                    elapsed_ms=round((time.perf_counter() - self._t0) * 1000.0, 2),
                )
            )
        except Exception:
            logger.exception("debug collector: could not capture step=%s", step)

    def meta(self, **kw: Any) -> None:
        if self.enabled:
            self._meta.update(kw)

    def flush(self) -> bool:
        """Hand everything to the queue. Returns False if dropped."""
        if not self.enabled or not self._artifacts:
            return False
        return submit(
            StepJob(
                camera_key=self.camera_key,
                frame_uid=self.frame_uid,
                artifacts=self._artifacts,
                metadata=self._meta,
            )
        )


def build_prefix(camera_key: str, frame_uid: str, when: datetime | None = None) -> str:
    d = (when or datetime.now(timezone.utc)).strftime("%Y/%m/%d")
    safe_cam = "".join(c if c.isalnum() or c in "-_" else "_" for c in camera_key)
    return f"ai-debug/{safe_cam}/{d}/{frame_uid}"


def new_frame_uid() -> str:
    return uuid.uuid4().hex


def get_stats() -> WriterStats:
    """Snapshot for the admin health panel. Copied so callers can't mutate."""
    return WriterStats(
        submitted=_STATS.submitted,
        written=_STATS.written,
        dropped=_STATS.dropped,
        failed=_STATS.failed,
        queue_depth=_QUEUE.qsize() if _QUEUE is not None else 0,
        last_write_ms=_STATS.last_write_ms,
        last_lag_ms=_STATS.last_lag_ms,
    )


async def start_writer(
    *,
    queue_size: int = DEFAULT_QUEUE_SIZE,
    workers: int = DEFAULT_WORKERS,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> None:
    """Idempotent — safe to call from a FastAPI startup hook on reload."""
    global _QUEUE, _JPEG_QUALITY
    if _QUEUE is not None:
        return
    _JPEG_QUALITY = jpeg_quality
    _QUEUE = asyncio.Queue(maxsize=queue_size)
    for i in range(max(1, workers)):
        _WORKERS.append(asyncio.create_task(_worker_loop(i), name=f"step-writer-{i}"))
    logger.info(
        "step writer started: queue_size=%d workers=%d jpeg_q=%d",
        queue_size, workers, jpeg_quality,
    )


async def stop_writer(drain_timeout: float = 5.0) -> None:
    """Drain briefly, then cancel. Bounded so shutdown cannot hang on a
    stalled MinIO — losing the tail of a debug queue is acceptable."""
    global _QUEUE
    if _QUEUE is None:
        return
    try:
        await asyncio.wait_for(_QUEUE.join(), timeout=drain_timeout)
    except asyncio.TimeoutError:
        logger.warning("step writer: drain timed out, %d jobs abandoned", _QUEUE.qsize())
    for task in _WORKERS:
        task.cancel()
    await asyncio.gather(*_WORKERS, return_exceptions=True)
    _WORKERS.clear()
    _QUEUE = None
    logger.info("step writer stopped: %s", get_stats())


def submit(job: StepJob) -> bool:
    """Enqueue without ever blocking. Returns False if the sample was dropped.

    Synchronous on purpose: the caller is on the hot path and must not have
    to ``await`` anything to record a debug artifact. ``put_nowait`` raising
    ``QueueFull`` is the intended, normal back-pressure path — not an error.
    """
    _STATS.submitted += 1
    if _QUEUE is None:
        _STATS.dropped += 1
        return False
    try:
        _QUEUE.put_nowait(job)
        return True
    except asyncio.QueueFull:
        _STATS.dropped += 1
        # Rate-limited: under sustained overload this fires per frame, and a
        # log line per dropped frame would itself become a bottleneck.
        if _STATS.dropped % 100 == 1:
            logger.warning(
                "step writer queue full — dropped %d debug samples so far "
                "(storage slower than capture; lower TRACE_SAMPLE_RATE)",
                _STATS.dropped,
            )
        return False


async def _worker_loop(index: int) -> None:
    assert _QUEUE is not None
    while True:
        job = await _QUEUE.get()
        try:
            await _write_job(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            _STATS.failed += 1
            # Swallowed deliberately: a failed debug upload must never kill
            # the worker, or the first MinIO blip would silently disable
            # debugging for the rest of the process's life.
            logger.exception("step writer %d: job failed for %s", index, job.frame_uid)
        finally:
            _QUEUE.task_done()


async def _write_job(job: StepJob) -> None:
    """Encode + upload one job off the event loop.

    Both encoding and upload go to a thread: ``cv2.imencode`` is CPU-bound
    and the MinIO client is blocking, so running either inline would stall
    the same event loop that serves frame requests — which would reintroduce
    exactly the latency this module exists to remove.
    """
    _STATS.last_lag_ms = round((time.perf_counter() - job.queued_at) * 1000.0, 2)
    t0 = time.perf_counter()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_job_blocking, job)
    _STATS.last_write_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    _STATS.written += 1


def _write_job_blocking(job: StepJob) -> None:
    import cv2

    from app.services import object_storage

    prefix = build_prefix(job.camera_key, job.frame_uid)
    order = {name: i for i, name in enumerate(STEP_ORDER)}
    written: list[dict[str, Any]] = []

    for art in sorted(job.artifacts, key=lambda a: order.get(a.step, 99)):
        idx = order.get(art.step, 99) + 1
        key = f"{prefix}/{idx:02d}_{art.step}.jpg"
        try:
            ok, buf = cv2.imencode(
                ".jpg", art.image, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY]
            )
            if not ok:
                logger.warning("step writer: imencode failed step=%s", art.step)
                continue
            data = buf.tobytes()
            object_storage.put_bytes(key, data, content_type="image/jpeg")
            written.append(
                {
                    "step": art.step,
                    "order": idx,
                    "key": key,
                    "bytes": len(data),
                    "params": art.params,
                    "elapsed_ms": art.elapsed_ms,
                }
            )
        except Exception:
            # Per-step, not per-job: one unwritable step must not cost the
            # other seven. A partial set is still diagnostically useful.
            logger.exception("step writer: upload failed step=%s", art.step)
        finally:
            art.image = None  # release the copy as soon as it is encoded

    manifest = {
        "frame_uid": job.frame_uid,
        "camera_key": job.camera_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queue_lag_ms": _STATS.last_lag_ms,
        "steps": written,
        **job.metadata,
    }
    try:
        object_storage.put_bytes(
            f"{prefix}/pipeline.json",
            json.dumps(manifest, ensure_ascii=False, default=str).encode("utf-8"),
            content_type="application/json",
        )
    except Exception:
        logger.exception("step writer: manifest upload failed for %s", job.frame_uid)
