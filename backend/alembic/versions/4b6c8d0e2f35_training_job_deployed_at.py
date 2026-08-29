"""add deployed_at to ai_training_jobs (regression gate baseline)

Revision ID: 4b6c8d0e2f35
Revises: 3a5b7c9d1e24
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4b6c8d0e2f35"
down_revision = "3a5b7c9d1e24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_training_jobs",
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The gate looks up "most recently deployed job for this org/branch"
    # on every deploy, so index the column it filters and orders by.
    op.create_index(
        "ix_ai_training_jobs_deployed_at",
        "ai_training_jobs",
        ["organization_id", "deployed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_training_jobs_deployed_at", table_name="ai_training_jobs")
    op.drop_column("ai_training_jobs", "deployed_at")
