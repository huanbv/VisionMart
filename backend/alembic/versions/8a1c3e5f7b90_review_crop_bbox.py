"""add crop_key + bbox to ai_review_candidates

Revision ID: 8a1c3e5f7b90
Revises: 7e9f1b3d5a68
Create Date: 2026-07-24

Vì sao
------
Hàng đợi duyệt trước đây chỉ lưu nguyên khung hình: một cảnh có hai sản
phẩm thì người duyệt không biết AI đang hỏi về cái nào, và khi duyệt xong,
nhãn được gán cho CẢ khung cảnh — classifier học từ ảnh nguyên cảnh (kệ
hàng, nền nhà) thay vì sản phẩm.

Hai cột mới sửa cả hai:

* ``crop_key`` — ảnh cắt riêng vùng phát hiện. Đây mới là thứ đi vào tập
  huấn luyện khi duyệt (khung hình giờ có khung đỏ vẽ chồng, tuyệt đối
  không được học từ nó).
* ``bbox`` — toạ độ vùng phát hiện trong hệ của khung đã tiền xử lý, giữ
  lại để sau này có thể vẽ lại/kiểm tra mà không phụ thuộc ảnh đã ghi.

Chỉ thêm cột nullable — bản ghi cũ và engine cũ (không gửi crop) vẫn hợp
lệ, áp dụng an toàn trên production đang chạy.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8a1c3e5f7b90"
down_revision = "7e9f1b3d5a68"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_review_candidates",
        sa.Column("crop_key", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "ai_review_candidates",
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_review_candidates", "bbox")
    op.drop_column("ai_review_candidates", "crop_key")
