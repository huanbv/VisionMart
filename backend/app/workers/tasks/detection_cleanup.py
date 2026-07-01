"""Periodic detection retention job.

Deletes DetectionEvent rows older than DETECTION_RETENTION_DAYS and removes
their associated snapshots from MinIO. Runs on Celery Beat when
DETECTION_CLEANUP_ENABLED is true.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)
from app.services.object_storage import MinioStorage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run_cleanup() -> dict:
    settings = get_settings()
    if not settings.DETECTION_CLEANUP_ENABLED:
        return {"skipped": "disabled"}

    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.DETECTION_RETENTION_DAYS
    )
    storage = MinioStorage(settings)

    async with SessionLocal() as session:
        repo = SqlAlchemyDetectionRepository(session)
        rows = await repo.list_older_than(
            cutoff, limit=settings.DETECTION_CLEANUP_BATCH_SIZE
        )
        if not rows:
            return {"deleted": 0, "cutoff": cutoff.isoformat()}

        image_keys = [key for _, key in rows if key]
        objects_removed = 0
        if image_keys:
            try:
                objects_removed = await storage.delete_many(image_keys)
            except Exception as exc:  # noqa: BLE001
                logger.exception("MinIO batch delete failed: %s", exc)

        deleted = await repo.hard_delete_ids([rid for rid, _ in rows])
        return {
            "cutoff": cutoff.isoformat(),
            "deleted": deleted,
            "objects_removed": objects_removed,
        }


@celery_app.task(name="detection.cleanup", ignore_result=True)
def cleanup() -> dict:
    try:
        result = asyncio.run(_run_cleanup())
        logger.info("detection.cleanup completed: %s", result)
        return result
    except Exception:
        logger.exception("detection.cleanup failed")
        raise
