"""Dispatch in-app alerts for high-confidence detection events."""

from __future__ import annotations

import logging
import uuid

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.metrics import ALERTS_SENT_TOTAL
from app.modules.camera.infrastructure.models import Camera
from app.modules.detection.infrastructure.models import DetectionEvent
from app.modules.identity.infrastructure.models import Role
from app.modules.notification.application.services import NotificationService
from app.modules.notification.infrastructure.models import (
    NotificationChannel,
    NotificationPriority,
)

logger = logging.getLogger(__name__)


class DetectionAlertDispatcher:
    def __init__(
        self,
        notification_service: NotificationService,
        settings: Settings,
    ) -> None:
        self._notifications = notification_service
        self._settings = settings

    def _resolve_classes(self, camera: Camera | None) -> set[str]:
        raw = (
            (camera.alert_classes if camera else None)
            or self._settings.DETECTION_ALERT_CLASSES
            or ""
        )
        return {c.strip().lower() for c in raw.split(",") if c.strip()}

    def _resolve_threshold(self, camera: Camera | None) -> float:
        if camera and camera.alert_min_confidence is not None:
            return float(camera.alert_min_confidence)
        return float(self._settings.DETECTION_ALERT_MIN_CONFIDENCE)

    async def _resolve_fallback_role(
        self,
        organization_id: uuid.UUID,
        session: AsyncSession | None,
    ) -> uuid.UUID | None:
        if session is None:
            return None
        code = (self._settings.DETECTION_ALERT_FALLBACK_ROLE_CODE or "").strip()
        if not code:
            return None
        result = await session.execute(
            select(Role.id).where(
                Role.organization_id == organization_id,
                Role.code == code,
                Role.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def dispatch(
        self,
        event: DetectionEvent,
        camera: Camera | str,
        *,
        session: AsyncSession | None = None,
    ) -> int:
        if isinstance(camera, str):
            camera_obj: Camera | None = None
            camera_name = camera
        else:
            camera_obj = camera
            camera_name = camera.name

        threshold = self._resolve_threshold(camera_obj)
        allowed = self._resolve_classes(camera_obj)
        if not allowed:
            return 0

        recipient_user_id: uuid.UUID | None = event.user_id
        recipient_role_id: uuid.UUID | None = None
        if recipient_user_id is None:
            recipient_role_id = await self._resolve_fallback_role(
                event.organization_id, session
            )
            if recipient_role_id is None:
                return 0

        matches: dict[str, dict] = {}
        for det in event.detections or []:
            if not isinstance(det, dict):
                continue
            class_name = str(det.get("class_name") or "").lower()
            confidence = float(det.get("confidence") or 0.0)
            if class_name not in allowed or confidence < threshold:
                continue
            best = matches.get(class_name)
            if best is None or confidence > float(best.get("confidence") or 0.0):
                matches[class_name] = det
        if not matches:
            return 0

        redis_client = aioredis.from_url(
            self._settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        sent = 0
        try:
            for class_name, det in matches.items():
                dedup_key = (
                    f"alert:detection:{event.organization_id}"
                    f":{event.camera_id}:{class_name}"
                )
                acquired = await redis_client.set(
                    dedup_key,
                    str(event.id),
                    nx=True,
                    ex=int(self._settings.DETECTION_ALERT_DEDUP_SECONDS),
                )
                if not acquired:
                    continue
                confidence = float(det.get("confidence") or 0.0)
                await self._notifications.create(
                    event.organization_id,
                    type="detection.alert",
                    title=f"AI phát hiện {class_name} tại {camera_name}",
                    body=(
                        f"Độ tin cậy {confidence * 100:.1f}% "
                        f"trên model {event.model}"
                    ),
                    recipient_user_id=recipient_user_id,
                    recipient_role_id=recipient_role_id,
                    channel=NotificationChannel.IN_APP,
                    priority=NotificationPriority.HIGH,
                    payload={
                        "camera_id": str(event.camera_id),
                        "camera_name": camera_name,
                        "detection_event_id": str(event.id),
                        "class_name": class_name,
                        "confidence": confidence,
                        "bbox": det.get("bbox"),
                        "model": event.model,
                    },
                )
                ALERTS_SENT_TOTAL.labels(
                    camera_id=str(event.camera_id),
                    class_name=class_name,
                ).inc()
                sent += 1
        finally:
            await redis_client.aclose()
        return sent
