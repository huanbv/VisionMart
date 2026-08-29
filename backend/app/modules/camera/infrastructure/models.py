"""ORM models for the Camera bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
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
    alert_classes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    alert_min_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    is_checkout_zone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Vung nhan dien ve tren Admin. Dang:
    #   [{"name": "quay", "type": "checkout",
    #     "points": [[0.1,0.2],[0.9,0.2],[0.9,0.8],[0.1,0.8]]}]
    # Toa do la PHAN SO (0-1) chu khong phai pixel: cung mot vung dung
    # duoc cho moi do phan giai, va doi camera sang 4K khong lam vung ve
    # trươt di. ai-engine doc truc tiep tu day (qua /ai/cameras/{id}) nen
    # nguoi dung keo chuot xong la co hieu luc trong 30 giay (thoi han
    # cache camera), khong can restart hay sua file YAML.
    roi_zones: Mapped[list | None] = mapped_column(JSONBType, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (UniqueConstraint("organization_id", "code"),)
