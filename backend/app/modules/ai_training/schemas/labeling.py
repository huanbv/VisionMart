"""Schemas for multi-object bbox labeling."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LabelBoxIn(BaseModel):
    product_id: uuid.UUID
    cx: float = Field(ge=0.0, le=1.0)
    cy: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)


class LabelBoxOut(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    cx: float
    cy: float
    w: float
    h: float

    model_config = {"from_attributes": True}


class LabelImageSummary(BaseModel):
    id: uuid.UUID
    storage_key: str
    original_filename: str | None
    image_width: int | None
    image_height: int | None
    box_count: int
    labeled: bool
    is_cropped: bool
    created_at: datetime


class LabelImageDetail(LabelImageSummary):
    preview_url: str
    boxes: list[LabelBoxOut]


class LabelImageListResponse(BaseModel):
    items: list[LabelImageSummary]
    total: int
    labeled_count: int
    pending_count: int


class SaveLabelBoxesRequest(BaseModel):
    boxes: list[LabelBoxIn]


class CropLabelImageRequest(BaseModel):
    """Normalized crop rectangle (0–1) relative to the current image."""

    x1: float = Field(ge=0.0, le=1.0)
    y1: float = Field(ge=0.0, le=1.0)
    x2: float = Field(ge=0.0, le=1.0)
    y2: float = Field(ge=0.0, le=1.0)


class BulkUploadResponse(BaseModel):
    uploaded: int
    failed: int
    items: list[LabelImageSummary]


class LabelingStatsResponse(BaseModel):
    total_images: int
    labeled_images: int
    pending_images: int
    pending_crop: int
    total_boxes: int
    distinct_skus: int
    ready_for_training: bool
    training_message: str | None = None
