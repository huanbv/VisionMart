"""Pydantic schemas for Product."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ProductResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    category_id: uuid.UUID | None
    sku: str
    barcode: str | None
    name: str
    description: str | None
    unit_price: Decimal
    currency: str
    brand: str | None = None
    volume_ml: int | None = None
    weight_g: int | None = None
    attributes: dict | None
    image_url: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductListResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    skip: int
    limit: int


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    category_id: uuid.UUID | None = None
    barcode: str | None = Field(default=None, max_length=80)
    description: str | None = None
    unit_price: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="VND", min_length=3, max_length=3)
    brand: str | None = Field(default=None, max_length=120)
    volume_ml: int | None = Field(default=None, ge=0)
    weight_g: int | None = Field(default=None, ge=0)
    attributes: dict | None = None
    image_url: str | None = Field(default=None, max_length=1024)
    is_active: bool = True


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: uuid.UUID | None = None
    category_unset: bool = False
    barcode: str | None = Field(default=None, max_length=80)
    barcode_unset: bool = False
    description: str | None = None
    description_unset: bool = False
    unit_price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    brand: str | None = Field(default=None, max_length=120)
    brand_unset: bool = False
    volume_ml: int | None = Field(default=None, ge=0)
    weight_g: int | None = Field(default=None, ge=0)
    attributes: dict | None = None
    attributes_unset: bool = False
    image_url: str | None = Field(default=None, max_length=1024)
    image_url_unset: bool = False
    is_active: bool | None = None
