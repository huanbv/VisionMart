"""add scan_photo_key to shopping_carts

Revision ID: f1a3c5e7b902
Revises: e5f7a9b1c234
Create Date: 2026-08-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1a3c5e7b902"
down_revision = "e5f7a9b1c234"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("shopping_carts")}
    if "scan_photo_key" not in existing:
        op.add_column(
            "shopping_carts",
            sa.Column("scan_photo_key", sa.String(length=512), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("shopping_carts")}
    if "scan_photo_key" in existing:
        op.drop_column("shopping_carts", "scan_photo_key")
