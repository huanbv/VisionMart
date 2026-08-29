"""Dọn dẹp telemetry AI theo thời hạn lưu giữ.

Vì sao xoá telemetry KHÔNG làm mất dữ liệu học
----------------------------------------------
Đây là điểm dễ hiểu nhầm nhất của module này, nên nói rõ ngay:

**Telemetry và dữ liệu huấn luyện là hai thứ khác nhau, nằm ở hai chỗ khác
nhau.**

* ``ai_frames`` / ``ai_detections`` / ``ai_classifications`` chứa **phán
  đoán của chính mô hình**. Đây là dữ liệu chẩn đoán: để trả lời "vì sao
  khung hình này nhận sai". Nó *không phải* nhãn, vì không ai xác nhận nó
  đúng. Huấn luyện trên chính phán đoán của mô hình sẽ khuếch đại lỗi của
  nó qua mỗi lần train lại — đó là lý do hàng đợi duyệt tồn tại.

* ``ai_training_images`` và ``ai_review_candidates`` (status='approved')
  chứa **nhãn do người xác nhận**. Đây mới là cơ sở học. Chúng nằm ngoài
  phạm vi dọn dẹp này và giữ vĩnh viễn.

Cho nên vòng đời đúng là: telemetry sinh ra → người duyệt thấy khung hình
đáng giá → **đề bạt** nó thành nhãn (sang bảng huấn luyện, ảnh sang prefix
khác trong object storage) → telemetry hết hạn và bị xoá, nhãn ở lại.

Ràng buộc an toàn
-----------------
Việc đề bạt là thủ công và không tức thời, nên vẫn có cửa sổ mà một khung
hình *đang chờ duyệt* nằm trong diện bị xoá. Job này vì thế **không bao
giờ xoá** phiên/khung hình còn được một ``ai_review_candidates`` ở trạng
thái ``pending`` tham chiếu tới — xoá mất một mẫu chờ duyệt là mất đúng
thứ quý nhất: một trường hợp mô hình đã sai mà người chưa kịp sửa.

Vì sao ``ai_events`` không bao giờ hết hạn
------------------------------------------
Đó là sự kiện nghiệp vụ (nhặt hàng, trả hàng, thanh toán) mà logic giỏ
hàng phụ thuộc vào. Chúng là *kết luận*, không phải chẩn đoán.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_pipeline.infrastructure.models import (
    AiDetection,
    AiFrame,
    AiLog,
    AiSession,
    AiTrack,
)

logger = logging.getLogger(__name__)

# Xoá theo lô. Một lệnh DELETE trên hàng triệu dòng sẽ giữ khoá lâu và
# thổi phồng WAL; lô nhỏ chạy nhiều vòng thì mỗi vòng ngắn, và job có thể
# dừng giữa chừng mà không để lại giao dịch dở.
DEFAULT_BATCH_SIZE = 1000
# Trần số lô mỗi lần chạy, để job định kỳ luôn kết thúc trong thời gian
# đoán trước được thay vì chạy hàng giờ sau một đợt tồn đọng lớn.
DEFAULT_MAX_BATCHES = 50


@dataclass
class RetentionReport:
    frames_deleted: int = 0
    logs_deleted: int = 0
    sessions_deleted: int = 0
    tracks_deleted: int = 0
    storage_prefixes: list[str] = field(default_factory=list)
    protected_frames: int = 0
    truncated: bool = False   # còn dữ liệu quá hạn, sẽ dọn ở lần chạy sau

    def as_dict(self) -> dict:
        return {
            "frames_deleted": self.frames_deleted,
            "logs_deleted": self.logs_deleted,
            "sessions_deleted": self.sessions_deleted,
            "tracks_deleted": self.tracks_deleted,
            "storage_prefixes": len(self.storage_prefixes),
            "protected_frames": self.protected_frames,
            "truncated": self.truncated,
        }


class RetentionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _protected_frame_ids(self, frame_ids: list) -> set:
        """Khung hình đang được một mẫu chờ duyệt tham chiếu tới.

        Truy vấn bằng ``storage_prefix`` chứ không bằng khoá ngoại, vì
        ``ai_review_candidates`` được ai-engine ghi qua một đường độc lập
        và không giữ ``frame_id``. Đối chiếu theo prefix lưu trữ là mối
        liên hệ duy nhất chắc chắn có giữa hai bên.
        """
        if not frame_ids:
            return set()
        # Nhập khẩu tại chỗ: ai_pipeline không nên phụ thuộc biên dịch vào
        # ai_training, chỉ cần biết nó ở thời điểm chạy.
        from app.modules.ai_training.infrastructure.models import ReviewCandidate

        rows = (
            await self.session.execute(
                select(AiFrame.id, AiFrame.storage_prefix).where(
                    AiFrame.id.in_(frame_ids),
                    AiFrame.storage_prefix.isnot(None),
                )
            )
        ).all()
        if not rows:
            return set()

        prefix_by_id = {r[0]: r[1] for r in rows}
        pending_keys = (
            await self.session.execute(
                select(ReviewCandidate.storage_key).where(
                    ReviewCandidate.status == "pending",
                    ReviewCandidate.is_deleted.is_(False),
                )
            )
        ).scalars().all()
        if not pending_keys:
            return set()

        protected = set()
        for frame_id, prefix in prefix_by_id.items():
            if any(str(key).startswith(prefix) for key in pending_keys):
                protected.add(frame_id)
        return protected

    async def purge_frames(
        self,
        *,
        retention_days: int,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_batches: int = DEFAULT_MAX_BATCHES,
        report: RetentionReport | None = None,
    ) -> RetentionReport:
        """Xoá khung hình quá hạn và mọi thứ phụ thuộc (theo CASCADE).

        ``ai_detections`` / ``ai_classifications`` / ``ai_ocr`` /
        ``ai_embeddings`` đi theo nhờ ``ondelete=CASCADE``, nên không cần
        xoá riêng — và quan trọng hơn, không thể bỏ sót.
        """
        report = report or RetentionReport()
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        for _ in range(max_batches):
            rows = (
                await self.session.execute(
                    select(AiFrame.id, AiFrame.storage_prefix)
                    .where(AiFrame.created_at < cutoff)
                    .order_by(AiFrame.created_at.asc())
                    .limit(batch_size)
                )
            ).all()
            if not rows:
                return report

            ids = [r[0] for r in rows]
            protected = await self._protected_frame_ids(ids)
            if protected:
                report.protected_frames += len(protected)
                ids = [i for i in ids if i not in protected]
            if not ids:
                # Cả lô đều được bảo vệ. Dừng hẳn thay vì lặp vô hạn trên
                # cùng một lô — lần chạy sau, khi người đã duyệt xong,
                # chúng sẽ hết được bảo vệ.
                logger.info("retention: toàn bộ lô đang chờ duyệt, bỏ qua")
                return report

            report.storage_prefixes.extend(
                str(r[1]) for r in rows if r[1] and r[0] in set(ids)
            )
            result = await self.session.execute(
                delete(AiFrame).where(AiFrame.id.in_(ids))
            )
            report.frames_deleted += result.rowcount or 0
            await self.session.commit()

            if len(rows) < batch_size:
                return report

        report.truncated = True
        return report

    async def purge_logs(
        self,
        *,
        retention_days: int,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_batches: int = DEFAULT_MAX_BATCHES,
        report: RetentionReport | None = None,
    ) -> RetentionReport:
        report = report or RetentionReport()
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        for _ in range(max_batches):
            ids = (
                await self.session.execute(
                    select(AiLog.id)
                    .where(AiLog.created_at < cutoff)
                    .limit(batch_size)
                )
            ).scalars().all()
            if not ids:
                return report
            result = await self.session.execute(delete(AiLog).where(AiLog.id.in_(ids)))
            report.logs_deleted += result.rowcount or 0
            await self.session.commit()
            if len(ids) < batch_size:
                return report
        report.truncated = True
        return report

    async def purge_empty_sessions(
        self,
        *,
        retention_days: int,
        batch_size: int = DEFAULT_BATCH_SIZE,
        report: RetentionReport | None = None,
    ) -> RetentionReport:
        """Xoá phiên đã quá hạn và không còn khung hình nào.

        Chỉ xoá phiên *rỗng*: một phiên còn khung hình nghĩa là những khung
        đó chưa quá hạn, và xoá phiên sẽ CASCADE cuốn chúng theo — tức là
        xoá dữ liệu chưa đến hạn.

        Riêng ``ai_events`` trỏ về phiên bằng CASCADE, nên phiên nào còn sự
        kiện nghiệp vụ cũng phải giữ lại: sự kiện là dữ liệu vĩnh viễn.
        """
        from app.modules.ai_pipeline.infrastructure.models import AiEvent

        report = report or RetentionReport()
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        frame_exists = (
            select(func.count(AiFrame.id))
            .where(AiFrame.session_id == AiSession.id)
            .scalar_subquery()
        )
        event_exists = (
            select(func.count(AiEvent.id))
            .where(AiEvent.session_id == AiSession.id)
            .scalar_subquery()
        )
        ids = (
            await self.session.execute(
                select(AiSession.id)
                .where(
                    AiSession.started_at < cutoff,
                    frame_exists == 0,
                    event_exists == 0,
                )
                .limit(batch_size)
            )
        ).scalars().all()
        if not ids:
            return report

        tracks = await self.session.execute(
            delete(AiTrack).where(AiTrack.session_id.in_(ids))
        )
        report.tracks_deleted += tracks.rowcount or 0
        result = await self.session.execute(
            delete(AiSession).where(AiSession.id.in_(ids))
        )
        report.sessions_deleted += result.rowcount or 0
        await self.session.commit()
        return report
