"""ORM models for the Customer bounded context."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.entity import Entity
from app.database.types import JSONBType, UUIDType


class Customer(Entity):
    """End-shopper. May be linked to a User (loyalty) or anonymous (visitor)."""

    __tablename__ = "customers"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("branches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    # External reference (e.g. vector-DB id) for face/body embeddings.
    face_embedding_ref: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    attributes: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
