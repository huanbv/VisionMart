"""add polygon to ai_label_boxes

Revision ID: e5f7a9b1c234
Revises: d4e6f8a0b123
Create Date: 2026-08-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5f7a9b1c234"
down_revision = "d4e6f8a0b123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("ai_label_boxes")}
    if "polygon" not in existing:
        op.add_column(
            "ai_label_boxes",
            sa.Column("polygon", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("ai_label_boxes", "polygon")
