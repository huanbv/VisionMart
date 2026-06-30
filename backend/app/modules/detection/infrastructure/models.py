"""ORM models for the Detection bounded context (append-only)."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.entity import ImmutableEntity
from app.database.types import JSONBType, UUIDType


class DetectionEvent(ImmutableEntity):
    """One AI inference run against a camera frame."""

    __tablename__ = "detection_events"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    image_width: Mapped[int] = mapped_column(Integer, nullable=False)
    image_height: Mapped[int] = mapped_column(Integer, nullable=False)
    image_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    image_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    detection_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", index=True
    )
    max_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, server_default="0"
    )
    detections: Mapped[list] = mapped_column(JSONBType, nullable=False)
