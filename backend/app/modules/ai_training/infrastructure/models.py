"""ORM models for the AI training context."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.entity import Entity
from app.database.types import JSONBType, UUIDType


class TrainingImage(Entity):
    """A single labelled image uploaded for training one product class."""

    __tablename__ = "ai_training_images"
    __table_args__ = (
        Index(
            "ix_ai_training_images_org_product",
            "organization_id",
            "product_id",
        ),
    )

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
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    image_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    image_format: Mapped[str | None] = mapped_column(String(16), nullable=True)


class TrainingJob(Entity):
    """A training run — turns uploaded images into a deployable YOLO weight."""

    __tablename__ = "ai_training_jobs"

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
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="pending",
        index=True,
    )
    epochs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    image_size: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="640"
    )
    class_map: Mapped[dict] = mapped_column(JSONBType, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    weight_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
