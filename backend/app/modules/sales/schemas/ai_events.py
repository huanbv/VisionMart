"""Schemas for AI Engine → backend cart events.

Per docs/26_CART_ENGINE.md: AI never writes to cart/inventory tables directly.
It emits proposals that the backend validates, deduplicates, and applies.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AICartEventType(str, Enum):
    PRODUCT_PICKED_UP = "product_picked_up"
    PRODUCT_RETURNED = "product_returned"
    CHECKOUT_INITIATED = "checkout_initiated"
    # Chế độ quầy thanh toán: sản phẩm đặt trước camera quầy, thêm thẳng vào
    # đơn không cần ghép người. Xử lý giống PRODUCT_PICKED_UP (đều thêm một
    # dòng hàng), chỉ khác nguồn phát — nên tái dùng cùng handler.
    PRODUCT_SCANNED = "product_scanned"


class AICartEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, max_length=80)
    event_type: AICartEventType
    organization_id: uuid.UUID
    branch_id: uuid.UUID
    camera_id: uuid.UUID | None = None
    track_id: str = Field(..., min_length=1, max_length=80)
    product_id: uuid.UUID | None = None
    product_sku: str | None = Field(default=None, max_length=80)
    quantity: int = Field(default=1, gt=0, le=20)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    customer_id: uuid.UUID | None = None
    customer_photo_key: str | None = Field(default=None, max_length=512)
    occurred_at: datetime | None = None


class AICartEventResponse(BaseModel):
    accepted: bool
    reason: str | None = None
    cart_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
