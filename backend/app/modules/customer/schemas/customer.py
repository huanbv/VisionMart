"""Pydantic schemas for the Customer bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    branch_id: uuid.UUID | None
    full_name: str | None
    email: str | None
    phone: str | None
    face_embedding_ref: str | None
    attributes: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
    total: int
    skip: int
    limit: int


class CustomerCreate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    branch_id: uuid.UUID | None = None
    attributes: dict | None = None
    is_active: bool = True


class CustomerUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    branch_id: uuid.UUID | None = None
    attributes: dict | None = None
    is_active: bool | None = None

    full_name_unset: bool = False
    email_unset: bool = False
    phone_unset: bool = False
    branch_unset: bool = False
    attributes_unset: bool = False


class CustomerStats(BaseModel):
    customer_id: uuid.UUID
    order_count: int
    total_spent: Decimal
