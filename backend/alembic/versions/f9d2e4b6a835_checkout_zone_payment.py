"""camera checkout zone + order payment fields

Revision ID: f9d2e4b6a835
Revises: e8c1f5a3b724
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f9d2e4b6a835"
down_revision = "e8c1f5a3b724"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "is_checkout_zone",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column("payment_reference", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("payment_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("payment_gateway", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "payment_gateway")
    op.drop_column("orders", "payment_status")
    op.drop_column("orders", "payment_reference")
    op.drop_column("cameras", "is_checkout_zone")
