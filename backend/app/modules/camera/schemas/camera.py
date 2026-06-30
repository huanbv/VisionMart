"""Pydantic schemas for the Camera bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CameraResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    branch_id: uuid.UUID
    branch_name: str | None = None
    code: str
    name: str
    stream_url: str
    location: str | None
    resolution: str | None
    fps: int | None
    config: dict | None
    is_online: bool
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CameraListResponse(BaseModel):
    items: list[CameraResponse]
    total: int
    skip: int
    limit: int


class CameraCreate(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=255)
    branch_id: uuid.UUID
    stream_url: str = Field(min_length=1, max_length=1024)
    location: str | None = Field(default=None, max_length=255)
    resolution: str | None = Field(default=None, max_length=20)
    fps: int | None = Field(default=None, ge=1, le=240)
    config: dict | None = None
    is_active: bool = True


class CameraUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    branch_id: uuid.UUID | None = None
    stream_url: str | None = Field(default=None, min_length=1, max_length=1024)
    location: str | None = None
    resolution: str | None = None
    fps: int | None = Field(default=None, ge=1, le=240)
    config: dict | None = None
    is_active: bool | None = None

    location_unset: bool = False
    resolution_unset: bool = False
    fps_unset: bool = False
    config_unset: bool = False


class CameraHeartbeat(BaseModel):
    online: bool = True


class CameraStats(BaseModel):
    total: int
    online: int
    active: int
