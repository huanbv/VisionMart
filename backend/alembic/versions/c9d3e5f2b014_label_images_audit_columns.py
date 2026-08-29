"""add audit columns to label tables (fix incomplete initial migration)

Revision ID: c9d3e5f2b014
Revises: b8c2e4f1a901
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9d3e5f2b014"
down_revision = "b8c2e4f1a901"
branch_labels = None
depends_on = None

_TABLES = ("ai_label_images", "ai_label_boxes")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in _TABLES:
        existing = {c["name"] for c in insp.get_columns(table)}
        if "created_by" not in existing:
            op.add_column(table, sa.Column("created_by", sa.UUID(), nullable=True))
        if "updated_by" not in existing:
            op.add_column(table, sa.Column("updated_by", sa.UUID(), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "updated_by")
        op.drop_column(table, "created_by")
