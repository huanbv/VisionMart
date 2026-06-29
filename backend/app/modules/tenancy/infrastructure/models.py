"""ORM models for the Tenancy bounded context."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.entity import Entity
from app.database.types import JSONBType, UUIDType


class Organization(Entity):
    """Top-level tenant. All other aggregates live under an organization."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    settings: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)

    branches: Mapped[list["Branch"]] = relationship(
        back_populates="organization", lazy="raise"
    )


class Branch(Entity):
    """A physical store / location belonging to an organization."""

    __tablename__ = "branches"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    address: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    organization: Mapped["Organization"] = relationship(
        back_populates="branches", lazy="raise"
    )

    __table_args__ = (UniqueConstraint("organization_id", "code"),)


class SystemSetting(Entity):
    """Per-tenant (or global if organization_id is null) configuration entries."""

    __tablename__ = "system_settings"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (UniqueConstraint("organization_id", "key"),)
