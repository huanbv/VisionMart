"""Pydantic schemas for the Dashboard bounded context."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class CameraSummary(BaseModel):
    total: int
    online: int
    active: int


class SalesBucket(BaseModel):
    orders: int
    revenue: Decimal


class DashboardSummary(BaseModel):
    today: SalesBucket
    last_7_days: SalesBucket
    last_30_days: SalesBucket
    customers_total: int
    customers_new_7d: int
    products_total: int
    low_stock_count: int
    cameras: CameraSummary
    employees_active: int
    branches_count: int


class SalesTrendPoint(BaseModel):
    date: date
    orders: int
    revenue: Decimal


class SalesTrendResponse(BaseModel):
    days: int
    points: list[SalesTrendPoint]


class TopProduct(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    quantity: int
    revenue: Decimal


class TopProductsResponse(BaseModel):
    days: int
    items: list[TopProduct]


class LowStockItem(BaseModel):
    inventory_id: uuid.UUID
    sku: str
    product_name: str
    branch_name: str
    quantity: int
    reserved_quantity: int
    reorder_level: int


class LowStockResponse(BaseModel):
    items: list[LowStockItem]


class RecentOrder(BaseModel):
    id: uuid.UUID
    code: str
    branch_name: str
    status: str
    total_amount: Decimal
    created_at: datetime


class RecentOrdersResponse(BaseModel):
    items: list[RecentOrder]
