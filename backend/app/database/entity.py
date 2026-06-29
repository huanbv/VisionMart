"""Abstract entity bases.

`Entity`           -- audited aggregate root (UUID PK + timestamps + soft-delete + audit).
`ImmutableEntity`  -- append-only rows (e.g. AuditLog) — no soft delete, no updated_at.
`AssociationBase`  -- thin base for pure M2M tables (composite PK).
"""

from __future__ import annotations

from app.database.base import Base
from app.database.mixins import (
    AuditMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Entity(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, AuditMixin):
    """Aggregate root with full audit + soft delete support."""

    __abstract__ = True


class ImmutableEntity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only entity. Suitable for AuditLog and similar event-style tables."""

    __abstract__ = True


class AssociationBase(Base):
    """Thin base for many-to-many association tables (composite primary keys)."""

    __abstract__ = True
