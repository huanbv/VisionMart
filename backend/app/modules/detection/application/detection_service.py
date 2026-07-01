"""Application service for the Detection bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from app.modules.detection.infrastructure.models import DetectionEvent
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)


class DetectionService:
    def __init__(self, repo: SqlAlchemyDetectionRepository) -> None:
        self._repo = repo

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID,
        user_id: uuid.UUID | None,
        result: dict,
        image_key: str | None = None,
    ) -> DetectionEvent:
        image = result.get("image", {}) or {}
        detections = result.get("detections", []) or []
        confidences = [
            float(d.get("confidence", 0.0) or 0.0)
            for d in detections
            if isinstance(d, dict)
        ]
        event = DetectionEvent(
            organization_id=organization_id,
            camera_id=camera_id,
            user_id=user_id,
            model=str(result.get("model") or "unknown"),
            image_width=int(image.get("width") or 0),
            image_height=int(image.get("height") or 0),
            image_format=image.get("format"),
            image_size_bytes=int(image.get("size_bytes") or 0),
            elapsed_ms=int(result.get("elapsed_ms") or 0),
            detection_count=len(detections),
            max_confidence=max(confidences) if confidences else 0.0,
            image_key=image_key,
            detections=detections,
        )
        return await self._repo.add(event)

    async def get(
        self, organization_id: uuid.UUID, event_id: uuid.UUID
    ) -> DetectionEvent | None:
        return await self._repo.get(organization_id, event_id)

    async def list(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        model: str | None = None,
        min_confidence: float | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[DetectionEvent], int]:
        items = await self._repo.list(
            organization_id=organization_id,
            camera_id=camera_id,
            model=model,
            min_confidence=min_confidence,
            date_from=date_from,
            date_to=date_to,
            skip=skip,
            limit=limit,
        )
        total = await self._repo.count(
            organization_id=organization_id,
            camera_id=camera_id,
            model=model,
            min_confidence=min_confidence,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total
