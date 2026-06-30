"""Pydantic response schemas for the Reports bounded context."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class SalesByDayRow(BaseModel):
    day: date
    orders: int
    revenue: Decimal


class SalesByBranchRow(BaseModel):
    branch_id: uuid.UUID
    branch_name: str
    orders: int
    revenue: Decimal


class TopProductRow(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    quantity: int
    revenue: Decimal


class InventoryValuationRow(BaseModel):
    sku: str
    product_name: str
    branch_name: str
    quantity: int
    unit_price: Decimal
    total_value: Decimal


class TopCustomerRow(BaseModel):
    customer_id: uuid.UUID
    full_name: str | None
    phone: str | None
    orders: int
    revenue: Decimal
