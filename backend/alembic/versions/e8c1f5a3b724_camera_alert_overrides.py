"""add per-camera alert overrides

Revision ID: e8c1f5a3b724
Revises: d7b9c4e1f035
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e8c1f5a3b724"
down_revision = "d7b9c4e1f035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("alert_classes", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "cameras",
        sa.Column("alert_min_confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "alert_min_confidence")
    op.drop_column("cameras", "alert_classes")
