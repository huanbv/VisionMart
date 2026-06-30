"""Pydantic schemas for Category."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CategoryResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None
    parent_unset: bool = False
    is_active: bool | None = None
