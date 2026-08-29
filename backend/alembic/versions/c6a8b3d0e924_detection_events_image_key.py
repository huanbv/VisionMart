"""add image_key to detection_events

Revision ID: c6a8b3d0e924
Revises: b5f7a2c9d813
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c6a8b3d0e924"
down_revision = "b5f7a2c9d813"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "detection_events",
        sa.Column("image_key", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("detection_events", "image_key")
