"""ORM models for the Audit bounded context (append-only)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.entity import ImmutableEntity
from app.database.types import JSONBType, UUIDType


class AuditLog(ImmutableEntity):
    """Immutable audit record. Written via the service layer / domain events."""

    __tablename__ = "audit_logs"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    old_values: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    new_values: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
