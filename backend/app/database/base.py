"""SQLAlchemy declarative base shared by every ORM model.

A consistent naming convention is mandatory so Alembic produces deterministic
constraint names (no random hashes), which keeps migrations diff-friendly.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root declarative base. All ORM models must inherit from `Base` or `Entity`."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
