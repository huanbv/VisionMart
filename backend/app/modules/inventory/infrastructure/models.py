"""ORM models for the Inventory bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.entity import Entity
from app.database.types import UUIDType


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
