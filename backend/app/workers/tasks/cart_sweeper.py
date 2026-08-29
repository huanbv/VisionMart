"""Periodic sweeper: abandon carts past their `expires_at`, and resolve
carts stuck in PENDING_CHECKOUT whose confirmation window lapsed (nobody
scanned/confirmed the QR in time).

Reuses `CartService.abandon()` / `CheckoutService.cancel_pending_checkout()`
so inventory reservations are released or preserved correctly either way.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.database.session import SessionLocal
from app.modules.sales.api.cart_router import build_cart_service, build_checkout_service
from app.modules.sales.infrastructure.models import CartSource
from app.modules.sales.infrastructure.repositories import SqlAlchemyCartRepository
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    abandoned = 0
    checkout_cancelled = 0
    ai_unconfirmed_cleared = 0
    async with SessionLocal() as session:
        repo = SqlAlchemyCartRepository(session)
        cart_service = build_cart_service(session)
        checkout_service = build_checkout_service(session)

        expired = await repo.list_expired(now, limit=500)
        for cart in expired:
            try:
                await cart_service.abandon(cart.organization_id, cart.id)
                abandoned += 1
            except Exception:
                logger.exception("cart abandon failed cart_id=%s", cart.id)

        pending_expired = await repo.list_pending_checkout_expired(now, limit=500)
        for cart in pending_expired:
            try:
                if cart.source == CartSource.AI_VISION:
                    # Đơn AI 15' không ai xác nhận -> DỌN hẳn, không resume:
                    # đơn AI chưa xác nhận nên biến mất khỏi màn hình chứ
                    # không quay lại trạng thái mua tiếp. Resume trước (PENDING
                    # -> ACTIVE) rồi abandon để dùng lại đúng logic nhả tồn kho
                    # trong CartService.abandon (chỉ nhận cart ACTIVE).
                    await checkout_service.cancel_pending_checkout(
                        cart.organization_id, cart.id
                    )
                    await cart_service.abandon(cart.organization_id, cart.id)
                    ai_unconfirmed_cleared += 1
                else:
                    # Cart nhân viên tạo tay: hết cửa sổ xác nhận thì resume
                    # mua tiếp như cũ; nếu khách đã rời, ACTIVE-expiry ở trên
                    # sẽ dọn sau. Giữ nguyên hành vi cũ.
                    await checkout_service.cancel_pending_checkout(
                        cart.organization_id, cart.id
                    )
                    checkout_cancelled += 1
            except Exception:
                logger.exception(
                    "cart pending-checkout sweep failed cart_id=%s", cart.id
                )
    return {
        "abandoned": abandoned,
        "checkout_confirmation_timed_out": checkout_cancelled,
        "ai_unconfirmed_cleared": ai_unconfirmed_cleared,
    }


@celery_app.task(name="cart.sweep_expired", ignore_result=True)
def sweep_expired() -> dict:
    try:
        result = asyncio.run(_run())
        logger.info("cart.sweep_expired result=%s", result)
        return result
    except Exception:
        logger.exception("cart.sweep_expired failed")
        raise
