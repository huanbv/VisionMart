"""SQLAlchemy repository for the Detection bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.detection.infrastructure.models import DetectionEvent


class SqlAlchemyDetectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _apply_filters(
        self,
        stmt,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None,
        model: str | None,
        min_confidence: float | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ):
        stmt = stmt.where(DetectionEvent.organization_id == organization_id)
        if camera_id is not None:
            stmt = stmt.where(DetectionEvent.camera_id == camera_id)
        if model:
            stmt = stmt.where(DetectionEvent.model == model)
        if min_confidence is not None:
            stmt = stmt.where(DetectionEvent.max_confidence >= min_confidence)
        if date_from is not None:
            stmt = stmt.where(DetectionEvent.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(DetectionEvent.created_at <= date_to)
        return stmt

    async def add(self, event: DetectionEvent) -> DetectionEvent:
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(event)
        return event

    async def get(
        self, organization_id: uuid.UUID, event_id: uuid.UUID
    ) -> DetectionEvent | None:
        stmt = select(DetectionEvent).where(
            DetectionEvent.id == event_id,
            DetectionEvent.organization_id == organization_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

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
    ) -> Sequence[DetectionEvent]:
        stmt = self._apply_filters(
            select(DetectionEvent),
            organization_id=organization_id,
            camera_id=camera_id,
            model=model,
            min_confidence=min_confidence,
            date_from=date_from,
            date_to=date_to,
        ).order_by(DetectionEvent.created_at.desc()).offset(skip).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()

    async def count(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        model: str | None = None,
        min_confidence: float | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        stmt = self._apply_filters(
            select(func.count(DetectionEvent.id)),
            organization_id=organization_id,
            camera_id=camera_id,
            model=model,
            min_confidence=min_confidence,
            date_from=date_from,
            date_to=date_to,
        )
        return int((await self._session.execute(stmt)).scalar_one())
