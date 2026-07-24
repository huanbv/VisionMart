"""add roi_zones to cameras (vùng nhận diện vẽ trên Admin)

Revision ID: 9b2d4f6a8c13
Revises: 8a1c3e5f7b90
Create Date: 2026-07-24

Vì sao
------
Pipeline đã có ROI đầy đủ (che pixel ngoài vùng trước khi YOLO chạy),
nhưng nguồn cấu hình duy nhất là một file YAML phải sửa tay rồi deploy —
nên trên thực tế chưa camera nào dùng, và detector "nhìn" cả kệ hàng phía
sau lẫn người qua lại, sinh ra phát hiện không liên quan.

Cột này cho phép vẽ vùng ngay trong Admin và lưu theo từng camera.
ai-engine đọc nó qua ``/ai/cameras/{id}`` — lần gọi mà nó **đã** thực hiện
cho mỗi khung hình và cache 30 giây — nên vùng vẽ xong có hiệu lực trong
vòng 30 giây, không thêm một lượt gọi mạng nào trên đường xử lý.

Toạ độ lưu dạng PHÂN SỐ (0–1) chứ không phải pixel: cùng một vùng dùng
được cho mọi độ phân giải, và đổi camera sang 4K không làm vùng trượt đi.

Chỉ thêm một cột nullable — camera chưa vẽ vùng vẫn chạy y như trước, và
file YAML vẫn là đường dự phòng.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9b2d4f6a8c13"
down_revision = "8a1c3e5f7b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("roi_zones", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "roi_zones")
