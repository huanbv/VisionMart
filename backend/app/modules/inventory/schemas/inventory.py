"""Pydantic schemas for the Inventory bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.inventory.infrastructure.models import StockMovementType


class InventoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    branch_id: uuid.UUID
    quantity: int
    reserved_quantity: int
    reorder_level: int
    last_stock_check_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InventoryResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    branch_id: uuid.UUID
    branch_name: str
    quantity: int
    reserved_quantity: int
    available_quantity: int
    reorder_level: int
    low_stock: bool
    last_stock_check_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InventoryListResponse(BaseModel):
    items: list[InventoryResponse]
    total: int
    skip: int
    limit: int


class AdjustRequest(BaseModel):
    product_id: uuid.UUID
    branch_id: uuid.UUID
    delta: int = Field(..., description="Positive to add, negative to remove")
    movement_type: StockMovementType = StockMovementType.ADJUST
    reason: str | None = Field(default=None, max_length=255)
    reference: str | None = Field(default=None, max_length=120)


class TransferRequest(BaseModel):
    product_id: uuid.UUID
    from_branch_id: uuid.UUID
    to_branch_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    reason: str | None = Field(default=None, max_length=255)
    reference: str | None = Field(default=None, max_length=120)


class ReorderLevelUpdate(BaseModel):
    reorder_level: int = Field(..., ge=0)


class StockMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    branch_id: uuid.UUID
    movement_type: StockMovementType
    delta: int
    quantity_after: int
    reason: str | None
    reference: str | None
    performed_by: uuid.UUID | None
    created_at: datetime


class StockMovementListResponse(BaseModel):
    items: list[StockMovementResponse]
    total: int
    skip: int
    limit: int
