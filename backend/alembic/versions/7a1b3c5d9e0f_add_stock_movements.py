"""add stock_movements table

Revision ID: 7a1b3c5d9e0f
Revises: 6fa79a26c4de
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "7a1b3c5d9e0f"
down_revision = "6fa79a26c4de"
branch_labels = None
depends_on = None


movement_enum = postgresql.ENUM(
    "in",
    "out",
    "adjust",
    "transfer_in",
    "transfer_out",
    name="stock_movement_type",
    create_type=False,
)


def upgrade() -> None:
    movement_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("movement_type", movement_enum, nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("performed_by", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["performed_by"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_stock_movements_organization_id",
        "stock_movements",
        ["organization_id"],
    )
    op.create_index(
        "ix_stock_movements_product_id", "stock_movements", ["product_id"]
    )
    op.create_index(
        "ix_stock_movements_branch_id", "stock_movements", ["branch_id"]
    )
    op.create_index(
        "ix_stock_movements_performed_by",
        "stock_movements",
        ["performed_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_stock_movements_performed_by", table_name="stock_movements")
    op.drop_index("ix_stock_movements_branch_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_product_id", table_name="stock_movements")
    op.drop_index(
        "ix_stock_movements_organization_id", table_name="stock_movements"
    )
    op.drop_table("stock_movements")
    movement_enum.drop(op.get_bind(), checkfirst=True)
