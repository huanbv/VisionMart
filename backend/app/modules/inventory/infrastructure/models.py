"""ORM models for the Inventory bounded context."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.entity import Entity
from app.database.types import UUIDType


class StockMovementType(str, enum.Enum):
    IN = "in"
    OUT = "out"
    ADJUST = "adjust"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"


class Inventory(Entity):
    """Stock level for one Product at one Branch."""

    __tablename__ = "inventory"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    reserved_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    reorder_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_stock_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("product_id", "branch_id"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_non_negative"),
        CheckConstraint("reorder_level >= 0", name="reorder_non_negative"),
    )


class StockMovement(Entity):
    """Immutable audit record of a single stock change."""

    __tablename__ = "stock_movements"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("branches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    movement_type: Mapped[StockMovementType] = mapped_column(
        SAEnum(
            StockMovementType,
            name="stock_movement_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    performed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
