"""Application services for the Notification bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.core.exceptions import NotFoundError, ValidationError
from app.modules.notification.infrastructure.models import (
    Notification,
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)
from app.modules.notification.infrastructure.repositories import (
    SqlAlchemyNotificationRepository,
)


class NotificationService:
    def __init__(self, repository: SqlAlchemyNotificationRepository) -> None:
        self._repo = repository

    async def list(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
        unread_only: bool,
    ) -> tuple[list[Notification], int]:
        return await self._repo.list_for_user(
            organization_id,
            user_id,
            skip=skip,
            limit=limit,
            unread_only=unread_only,
        )

    async def unread_count(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        return await self._repo.unread_count(organization_id, user_id)

    async def mark_read(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> Notification:
        n = await self._repo.get_for_user(
            organization_id, user_id, notification_id
        )
        if n is None:
            raise NotFoundError("Notification not found")
        return await self._repo.mark_read(n)

    async def mark_all_read(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> int:
        return await self._repo.mark_all_read(organization_id, user_id)

    async def delete(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> None:
        n = await self._repo.get_for_user(
            organization_id, user_id, notification_id
        )
        if n is None:
            raise NotFoundError("Notification not found")
        await self._repo.soft_delete(n)

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        type: str,
        title: str,
        body: str | None,
        recipient_user_id: uuid.UUID | None,
        recipient_role_id: uuid.UUID | None,
        channel: NotificationChannel = NotificationChannel.IN_APP,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        payload: dict | None = None,
    ) -> Notification:
        if recipient_user_id is None and recipient_role_id is None:
            raise ValidationError(
                "Either recipient_user_id or recipient_role_id is required"
            )
        n = Notification(
            organization_id=organization_id,
            recipient_user_id=recipient_user_id,
            recipient_role_id=recipient_role_id,
            channel=channel,
            type=type,
            title=title,
            body=body,
            payload=payload,
            priority=priority,
            status=NotificationStatus.SENT,
            sent_at=datetime.now(timezone.utc),
        )
        return await self._repo.add(n)
