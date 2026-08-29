"""widen shopping_carts.session_id 80 -> 150

Revision ID: 7e9f1b3d5a68
Revises: 6d8e0a2b4c57
Create Date: 2026-07-24

Vì sao
------
``session_id`` được backend dựng là ``cam:{camera_uuid}:track:{track_id}``,
mà ``track_id`` từ pipeline ai-engine lại chứa thêm một ``camera_uuid``.
Chuỗi kết quả mang tối đa hai UUID (36 ký tự mỗi cái) cộng tiền tố, vượt
giới hạn cũ 80 ký tự và khiến INSERT giỏ hàng ném
StringDataRightTruncationError — đơn hàng AI không tạo được.

Chỉ nới rộng cột, không đổi dữ liệu: mọi giá trị cũ vẫn hợp lệ, nên có
thể áp dụng an toàn trên production đang chạy.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7e9f1b3d5a68"
down_revision = "6d8e0a2b4c57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "shopping_carts",
        "session_id",
        existing_type=sa.String(length=80),
        type_=sa.String(length=150),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Có thể cắt cụt dữ liệu nếu đã tồn tại session_id dài hơn 80; chỉ hạ
    # khi chắc chắn không có. Để đúng đối xứng vẫn khai báo.
    op.alter_column(
        "shopping_carts",
        "session_id",
        existing_type=sa.String(length=150),
        type_=sa.String(length=80),
        existing_nullable=True,
    )
