"""SQLAlchemy repository for the Audit bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.infrastructure.models import AuditLog


class SqlAlchemyAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _apply_filters(
        self,
        stmt,
        *,
        organization_id: uuid.UUID | None,
        action: str | None,
        resource_type: str | None,
        resource_id: str | None,
        user_id: uuid.UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ):
        if organization_id is not None:
            stmt = stmt.where(AuditLog.organization_id == organization_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if resource_id:
            stmt = stmt.where(AuditLog.resource_id == resource_id)
        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if date_from is not None:
            stmt = stmt.where(AuditLog.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(AuditLog.created_at <= date_to)
        return stmt

    async def list(
        self,
        *,
        organization_id: uuid.UUID | None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        user_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Sequence[AuditLog]:
        stmt = self._apply_filters(
            select(AuditLog),
            organization_id=organization_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
        ).order_by(AuditLog.created_at.desc()).offset(skip).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()

    async def count(
        self,
        *,
        organization_id: uuid.UUID | None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        user_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        stmt = self._apply_filters(
            select(func.count(AuditLog.id)),
            organization_id=organization_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def add(self, log: AuditLog) -> AuditLog:
        self._session.add(log)
        await self._session.commit()
        await self._session.refresh(log)
        return log
