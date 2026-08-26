"""Continuous frame pipeline: grab a live frame per camera and run the real
tracking + cart-automation pipeline (`/ai/frame`) on it.

This is distinct from `rtsp_capture.py`'s `rtsp.scan_all`, which only calls
`/capture` (plain detection, used for the DetectionEvent/alerts feed) once
every `RTSP_CAPTURE_INTERVAL_SECONDS` (default 60s) — far too infrequent to
catch a product pickup/return, and it never touches tracking or the cart
pipeline at all. `product_picked_up` / `product_returned` /
`checkout_initiated` only ever get emitted when something calls `/ai/frame`;
before this task existed, the only callers were the manual
"analyze one frame" button and the `/cart/simulate` demo endpoint — nothing
watched real cameras continuously.

Runs on every Celery Beat tick, but each branch is skipped unless its Live
Cart switch is on. ``FRAME_PIPELINE_ENABLED`` is the initial default for a
branch that has never been toggled; an explicit UI choice is persisted in
Redis and overrides it. Each camera holds a full YOLO model instance in
ai-engine's RAM, so tune FRAME_PIPELINE_MAX_CAMERAS and the interval
conservatively.
"""

from __future__ import annotations

import asyncio
import base64
import logging

import redis.asyncio as aioredis

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.modules.camera.application.ai_auto_scan import is_paused_on
from app.modules.camera.infrastructure.repositories import (
    SqlAlchemyCameraRepository,
)
from app.services.ai_engine_client import AIEngineClient, AIEngineError
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_LOCK_KEY = "lock:frame_pipeline:scan_all"
# Safety-net expiry in case a run crashes without releasing the lock —
# comfortably above the worst-case runtime (FRAME_PIPELINE_MAX_CAMERAS
# cameras processed sequentially, each up to ~open_timeout + inference).
_LOCK_TTL_SECONDS = 55


async def _process_one(ai_client: AIEngineClient, camera) -> tuple[str, str]:
    settings = get_settings()
    try:
        captured = await ai_client.capture(
            stream_url=camera.stream_url,
            open_timeout_ms=settings.FRAME_PIPELINE_OPEN_TIMEOUT_MS,
            # JPEG is sent through /ai/frame next. Detection here doubled
            # YOLO load and is not used for cart events.
            detect=False,
        )
    except AIEngineError as exc:
        return str(camera.id), f"capture-failed: {exc}"

    frame_b64 = captured.get("frame_base64")
    if not frame_b64:
        return str(camera.id), "capture-empty"

    try:
        frame_bytes = base64.b64decode(frame_b64)
    except ValueError as exc:
        return str(camera.id), f"decode-failed: {exc}"

    try:
        result = await ai_client.frame(
            content=frame_bytes,
            filename="frame.jpg",
            content_type="image/jpeg",
            organization_id=str(camera.organization_id),
            branch_id=str(camera.branch_id),
            camera_id=str(camera.id),
            recognize_face=settings.FRAME_PIPELINE_RECOGNIZE_FACE,
            min_confidence=settings.FRAME_PIPELINE_MIN_CONFIDENCE,
        )
    except AIEngineError as exc:
        return str(camera.id), f"frame-pipeline-failed: {exc}"

    emitted = result.get("emitted_events") or []
    return str(camera.id), f"ok:persons={result.get('persons')},events={len(emitted)}"


async def _run_scan() -> dict:
    settings = get_settings()

    # Celery beat fires this every FRAME_PIPELINE_INTERVAL_SECONDS regardless
    # of whether the previous run finished. At a 2-3s interval, a slow run
    # (many cameras, a slow RTSP source) would otherwise overlap with the
    # next one, doubling up ai-engine load — the same failure mode as the
    # earlier --workers=2 OOM incident, just triggered from the backend side
    # instead. A short-lived Redis lock makes overlapping ticks a no-op skip
    # instead of a pile-up.
    redis_client = aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    try:
        acquired = await redis_client.set(
            _LOCK_KEY, "1", nx=True, ex=_LOCK_TTL_SECONDS
        )
        if not acquired:
            return {"skipped": "previous run still in progress"}

        async with SessionLocal() as session:
            cameras = await SqlAlchemyCameraRepository(
                session
            ).list_active_with_stream(limit=settings.FRAME_PIPELINE_MAX_CAMERAS)
            if not cameras:
                return {"cameras": 0}

            ai_client = AIEngineClient()
            results: dict[str, str] = {}
            paused_cache: dict[str, bool] = {}
            # Sequential on purpose: each call already triggers a YOLO
            # inference (+ tracking) in ai-engine; running
            # FRAME_PIPELINE_MAX_CAMERAS of those concurrently would spike
            # CPU/RAM exactly the way the earlier --workers/OOM incident
            # did. Cameras needing tighter real-time coverage should get a
            # shorter FRAME_PIPELINE_INTERVAL_SECONDS or their own dedicated
            # worker, not more concurrency here.
            for camera in cameras:
                try:
                    branch_key = str(camera.branch_id)
                    if branch_key not in paused_cache:
                        paused_cache[branch_key] = await is_paused_on(
                            redis_client, camera.branch_id
                        )
                    # Branch-level state is authoritative. An explicit "on"
                    # from Live Cart is persisted as Redis value ``0`` and
                    # can enable this branch even when the deployment-wide
                    # FRAME_PIPELINE_ENABLED default is false.
                    if paused_cache[branch_key]:
                        results[str(camera.id)] = "skipped:auto-scan-paused"
                        continue
                    cam_id, outcome = await _process_one(ai_client, camera)
                    results[cam_id] = outcome
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "frame pipeline failed for camera %s", camera.id
                    )
                    results[str(camera.id)] = f"error: {exc}"
            return {"cameras": len(cameras), "results": results}
    finally:
        try:
            await redis_client.delete(_LOCK_KEY)
        except Exception:  # noqa: BLE001
            pass
        await redis_client.aclose()
        from app.database.session import engine
        await engine.dispose()


@celery_app.task(name="frame_pipeline.scan_all", ignore_result=True)
def scan_all() -> dict:
    try:
        result = asyncio.run(_run_scan())
        logger.info("frame_pipeline.scan_all completed: %s", result)
        return result
    except Exception:
        logger.exception("frame_pipeline.scan_all failed")
        raise
