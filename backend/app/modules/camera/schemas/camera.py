"""Pydantic schemas for the Camera bounded context."""

from __future__ import annotations

from typing import Literal

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RoiZonePayload(BaseModel):
    """Mot vung nhan dien ve tren Admin.

    ``points`` la toa do PHAN SO (0-1) theo chieu rong/cao khung hinh, nen
    vung ve mot lan dung duoc cho moi do phan giai camera.
    """

    name: str = Field(..., min_length=1, max_length=60)
    type: Literal["entrance", "shelf", "checkout", "exit"] = "checkout"
    points: list[tuple[float, float]] = Field(..., min_length=3)

    @field_validator("points")
    @classmethod
    def _fractional(cls, v: list[tuple[float, float]]):
        # Chan toa do pixel bi gui nham vao day: mot vung [[640,360],...]
        # se im lang bien thanh mask rong (fillPoly ngoai khung) va camera
        # "mu" ma khong bao loi gi.
        for x, y in v:
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError(
                    "points phai la toa do phan so 0-1 (khong phai pixel)"
                )
        return v


class RoiZonesUpdate(BaseModel):
    zones: list[RoiZonePayload] = Field(default_factory=list, max_length=20)


class CameraResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    roi_zones: list | None = None

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
    auto_capture_enabled: bool
    alert_classes: str | None
    alert_min_confidence: float | None
    is_checkout_zone: bool = False
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
    auto_capture_enabled: bool = False
    alert_classes: str | None = Field(default=None, max_length=255)
    alert_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_checkout_zone: bool = False


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
    auto_capture_enabled: bool | None = None
    alert_classes: str | None = Field(default=None, max_length=255)
    alert_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_checkout_zone: bool | None = None

    location_unset: bool = False
    resolution_unset: bool = False
    fps_unset: bool = False
    config_unset: bool = False
    alert_classes_unset: bool = False
    alert_min_confidence_unset: bool = False


class CameraHeartbeat(BaseModel):
    online: bool = True


class CameraStats(BaseModel):
    total: int
    online: int
    active: int
