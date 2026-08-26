"""add cropped_at to ai_label_images

Revision ID: d4e6f8a0b123
Revises: c9d3e5f2b014
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4e6f8a0b123"
down_revision = "c9d3e5f2b014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {c["name"] for c in insp.get_columns("ai_label_images")}
    if "cropped_at" not in existing:
        op.add_column(
            "ai_label_images",
            sa.Column("cropped_at", sa.DateTime(timezone=True), nullable=True),
        )
    # Ảnh đã gán nhãn trước khi có luồng cắt — coi như đã xử lý.
    op.execute(
        """
        UPDATE ai_label_images AS li
        SET cropped_at = li.created_at
        WHERE li.cropped_at IS NULL
          AND EXISTS (
            SELECT 1 FROM ai_label_boxes AS lb
            WHERE lb.label_image_id = li.id AND lb.deleted_at IS NULL
          )
        """
    )


def downgrade() -> None:
    op.drop_column("ai_label_images", "cropped_at")
