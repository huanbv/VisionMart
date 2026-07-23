"""add brand / volume_ml / weight_g to products (SKU matching + OCR)

Revision ID: 5c7d9e1f3a46
Revises: 4b6c8d0e2f35
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5c7d9e1f3a46"
down_revision = "4b6c8d0e2f35"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # All nullable: existing rows stay valid and nothing has to be
    # backfilled before this migration can run.
    op.add_column("products", sa.Column("brand", sa.String(length=120), nullable=True))
    op.add_column("products", sa.Column("volume_ml", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("weight_g", sa.Integer(), nullable=True))
    # The matcher filters candidates by brand, so it is worth an index;
    # volume/weight are only read once a row is already selected.
    op.create_index("ix_products_brand", "products", ["brand"])


def downgrade() -> None:
    op.drop_index("ix_products_brand", table_name="products")
    op.drop_column("products", "weight_g")
    op.drop_column("products", "volume_ml")
    op.drop_column("products", "brand")
