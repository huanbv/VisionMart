"""ORM models for the Catalog bounded context."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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


class Category(Entity):
    """Hierarchical product taxonomy (self-referential tree)."""

    __tablename__ = "categories"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    parent: Mapped["Category | None"] = relationship(
        remote_side="Category.id", back_populates="children", lazy="raise"
    )
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent", lazy="raise"
    )

    __table_args__ = (UniqueConstraint("organization_id", "slug"),)


class Product(Entity):
    """Sellable item. Unit price is stored on the product; promotions are separate."""

    __tablename__ = "products"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=0, server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="VND", server_default="VND"
    )
    # Promoted out of `attributes` into real columns because the SKU
    # matcher and the OCR stage query them: brand narrows lookalike
    # candidates ("Aquafina" vs "Lavie" share a bottle silhouette), and
    # volume is the field OCR can actually read off a label to break the
    # remaining tie ("500ml" vs "1.5L" of the same brand).
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    volume_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (UniqueConstraint("organization_id", "sku"),)
