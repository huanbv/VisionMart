"""Pushes per-frame telemetry to the backend dashboard.

This is the link that makes the ``ai_*`` tables and the admin dashboard
show anything. The engine owns no database connection by design, so it
reports what it did over HTTP and the backend does the persisting.

Three properties this must have, in priority order:

1. **Never slow down inference.** Reports go into a bounded in-memory
   buffer and are flushed by a background task. Nothing on the frame path
   ever awaits the network.
2. **Never crash the pipeline.** Every failure — backend down, bad
   response, serialisation error — is logged and swallowed. Losing
   telemetry is an inconvenience; a 500 on ``/ai/frame`` because the
   dashboard's database was busy is an outage.
3. **Bounded memory.** Like the debug-image writer, the buffer has a hard
   cap and *drops the oldest* reports when full, rather than growing.

Why drop the oldest here, but the newest in ``step_writer``
-----------------------------------------------------------
``step_writer`` rejects new samples at ``submit()`` because its items are
independent diagnostic snapshots — any one is as good as any other, and
refusing at the door is cheapest. Telemetry is a *time series* of what the
model is doing right now; when the backend has been unreachable for a
while, the stale head of the queue is the least valuable part, and an
operator opening the dashboard wants the recent frames. So the oldest go
first.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any

import httpx

logger = logging.getLogger("ai-engine.telemetry")

_BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
_API_PREFIX = os.getenv("BACKEND_API_PREFIX", "/api/v1")

_BUFFER: deque[dict[str, Any]] = deque()
_SESSION_IDS: dict[str, str] = {}      # camera_key -> backend session id
_SESSION_SEQ: dict[str, int] = {}      # camera_key -> next frame seq
_FLUSH_TASK: asyncio.Task | None = None
_ENABLED = False
_MAX_QUEUE = 500
_BATCH_SIZE = 20
_FLUSH_SECONDS = 5.0

_STATS = {"buffered": 0, "sent": 0, "dropped": 0, "failed": 0}


def _headers() -> dict[str, str]:
    return {"X-AI-Engine-Key": os.getenv("AI_ENGINE_API_KEY", "")}


def get_stats() -> dict[str, Any]:
    return {**_STATS, "queue_depth": len(_BUFFER), "enabled": _ENABLED,
            "open_sessions": len(_SESSION_IDS)}


def next_seq(camera_key: str) -> int:
    """Monotonic frame index within a session.

    Kept here rather than derived from a timestamp because several frames
    can share a millisecond, and the dashboard's Previous/Next needs a
    total order that never ties.
    """
    seq = _SESSION_SEQ.get(camera_key, 0)
    _SESSION_SEQ[camera_key] = seq + 1
    return seq


async def ensure_session(
    camera_key: str,
    *,
    organization_id: str,
    branch_id: str | None = None,
    camera_id: str | None = None,
    cfg: Any = None,
) -> str | None:
    """Get (or open) the backend session id for this camera.

    Opening is the one telemetry call that *does* happen inline, because
    every frame report needs the id. It happens once per camera per process
    and its failure is cached as ``None`` handled by the caller — a backend
    that is down at startup must not stall frame handling.
    """
    if not _ENABLED:
        return None
    existing = _SESSION_IDS.get(camera_key)
    if existing:
        return existing

    payload = {
        "organization_id": organization_id,
        "branch_id": branch_id,
        "camera_id": camera_id,
        "camera_key": camera_key,
        "detector_version": os.getenv("YOLO_MODEL", "yolov8n.pt"),
        "classifier_version": (
            getattr(cfg, "classifier_model_path", None) if cfg else None
        ),
        # Snapshot of the flags in force, so a frame stays explainable
        # after someone changes the config next week.
        "config_snapshot": _config_snapshot(cfg),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{_BACKEND_URL}{_API_PREFIX}/ai/pipeline/sessions/open",
                json=payload,
                headers=_headers(),
            )
            response.raise_for_status()
            session_id = response.json().get("session_id")
    except Exception:
        logger.warning("telemetry: could not open session for %s", camera_key, exc_info=True)
        return None

    if session_id:
        _SESSION_IDS[camera_key] = session_id
        _SESSION_SEQ.setdefault(camera_key, 0)
    return session_id


def _config_snapshot(cfg: Any) -> dict[str, Any] | None:
    if cfg is None:
        return None
    keys = (
        "enable_clahe", "enable_gamma", "enable_denoise", "enable_bilateral",
        "enable_unsharp_mask", "enable_auto_gamma", "enable_sku_classifier",
        "enable_ocr_fallback", "enable_embeddings", "debug_ai",
        "classifier_min_confidence", "share_yolo_weights",
    )
    return {k: getattr(cfg, k) for k in keys if hasattr(cfg, k)}


def report_frame(camera_key: str, payload: dict[str, Any]) -> bool:
    """Buffer one frame report. Synchronous and non-blocking by contract.

    Returns False when the report was dropped, which the caller may ignore
    — telemetry is best-effort and the frame result is already correct
    without it.
    """
    if not _ENABLED:
        return False
    session_id = _SESSION_IDS.get(camera_key)
    if not session_id:
        return False

    if len(_BUFFER) >= _MAX_QUEUE:
        # Oldest out — see the module docstring for why this differs from
        # step_writer's newest-out policy.
        _BUFFER.popleft()
        _STATS["dropped"] += 1
        if _STATS["dropped"] % 100 == 1:
            logger.warning(
                "telemetry buffer full — dropped %d old reports (backend slow "
                "or unreachable)", _STATS["dropped"],
            )
    _BUFFER.append({"session_id": session_id, "frame": payload})
    _STATS["buffered"] += 1
    return True


async def _flush_once() -> None:
    """Send everything buffered, grouped by session.

    Grouped because the ingest endpoint takes one session per call; a
    multi-camera engine would otherwise need a call per frame, which is the
    overhead batching exists to avoid.
    """
    if not _BUFFER:
        return
    batch: list[dict[str, Any]] = []
    while _BUFFER and len(batch) < _BATCH_SIZE:
        batch.append(_BUFFER.popleft())

    by_session: dict[str, list[dict[str, Any]]] = {}
    for item in batch:
        by_session.setdefault(item["session_id"], []).append(item["frame"])

    org_id = os.getenv("AI_ORGANIZATION_ID", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        for session_id, frames in by_session.items():
            try:
                response = await client.post(
                    f"{_BACKEND_URL}{_API_PREFIX}/ai/pipeline/ingest",
                    json={
                        "organization_id": frames[0].get("organization_id") or org_id,
                        "session_id": session_id,
                        "frames": frames,
                    },
                    headers=_headers(),
                )
                response.raise_for_status()
                _STATS["sent"] += len(frames)
            except Exception:
                _STATS["failed"] += len(frames)
                # Not re-queued on purpose: a backend that is failing would
                # otherwise get the same batch forever while fresh frames
                # pile up behind it. Telemetry is expendable; keeping the
                # stream current is not.
                logger.warning(
                    "telemetry: ingest failed for session %s (%d frames dropped)",
                    session_id, len(frames), exc_info=True,
                )


async def _flush_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_FLUSH_SECONDS)
            await _flush_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telemetry flush loop error")


async def start(cfg: Any) -> None:
    """Enable buffering and start the flush task. Idempotent."""
    global _FLUSH_TASK, _ENABLED, _MAX_QUEUE, _BATCH_SIZE, _FLUSH_SECONDS
    if not getattr(cfg, "enable_telemetry", False):
        return
    if _FLUSH_TASK is not None:
        return
    _MAX_QUEUE = int(getattr(cfg, "telemetry_max_queue", 500))
    _BATCH_SIZE = int(getattr(cfg, "telemetry_batch_size", 20))
    _FLUSH_SECONDS = float(getattr(cfg, "telemetry_flush_seconds", 5.0))
    _ENABLED = True
    _FLUSH_TASK = asyncio.create_task(_flush_loop(), name="telemetry-flush")
    logger.info(
        "telemetry started: batch=%d every %.1fs, max_queue=%d",
        _BATCH_SIZE, _FLUSH_SECONDS, _MAX_QUEUE,
    )


async def stop() -> None:
    """Flush what is buffered, close sessions, stop the task."""
    global _FLUSH_TASK, _ENABLED
    _ENABLED = False
    if _FLUSH_TASK is not None:
        _FLUSH_TASK.cancel()
        try:
            await _FLUSH_TASK
        except (asyncio.CancelledError, Exception):
            pass
        _FLUSH_TASK = None
    try:
        # One last flush so the final seconds of a session are not lost on
        # a graceful restart.
        await asyncio.wait_for(_flush_once(), timeout=5.0)
    except Exception:
        logger.debug("telemetry: final flush failed", exc_info=True)

    async with httpx.AsyncClient(timeout=5.0) as client:
        for session_id in list(_SESSION_IDS.values()):
            try:
                await client.post(
                    f"{_BACKEND_URL}{_API_PREFIX}/ai/pipeline/sessions/{session_id}/close",
                    headers=_headers(),
                )
            except Exception:
                logger.debug("telemetry: close session %s failed", session_id)
    _SESSION_IDS.clear()
    _SESSION_SEQ.clear()


def reset() -> None:
    """Test hook: drop all state."""
    _BUFFER.clear()
    _SESSION_IDS.clear()
    _SESSION_SEQ.clear()
    for k in _STATS:
        _STATS[k] = 0
