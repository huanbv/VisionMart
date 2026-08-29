"""Periodic RTSP capture job.

For every active camera with a stream URL, ask the AI engine to pull one
frame, persist the frame in MinIO, record a DetectionEvent, and fire
alerts. Runs on Celery Beat when RTSP_CAPTURE_ENABLED is true.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid

from app.config.settings import get_settings
from app.core.metrics import (
    DETECTION_EVENTS_TOTAL,
    DETECTION_OBJECTS_TOTAL,
    RTSP_CAPTURES_TOTAL,
)
from app.database.session import SessionLocal
from app.modules.camera.infrastructure.repositories import (
    SqlAlchemyCameraRepository,
)
from app.modules.detection.application.alert_dispatcher import (
    DetectionAlertDispatcher,
)
from app.modules.detection.application.detection_service import (
    DetectionService,
    archive_product_detections,
)
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)
from app.modules.notification.application.services import NotificationService
from app.modules.notification.infrastructure.repositories import (
    SqlAlchemyNotificationRepository,
)
from app.services.ai_engine_client import AIEngineClient, AIEngineError
from app.services.object_storage import MinioStorage, ObjectStorageError
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _capture_one(
    session,
    ai_client: AIEngineClient,
    storage: MinioStorage,
    dispatcher: DetectionAlertDispatcher,
    camera,
) -> tuple[str, str]:
    try:
        result = await ai_client.capture(
            stream_url=camera.stream_url,
            open_timeout_ms=get_settings().RTSP_CAPTURE_OPEN_TIMEOUT_MS,
        )
    except AIEngineError as exc:
        RTSP_CAPTURES_TOTAL.labels(outcome="error").inc()
        return str(camera.id), f"capture-failed: {exc}"

    frame_b64 = result.pop("frame_base64", None)
    image_key: str | None = None
    if frame_b64:
        try:
            frame_bytes = base64.b64decode(frame_b64)
            image_key = (
                f"detections/{camera.organization_id}/{camera.id}/"
                f"{uuid.uuid4()}.jpg"
            )
            await storage.put(image_key, frame_bytes, content_type="image/jpeg")
        except (ObjectStorageError, ValueError):
            image_key = None

    image_meta = result.get("image") or {}
    result["detections"] = archive_product_detections(
        None,
        result.get("detections"),
        {},
        image_width=int(image_meta.get("width") or 0),
        image_height=int(image_meta.get("height") or 0),
        roi_zones=getattr(camera, "roi_zones", None),
    )

    detection_service = DetectionService(SqlAlchemyDetectionRepository(session))
    event = await detection_service.record(
        organization_id=camera.organization_id,
        camera_id=camera.id,
        user_id=None,
        result=result,
        image_key=image_key,
    )
    await dispatcher.dispatch(event, camera, session=session)
    RTSP_CAPTURES_TOTAL.labels(outcome="ok").inc()
    DETECTION_EVENTS_TOTAL.labels(camera_id=str(camera.id)).inc()
    for det in event.detections or []:
        if isinstance(det, dict):
            cls = str(det.get("class_name") or "unknown")
            DETECTION_OBJECTS_TOTAL.labels(class_name=cls).inc()
    return str(camera.id), f"ok:{event.detection_count}"


async def _run_scan() -> dict:
    settings = get_settings()
    if not settings.RTSP_CAPTURE_ENABLED:
        return {"skipped": "disabled"}

    try:
        async with SessionLocal() as session:
            cameras = await SqlAlchemyCameraRepository(session).list_active_with_stream(
                limit=settings.RTSP_CAPTURE_MAX_CAMERAS,
            )
            if not cameras:
                return {"cameras": 0}

            ai_client = AIEngineClient()
            storage = MinioStorage(settings)
            notifications = NotificationService(
                SqlAlchemyNotificationRepository(session)
            )
            dispatcher = DetectionAlertDispatcher(notifications, settings)

            results: dict[str, str] = {}
            for camera in cameras:
                try:
                    cam_id, status = await _capture_one(
                        session, ai_client, storage, dispatcher, camera
                    )
                    results[cam_id] = status
                except Exception as exc:  # noqa: BLE001
                    logger.exception("rtsp capture failed for camera %s", camera.id)
                    results[str(camera.id)] = f"error: {exc}"
            return {"cameras": len(cameras), "results": results}
    finally:
        from app.database.session import engine
        await engine.dispose()


@celery_app.task(name="rtsp.scan_all", ignore_result=True)
def scan_all() -> dict:
    try:
        result = asyncio.run(_run_scan())
        logger.info("rtsp.scan_all completed: %s", result)
        return result
    except Exception:
        logger.exception("rtsp.scan_all failed")
        raise
