"""SQLAlchemy repositories for the Notification bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.infrastructure.models import UserRole
from app.modules.notification.infrastructure.models import (
    Notification,
    NotificationStatus,
)


class SqlAlchemyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _recipient_filter(self, user_id: uuid.UUID):
        role_subq = select(UserRole.role_id).where(UserRole.user_id == user_id)
        return or_(
            Notification.recipient_user_id == user_id,
            Notification.recipient_role_id.in_(role_subq),
        )

    async def list_for_user(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        unread_only: bool = False,
    ) -> tuple[list[Notification], int]:
        base = select(Notification).where(
            Notification.organization_id == organization_id,
            Notification.is_deleted.is_(False),
            self._recipient_filter(user_id),
        )
        if unread_only:
            base = base.where(Notification.is_read.is_(False))

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        items = (
            (
                await self._session.execute(
                    base.order_by(Notification.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(items), int(total)

    async def unread_count(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        stmt = select(func.count(Notification.id)).where(
            Notification.organization_id == organization_id,
            Notification.is_deleted.is_(False),
            Notification.is_read.is_(False),
            self._recipient_filter(user_id),
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def get_for_user(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> Notification | None:
        stmt = select(Notification).where(
            Notification.id == notification_id,
            Notification.organization_id == organization_id,
            Notification.is_deleted.is_(False),
            self._recipient_filter(user_id),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, notification: Notification) -> Notification:
        self._session.add(notification)
        await self._session.commit()
        await self._session.refresh(notification)
        return notification

    async def mark_read(self, notification: Notification) -> Notification:
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(timezone.utc)
            notification.status = NotificationStatus.READ
            await self._session.commit()
            await self._session.refresh(notification)
        return notification

    async def mark_all_read(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        items, _ = await self.list_for_user(
            organization_id, user_id, skip=0, limit=500, unread_only=True
        )
        now = datetime.now(timezone.utc)
        for n in items:
            n.is_read = True
            n.read_at = now
            n.status = NotificationStatus.READ
        if items:
            await self._session.commit()
        return len(items)

    async def soft_delete(self, notification: Notification) -> None:
        notification.is_deleted = True
        await self._session.commit()
