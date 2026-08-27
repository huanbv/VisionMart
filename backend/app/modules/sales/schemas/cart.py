"""Pydantic schemas for the Shopping Cart aggregate."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.sales.infrastructure.models import CartSource, CartStatus


class CartLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    line_id: str
    product_id: uuid.UUID
    sku: str
    product_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal
    added_via: str
    source_event_id: str | None = None
    # AI's detection confidence for this pickup (1.0 for manually-added
    # lines). Never guaranteed-correct — see CartResponse.overall_confidence
    # and Principle 2: every AI prediction is probabilistic.
    confidence: float = 1.0
    added_at: datetime
    # True khi ai-engine đã lưu crop cận cảnh lúc detect. Frontend gọi
    # GET /carts/{id}/lines/{line_id}/photo — không trả MinIO key ra ngoài.
    has_photo: bool = False


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
    # Value-weighted average of line confidences — a quick "should staff
    # double-check this before confirming?" signal. Not persisted; computed
    # fresh from `lines` each time (see cart_service.compute_overall_confidence).
    overall_confidence: float = 1.0
    # True nếu ai-engine đã chụp được ảnh chủ giỏ hàng (xem
    # frame.py::process_frame nhánh checkout) — không trả thẳng
    # customer_photo_key (MinIO key nội bộ) ra ngoài, frontend gọi
    # GET /carts/{id}/customer-photo khi cần hiển thị.
    has_customer_photo: bool = False
    # True khi giỏ sinh từ Tải ảnh / Chụp & Quét đã lưu still có nhãn SP.
    # Frontend gọi GET /carts/{id}/scan-photo — không trả MinIO key.
    has_scan_photo: bool = False
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


class CartCheckoutQrResponse(BaseModel):
    """For the staff-facing checkout-zone screen: the confirm link + a
    ready-to-render SVG QR code encoding it."""

    cart_id: uuid.UUID
    checkout_token: str
    confirm_url: str
    qr_svg: str
    expires_at: datetime | None


class PublicBillLine(BaseModel):
    product_name: str
    sku: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class PublicBillResponse(BaseModel):
    """What a customer sees after scanning the checkout QR — deliberately
    minimal, no internal ids beyond the cart's own public-facing status."""

    status: CartStatus
    lines: list[PublicBillLine]
    total_amount: Decimal
    currency: str
    checkout_requested_at: datetime | None
    expires_at: datetime | None
    order_code: str | None = None
    paid_at: datetime | None = None


class PublicConfirmResponse(BaseModel):
    order_code: str
    total_amount: Decimal
    currency: str
    paid_at: datetime | None
