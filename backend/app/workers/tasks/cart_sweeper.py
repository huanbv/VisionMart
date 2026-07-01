"""Periodic sweeper: abandon carts past their `expires_at`.

Reuses `CartService.abandon()` so inventory reservations are released.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.database.session import SessionLocal
from app.modules.sales.api.cart_router import build_cart_service
from app.modules.sales.infrastructure.repositories import SqlAlchemyCartRepository
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    abandoned = 0
    async with SessionLocal() as session:
        repo = SqlAlchemyCartRepository(session)
        expired = await repo.list_expired(now, limit=500)
        service = build_cart_service(session)
        for cart in expired:
            try:
                await service.abandon(cart.organization_id, cart.id)
                abandoned += 1
            except Exception:
                logger.exception("cart abandon failed cart_id=%s", cart.id)
    return {"abandoned": abandoned}


@celery_app.task(name="cart.sweep_expired", ignore_result=True)
def sweep_expired() -> dict:
    try:
        result = asyncio.run(_run())
        logger.info("cart.sweep_expired result=%s", result)
        return result
    except Exception:
        logger.exception("cart.sweep_expired failed")
        raise
