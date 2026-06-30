"""Pydantic schemas for the Notification bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.notification.infrastructure.models import (
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
)


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    recipient_user_id: uuid.UUID | None
    recipient_role_id: uuid.UUID | None
    channel: NotificationChannel
    type: str
    title: str
    body: str | None
    payload: dict | None
    priority: NotificationPriority
    status: NotificationStatus
    sent_at: datetime | None
    read_at: datetime | None
    is_read: bool
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    skip: int
    limit: int
    unread: int


class UnreadCountResponse(BaseModel):
    unread: int


class MarkAllReadResponse(BaseModel):
    updated: int


class NotificationCreate(BaseModel):
    type: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=255)
    body: str | None = None
    recipient_user_id: uuid.UUID | None = None
    recipient_role_id: uuid.UUID | None = None
    channel: NotificationChannel = NotificationChannel.IN_APP
    priority: NotificationPriority = NotificationPriority.NORMAL
    payload: dict | None = None
