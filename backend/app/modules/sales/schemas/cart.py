"""Pydantic schemas for the Shopping Cart aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.sales.infrastructure.models import CartSource, CartStatus


class CartLine(BaseModel):
    line_id: str
    product_id: uuid.UUID
    sku: str
    product_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    added_via: str
    source_event_id: str | None = None
    added_at: datetime


class CartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None
    session_id: str | None
    status: CartStatus
    source: CartSource
    total_amount: Decimal
    currency: str
    lines: list[CartLine]
    expires_at: datetime | None
    converted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CartListResponse(BaseModel):
    items: list[CartResponse]
    total: int
    skip: int
    limit: int


class CartCreateRequest(BaseModel):
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    session_id: str | None = Field(default=None, max_length=80)
    source: CartSource = CartSource.AI_VISION


class CartAddLineRequest(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(default=1, gt=0, le=99)
    unit_price: Decimal | None = Field(default=None, ge=0)
    added_via: str = Field(default="manual", max_length=32)
    source_event_id: str | None = Field(default=None, max_length=80)


class CartCheckoutResponse(BaseModel):
    cart_id: uuid.UUID
    order_id: uuid.UUID
    order_code: str
    total_amount: Decimal
    currency: str
