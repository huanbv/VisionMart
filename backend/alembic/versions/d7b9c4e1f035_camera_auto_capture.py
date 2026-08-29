"""add auto_capture_enabled to cameras

Revision ID: d7b9c4e1f035
Revises: c6a8b3d0e924
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d7b9c4e1f035"
down_revision = "c6a8b3d0e924"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "auto_capture_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "auto_capture_enabled")
