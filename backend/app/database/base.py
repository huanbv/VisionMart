"""SQLAlchemy declarative base shared across all ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base class for all ORM models. Models will be added in later sprints."""
