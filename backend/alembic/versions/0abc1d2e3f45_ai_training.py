"""add ai training tables

Revision ID: 0abc1d2e3f45
Revises: f9d2e4b6a835
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0abc1d2e3f45"
down_revision = "f9d2e4b6a835"
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
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "ai_training_images",
        *_common_columns(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("image_size_bytes", sa.Integer(), nullable=False),
        sa.Column("image_format", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_ai_training_images_organization_id",
        "ai_training_images",
        ["organization_id"],
    )
    op.create_index(
        "ix_ai_training_images_product_id",
        "ai_training_images",
        ["product_id"],
    )
    op.create_index(
        "ix_ai_training_images_org_product",
        "ai_training_images",
        ["organization_id", "product_id"],
    )

    op.create_table(
        "ai_training_jobs",
        *_common_columns(),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "epochs", sa.Integer(), nullable=False, server_default=sa.text("30")
        ),
        sa.Column(
            "image_size",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("640"),
        ),
        sa.Column(
            "class_map",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("weight_key", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"], ["branches.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_ai_training_jobs_organization_id",
        "ai_training_jobs",
        ["organization_id"],
    )
    op.create_index(
        "ix_ai_training_jobs_branch_id",
        "ai_training_jobs",
        ["branch_id"],
    )
    op.create_index(
        "ix_ai_training_jobs_status",
        "ai_training_jobs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_training_jobs_status", table_name="ai_training_jobs")
    op.drop_index(
        "ix_ai_training_jobs_branch_id", table_name="ai_training_jobs"
    )
    op.drop_index(
        "ix_ai_training_jobs_organization_id", table_name="ai_training_jobs"
    )
    op.drop_table("ai_training_jobs")

    op.drop_index(
        "ix_ai_training_images_org_product", table_name="ai_training_images"
    )
    op.drop_index(
        "ix_ai_training_images_product_id", table_name="ai_training_images"
    )
    op.drop_index(
        "ix_ai_training_images_organization_id",
        table_name="ai_training_images",
    )
    op.drop_table("ai_training_images")
