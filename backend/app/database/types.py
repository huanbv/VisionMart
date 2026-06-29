"""Common ORM column types & SQL helpers."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Re-export the canonical Postgres types so models import from one place.
UUIDType = UUID(as_uuid=True)
JSONBType = JSONB()

# `gen_random_uuid()` is provided by the `pgcrypto` extension (created in
# docker/postgres/init.sql).
UUID_DEFAULT_SQL = text("gen_random_uuid()")
