"""add gen_random_uuid() default to stock_movements.id

The `7a1b3c5d9e0f_add_stock_movements` migration created the primary key
without a `DEFAULT gen_random_uuid()`, so SQLAlchemy inserts (which omit
the id column and expect the server default to fill it) fail with a NOT
NULL violation. This migration adds the missing default.

Revision ID: a4e6f8b1c703
Revises: 9c3d5e7f2a13
Create Date: 2026-07-01
"""

from __future__ import annotations

from alembic import op

revision = "a4e6f8b1c703"
down_revision = "9c3d5e7f2a13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute(
        "ALTER TABLE stock_movements "
        "ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE stock_movements ALTER COLUMN id DROP DEFAULT")
