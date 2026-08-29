"""add missing audit/soft-delete columns to stock_movements

The original `7a1b3c5d9e0f_add_stock_movements` migration forgot the
`deleted_at`, `created_by`, `updated_by` columns inherited from
`Entity` (SoftDeleteMixin + AuditMixin). This migration adds them so
inserts against the table succeed.

Revision ID: 9c3d5e7f2a13
Revises: 8b2c4d6e1f02
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9c3d5e7f2a13"
down_revision = "8b2c4d6e1f02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stock_movements") as batch:
        batch.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("created_by", sa.UUID(), nullable=True))
        batch.add_column(sa.Column("updated_by", sa.UUID(), nullable=True))
    op.create_index(
        "ix_stock_movements_deleted_at",
        "stock_movements",
        ["deleted_at"],
    )
    op.create_index(
        "ix_stock_movements_is_deleted",
        "stock_movements",
        ["is_deleted"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_stock_movements_is_deleted", table_name="stock_movements"
    )
    op.drop_index(
        "ix_stock_movements_deleted_at", table_name="stock_movements"
    )
    with op.batch_alter_table("stock_movements") as batch:
        batch.drop_column("updated_by")
        batch.drop_column("created_by")
        batch.drop_column("deleted_at")
