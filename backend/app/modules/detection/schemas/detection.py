"""Pydantic schemas for the Detection bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DetectionEventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    camera_id: uuid.UUID
    user_id: uuid.UUID | None
    model: str
    image_width: int
    image_height: int
    image_format: str | None
    image_size_bytes: int
    elapsed_ms: int
    detection_count: int
    max_confidence: float
    created_at: datetime
    image_key: str | None = None


class DetectionEventResponse(DetectionEventSummary):
    detections: list[dict]


class DetectionEventListResponse(BaseModel):
    items: list[DetectionEventSummary]
    total: int
    skip: int = Field(0, ge=0)
    limit: int = Field(50, ge=1)
