"""add customer_photo_key to shopping_carts

Revision ID: a3f7d1c9b246
Revises: 9b2d4f6a8c13
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a3f7d1c9b246"
down_revision = "9b2d4f6a8c13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shopping_carts",
        sa.Column("customer_photo_key", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shopping_carts", "customer_photo_key")
