"""Periodic alert-scan Celery tasks.

Bridges Celery's sync execution model into the async stack by running a
fresh `AsyncSession` per invocation via `asyncio.run`.
"""

from __future__ import annotations

import asyncio
import logging

from app.database.session import SessionLocal
from app.modules.notification.application.alert_service import AlertService
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run_scan() -> dict:
    async with SessionLocal() as session:
        service = AlertService(session)
        return await service.scan_all_organizations()


@celery_app.task(name="alerts.scan_all", ignore_result=True)
def scan_all() -> dict:
    try:
        result = asyncio.run(_run_scan())
        logger.info("alerts.scan_all completed: %s", result)
        return result
    except Exception:
        logger.exception("alerts.scan_all failed")
        raise
