"""Job định kỳ dọn telemetry AI + ảnh debug.

Chạy trên Celery Beat khi ``AI_PIPELINE_CLEANUP_ENABLED=true``.

Thứ tự các bước không tuỳ tiện: log → khung hình → phiên rỗng. Xoá khung
hình trước phiên vì một phiên chỉ được coi là rỗng sau khi khung hình cuối
của nó đã đi; làm ngược lại thì phiên nào cũng "còn khung" và không bao
giờ dọn được.

Ảnh debug trong object storage bị xoá **sau** khi hàng DB đã xoá thành
công. Ngược lại sẽ để lại hàng trỏ tới ảnh không còn tồn tại — dashboard
hiện ảnh vỡ. Còn thứ tự này, xấu nhất là để lại ảnh mồ côi tốn dung
lượng, mà lần chạy sau sẽ quét nốt.
"""

from __future__ import annotations

import asyncio
import logging

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.modules.ai_pipeline.application.retention_service import (
    RetentionReport,
    RetentionService,
)
from app.services.object_storage import MinioStorage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _delete_debug_objects(prefixes: list[str]) -> int:
    """Xoá ảnh từng bước của các khung hình vừa bị xoá khỏi DB."""
    if not prefixes:
        return 0
    settings = get_settings()
    storage = MinioStorage(settings)
    removed = 0
    for prefix in prefixes:
        try:
            keys = await storage.list_keys(prefix)
            if keys:
                removed += await storage.delete_many(keys)
        except Exception:  # noqa: BLE001
            # Ảnh mồ côi chỉ tốn dung lượng; làm hỏng cả job dọn dẹp vì
            # một prefix không đọc được thì tệ hơn nhiều.
            logger.warning("không xoá được ảnh debug ở %s", prefix, exc_info=True)
    return removed


async def _run() -> dict:
    settings = get_settings()
    if not getattr(settings, "AI_PIPELINE_CLEANUP_ENABLED", False):
        return {"skipped": "disabled"}

    report = RetentionReport()
    async with SessionLocal() as session:
        service = RetentionService(session)

        await service.purge_logs(
            retention_days=settings.AI_LOG_RETENTION_DAYS, report=report
        )
        await service.purge_frames(
            retention_days=settings.AI_FRAME_RETENTION_DAYS, report=report
        )
        await service.purge_empty_sessions(
            retention_days=settings.AI_SESSION_RETENTION_DAYS, report=report
        )

    removed = await _delete_debug_objects(report.storage_prefixes)
    out = report.as_dict()
    out["debug_objects_removed"] = removed
    return out


@celery_app.task(name="ai_pipeline.cleanup", ignore_result=True)
def cleanup() -> dict:
    try:
        result = asyncio.run(_run())
        logger.info("ai_pipeline.cleanup xong: %s", result)
        return result
    except Exception:
        logger.exception("ai_pipeline.cleanup thất bại")
        raise
