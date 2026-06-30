"""Pydantic schemas for the Organization resource."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    settings: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    settings: dict | None = None
