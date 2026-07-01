"""add gen_random_uuid() default to detection_events.id

Same autogen omission as stock_movements: the id primary key was created
without `DEFAULT gen_random_uuid()`, so inserts (which omit the id column
and expect the server default to fill it) fail with a NOT NULL violation.

Revision ID: b5f7a2c9d813
Revises: a4e6f8b1c703
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision = "b5f7a2c9d813"
down_revision = "a4e6f8b1c703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute(
        "ALTER TABLE detection_events "
        "ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE detection_events ALTER COLUMN id DROP DEFAULT")
