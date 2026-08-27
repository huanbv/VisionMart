"""ORM models for the Sales bounded context."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.entity import Entity
from app.database.types import JSONBType, UUIDType


# --------------------------------------------------------------
# Enums
# --------------------------------------------------------------
class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class CartStatus(str, enum.Enum):
    ACTIVE = "active"
    ABANDONED = "abandoned"
    CONVERTED = "converted"
    # AI detected checkout_initiated (or staff pressed checkout on an
    # AI cart): bill is frozen, nothing charged yet. Waiting for the
    # customer to confirm via QR, or staff to confirm on their behalf.
    PENDING_CHECKOUT = "pending_checkout"


class CartSource(str, enum.Enum):
    AI_VISION = "ai_vision"
    MANUAL = "manual"
    MOBILE_APP = "mobile_app"


# --------------------------------------------------------------
# Aggregates
# --------------------------------------------------------------
class ShoppingCart(Entity):
    """A cart in progress. AI Engine writes items as detections are made."""

    __tablename__ = "shopping_carts"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 150, không phải 80: session_id được ghép "cam:{camera_uuid}:track:
    # {track_id}", mà track_id từ pipeline lại chứa thêm một camera_uuid —
    # nên chuỗi mang tối đa hai UUID (mỗi cái 36 ký tự) cộng tiền tố, vượt
    # 80 và làm INSERT giỏ hàng vỡ. 150 đủ dư cho cả hai UUID.
    session_id: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    # Key MinIO của ảnh crop người (chủ giỏ hàng) do ai-engine chụp lúc gán
    # chủ sở hữu cho sản phẩm đầu tiên (xem frame.py — nhánh checkout, bước
    # ghép chủ sở hữu). NULL nếu giỏ tạo trước khi có tính năng này, hoặc
    # nếu không xác định được người (session checkout-noperson-*).
    customer_photo_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Ảnh still Tải ảnh / Chụp & Quét đã vẽ box + tên sản phẩm. NULL với
    # giỏ live camera (không có một khung nguồn) hoặc giỏ tạo trước cột này.
    scan_photo_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[CartStatus] = mapped_column(
        SAEnum(CartStatus, name="cart_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CartStatus.ACTIVE,
        server_default=CartStatus.ACTIVE.value,
    )
    source: Mapped[CartSource] = mapped_column(
        SAEnum(CartSource, name="cart_source", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CartSource.AI_VISION,
        server_default=CartSource.AI_VISION.value,
    )
    items: Mapped[list | None] = mapped_column(JSONBType, nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=0, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="VND", server_default="VND"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Opaque, unguessable credential for the customer-facing confirm page
    # (`GET/POST /shop/checkout/{token}`). Only set while status is
    # PENDING_CHECKOUT; the QR code shown at the checkout zone encodes a URL
    # containing this token. Not a customer identity — just proof "the
    # person confirming is looking at this specific bill".
    checkout_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    checkout_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Order(Entity):
    """A confirmed sale. Once `status` reaches PAID it is treated as immutable."""

    __tablename__ = "orders"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cart_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("shopping_carts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=OrderStatus.PENDING,
        server_default=OrderStatus.PENDING.value,
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=0, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="VND", server_default="VND"
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_gateway: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(40), nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="raise"
    )

    __table_args__ = (UniqueConstraint("organization_id", "code"),)


class OrderItem(Entity):
    """Single line in an Order. Captures price at the moment of sale."""

    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=0, server_default="0"
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items", lazy="raise")
