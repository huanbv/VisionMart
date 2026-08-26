"""Pydantic DTOs for the AI training API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TrainingImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    storage_key: str
    image_size_bytes: int
    image_format: str | None
    created_at: datetime
    preview_url: str | None = None


class TrainingImageList(BaseModel):
    items: list[TrainingImageRead]
    total: int


class TrainingJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    product_ids: list[uuid.UUID] = Field(min_length=1)
    branch_id: uuid.UUID | None = None
    epochs: int = Field(default=30, ge=5, le=300)
    image_size: int = Field(default=640, ge=320, le=1280)


class LabeledJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    branch_id: uuid.UUID | None = None
    epochs: int = Field(default=30, ge=5, le=300)
    image_size: int = Field(default=640, ge=320, le=1280)


class TrainingJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: str
    epochs: int
    image_size: int
    branch_id: uuid.UUID | None
    class_map: dict
    metrics: dict | None
    weight_key: str | None
    error_message: str | None
    # Null until this weight has been pushed live; the most recent value
    # across jobs is what the regression gate compares against.
    deployed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    progress: str | None = None
    current_epoch: int | None = None
    total_epochs: int | None = None
    # Chi tiết giai đoạn chuẩn bị dữ liệu. Trước đây bước này chỉ hiện
    # một dòng chữ rồi im lặng cho tới khi bắt đầu huấn luyện, nên người
    # dùng không phân biệt được "đang tải ảnh" với "đã treo".
    stage: str | None = None
    images_total: int | None = None
    images_done: int | None = None
    class_counts: dict[str, int] | None = None
    train_count: int | None = None
    val_count: int | None = None
    started_at_ts: float | None = None
    finished_at_ts: float | None = None


class TrainingJobList(BaseModel):
    items: list[TrainingJobRead]
    total: int
