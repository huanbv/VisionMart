"""ORM models for the AI training context."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
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


class ReviewCandidate(Entity):
    """A frame flagged for human review, feeding the active-learning loop.

    The point of active learning here is to retrain on the cases the model
    got *wrong or was unsure about*, which is where new labels are worth
    the most — not on frames it already handles confidently.

    Crucially, a candidate only becomes training data after a human
    confirms the label (``status='approved'`` writes a ``TrainingImage``).
    Feeding the model's own predictions back in unreviewed would teach it
    its own mistakes and drift a little further every retrain, so the
    human step is a correctness requirement, not a nicety.

    ``source`` records *why* the frame was captured:

    * ``low_confidence``    — detection below the review threshold
    * ``checkout_mismatch`` — a human corrected the AI at checkout, so the
      confirmed line item is a gold-standard label for that frame
    * ``manual``            — an operator flagged it from the UI
    """

    __tablename__ = "ai_review_candidates"
    __table_args__ = (
        Index(
            "ix_ai_review_candidates_org_status",
            "organization_id",
            "status",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("cameras.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # Anh cat rieng vung phat hien (crop). storage_key la khung hinh CO
    # khung do cho nguoi duyet nhin; crop_key moi la thu classifier hoc —
    # huan luyen tren nguyen khung canh se day model ca ke hang, nen nha
    # va chinh cai khung do. Nullable vi ban engine cu khong gui crop.
    crop_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Toa do bbox trong he cua khung da tien xu ly: {"x1","y1","x2","y2"}.
    bbox: Mapped[dict | None] = mapped_column(JSONBType, nullable=True)
    # Captured up-front so approving into a TrainingImage doesn't need to
    # re-read the object just to measure it.
    image_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="low_confidence")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    # What the model thought (may be null when it detected nothing at all).
    predicted_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    predicted_class: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # What the human said. Null while pending; set on approve.
    confirmed_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Set once the approved candidate has been materialised as a
    # TrainingImage, so re-approving can't create duplicates.
    training_image_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("ai_training_images.id", ondelete="SET NULL"), nullable=True
    )


class LabelImage(Entity):
    """Scene image for multi-object bbox labeling (several SKUs per frame)."""

    __tablename__ = "ai_label_images"
    __table_args__ = (
        Index("ix_ai_label_images_org", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    image_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cropped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LabelBox(Entity):
    """YOLO-normalized bbox on a scene image, tied to a product SKU."""

    __tablename__ = "ai_label_boxes"
    __table_args__ = (
        Index("ix_ai_label_boxes_image", "label_image_id"),
    )

    label_image_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("ai_label_images.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    cx: Mapped[float] = mapped_column(Float, nullable=False)
    cy: Mapped[float] = mapped_column(Float, nullable=False)
    w: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)


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
    # When this weight was last pushed live. The most recent non-null value
    # for an org/branch is the baseline the regression gate compares a new
    # candidate against — without it there is no way to tell whether a
    # deploy is an improvement or a silent downgrade.
    deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
