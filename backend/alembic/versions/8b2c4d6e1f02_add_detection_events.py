"""add detection_events table

Revision ID: 8b2c4d6e1f02
Revises: 7a1b3c5d9e0f
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8b2c4d6e1f02"
down_revision = "7a1b3c5d9e0f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.create_table(
        "detection_events",
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
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("image_width", sa.Integer(), nullable=False),
        sa.Column("image_height", sa.Integer(), nullable=False),
        sa.Column("image_format", sa.String(length=16), nullable=True),
        sa.Column("image_size_bytes", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column(
            "detection_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_confidence",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "detections",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["camera_id"], ["cameras.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_detection_events_organization_id",
        "detection_events",
        ["organization_id"],
    )
    op.create_index(
        "ix_detection_events_camera_id",
        "detection_events",
        ["camera_id"],
    )
    op.create_index(
        "ix_detection_events_user_id",
        "detection_events",
        ["user_id"],
    )
    op.create_index(
        "ix_detection_events_model",
        "detection_events",
        ["model"],
    )
    op.create_index(
        "ix_detection_events_detection_count",
        "detection_events",
        ["detection_count"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_detection_events_detection_count", table_name="detection_events"
    )
    op.drop_index("ix_detection_events_model", table_name="detection_events")
    op.drop_index("ix_detection_events_user_id", table_name="detection_events")
    op.drop_index(
        "ix_detection_events_camera_id", table_name="detection_events"
    )
    op.drop_index(
        "ix_detection_events_organization_id", table_name="detection_events"
    )
    op.drop_table("detection_events")
