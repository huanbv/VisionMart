"""Pydantic schemas for the Audit bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    old_values: dict | None
    new_values: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    skip: int = Field(0, ge=0)
    limit: int = Field(50, ge=1)
