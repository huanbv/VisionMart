"""Dispatch in-app alerts for high-confidence detection events."""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from app.config.settings import Settings
from app.modules.detection.infrastructure.models import DetectionEvent
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

    def _allowed_classes(self) -> set[str]:
        raw = self._settings.DETECTION_ALERT_CLASSES or ""
        return {c.strip().lower() for c in raw.split(",") if c.strip()}

    async def dispatch(
        self, event: DetectionEvent, camera_name: str
    ) -> int:
        threshold = float(self._settings.DETECTION_ALERT_MIN_CONFIDENCE)
        allowed = self._allowed_classes()
        if event.user_id is None or not allowed:
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
                    recipient_user_id=event.user_id,
                    recipient_role_id=None,
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
                sent += 1
        finally:
            await redis_client.aclose()
        return sent
