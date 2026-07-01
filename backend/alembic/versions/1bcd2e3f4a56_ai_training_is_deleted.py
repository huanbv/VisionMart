"""add is_deleted column to ai training tables

Revision ID: 1bcd2e3f4a56
Revises: 0abc1d2e3f45
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "1bcd2e3f4a56"
down_revision = "0abc1d2e3f45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("ai_training_images", "ai_training_jobs"):
        op.add_column(
            table,
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
        op.create_index(
            f"ix_{table}_is_deleted", table, ["is_deleted"]
        )


def downgrade() -> None:
    for table in ("ai_training_images", "ai_training_jobs"):
        op.drop_index(f"ix_{table}_is_deleted", table_name=table)
        op.drop_column(table, "is_deleted")
