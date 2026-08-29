"""Pydantic schemas for the Sales bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.sales.infrastructure.models import OrderStatus


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    subtotal: Decimal


class OrderSummary(BaseModel):
    id: uuid.UUID
    code: str
    branch_id: uuid.UUID
    branch_name: str
    customer_id: uuid.UUID | None
    status: OrderStatus
    total_amount: Decimal
    currency: str
    paid_at: datetime | None
    created_at: datetime


class OrderListResponse(BaseModel):
    items: list[OrderSummary]
    total: int
    skip: int
    limit: int


class OrderDetail(BaseModel):
    id: uuid.UUID
    code: str
    organization_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None
    employee_id: uuid.UUID | None
    cart_id: uuid.UUID | None
    status: OrderStatus
    total_amount: Decimal
    currency: str
    paid_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]


class OrderLineCreate(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)


class OrderCreate(BaseModel):
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)
    lines: list[OrderLineCreate] = Field(..., min_length=1)
