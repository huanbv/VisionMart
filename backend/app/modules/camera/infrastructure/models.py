"""ORM models for the Camera bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.entity import Entity
from app.database.types import JSONBType, UUIDType


class Camera(Entity):
    """A physical camera attached to a branch. Streams are consumed by AI Engine."""

    __tablename__ = "cameras"

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
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    stream_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    is_online: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    auto_capture_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (UniqueConstraint("organization_id", "code"),)
