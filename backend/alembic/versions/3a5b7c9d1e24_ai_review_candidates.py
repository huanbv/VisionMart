"""add ai_review_candidates table (active-learning review queue)

Revision ID: 3a5b7c9d1e24
Revises: 2f4a6c8e0b13
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "3a5b7c9d1e24"
down_revision = "2f4a6c8e0b13"
branch_labels = None
depends_on = None


def _common_columns() -> list[sa.Column]:
    """Same audit/soft-delete column set the other Entity tables use
    (see 0abc1d2e3f45 + 1bcd2e3f4a56, folded together here)."""
    return [
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_review_candidates",
        *_common_columns(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column(
            "image_size_bytes", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'low_confidence'"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("predicted_product_id", sa.UUID(), nullable=True),
        sa.Column("predicted_class", sa.String(length=128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("confirmed_product_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("training_image_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["predicted_product_id"], ["products.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_product_id"], ["products.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["training_image_id"], ["ai_training_images.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_ai_review_candidates_organization_id",
        "ai_review_candidates",
        ["organization_id"],
    )
    op.create_index(
        "ix_ai_review_candidates_camera_id", "ai_review_candidates", ["camera_id"]
    )
    op.create_index(
        "ix_ai_review_candidates_is_deleted", "ai_review_candidates", ["is_deleted"]
    )
    # The review queue is always read as "pending items for this org".
    op.create_index(
        "ix_ai_review_candidates_org_status",
        "ai_review_candidates",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_review_candidates_org_status", table_name="ai_review_candidates")
    op.drop_index("ix_ai_review_candidates_is_deleted", table_name="ai_review_candidates")
    op.drop_index("ix_ai_review_candidates_camera_id", table_name="ai_review_candidates")
    op.drop_index(
        "ix_ai_review_candidates_organization_id", table_name="ai_review_candidates"
    )
    op.drop_table("ai_review_candidates")
