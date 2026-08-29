"""Pydantic schemas for the Branch resource."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BranchResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    code: str
    address: dict | None
    timezone: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BranchListResponse(BaseModel):
    items: list[BranchResponse]
    total: int
    skip: int
    limit: int


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=40)
    address: dict | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    is_active: bool = True


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=40)
    address: dict | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None
