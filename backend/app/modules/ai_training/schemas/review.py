"""Schemas for the active-learning review queue."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReviewCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    camera_id: uuid.UUID | None = None
    storage_key: str
    image_size_bytes: int = 0
    source: str
    status: str
    predicted_product_id: uuid.UUID | None = None
    predicted_class: str | None = None
    confidence: float | None = None
    confirmed_product_id: uuid.UUID | None = None
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    training_image_id: uuid.UUID | None = None
    created_at: datetime

    crop_key: str | None = None
    bbox: dict | None = None

    # Filled by the router, not stored.
    preview_url: str | None = None
    crop_preview_url: str | None = None


class ReviewCandidateList(BaseModel):
    items: list[ReviewCandidateRead]
    total: int


class ReviewStats(BaseModel):
    pending: int = 0
    approved: int = 0
    rejected: int = 0


class ApproveCandidatePayload(BaseModel):
    """Approving requires the confirmed label — that human decision is the
    entire value of the queue, so it is never inferred from the model's own
    prediction."""

    confirmed_product_id: uuid.UUID
    note: str | None = Field(default=None, max_length=500)


class RejectCandidatePayload(BaseModel):
    note: str | None = Field(default=None, max_length=500)
