"""add bbox labeling tables for multi-object training

Revision ID: b8c2e4f1a901
Revises: a3f7d1c9b246
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8c2e4f1a901"
down_revision = "a3f7d1c9b246"
branch_labels = None
depends_on = None


def _common_columns() -> list[sa.Column]:
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
        "ai_label_images",
        *_common_columns(),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("image_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_format", sa.String(16), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_ai_label_images_org",
        "ai_label_images",
        ["organization_id"],
    )

    op.create_table(
        "ai_label_boxes",
        *_common_columns(),
        sa.Column(
            "label_image_id",
            sa.UUID(),
            sa.ForeignKey("ai_label_images.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.UUID(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cx", sa.Float(), nullable=False),
        sa.Column("cy", sa.Float(), nullable=False),
        sa.Column("w", sa.Float(), nullable=False),
        sa.Column("h", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_ai_label_boxes_image",
        "ai_label_boxes",
        ["label_image_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_label_boxes_image", table_name="ai_label_boxes")
    op.drop_table("ai_label_boxes")
    op.drop_index("ix_ai_label_images_org", table_name="ai_label_images")
    op.drop_table("ai_label_images")
