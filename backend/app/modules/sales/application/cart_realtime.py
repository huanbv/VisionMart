"""Realtime helpers for shopping cart events.

Publishes cart mutations to Redis pub/sub so WebSocket clients (dashboard,
cashier station display) receive live updates.

Also hosts the event-bus subscriber that turns Sales domain events
(`app/modules/sales/domain/events.py`) into these WebSocket pushes, using
the project's existing `EventBus`/`DomainEvent` (`app/core/events/`,
provided via `app/dependencies/providers.get_event_bus`). This is the
"decoupled" half of the checkout flow: `CartService`/`CheckoutService` only
publish e.g. `sales.customer_confirmed` — they never import or call this
module's `publish_cart_update` directly. Whoever imports this module (the
API process, or a Celery worker) gets the subscribers registered as a side
effect of the import below, so realtime notification "just works" without
every call site having to wire it up. (This import-time registration is a
known, documented trade-off — see the pre-production audit's Step 7 for why
explicit startup wiring would be more robust; not changed here to keep this
fix scoped to the boot-blocking bug it's part of.)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.core.events import DomainEvent, EventBus
from app.core.realtime import publish_event
from app.dependencies.providers import get_event_bus
from app.modules.sales.domain import events as sales_events

logger = logging.getLogger(__name__)


def cart_channel(branch_id: uuid.UUID) -> str:
    return f"cart:branch:{branch_id}"


async def publish_cart_update(branch_id: uuid.UUID, payload: dict) -> None:
    await publish_event([cart_channel(branch_id)], payload)


async def _on_cart_domain_event(event: DomainEvent) -> None:
    cart = event.payload.get("cart")
    if cart is None:
        logger.warning("sales event %s published with no 'cart' in payload", event.name)
        return

    payload: dict = {
        "type": "cart_update",
        # "sales.checkout_pending" -> "checkout_pending", kept short for
        # the frontend (which today only uses it as a "something changed"
        # signal, not a strict contract).
        "action": event.name.split(".", 1)[-1],
        "cart_id": str(cart.id),
        "branch_id": str(cart.branch_id),
        "status": cart.status.value,
        "source": cart.source.value,
        "total_amount": str(cart.total_amount),
        "currency": cart.currency,
        "line_count": len(cart.items or []),
        "updated_at": (cart.updated_at or datetime.now(timezone.utc)).isoformat(),
    }
    # A few event types carry extra fields useful to future consumers (a
    # customer-display panel, analytics) even though today's dashboard only
    # treats any message as a "something changed, refetch" signal.
    for key in ("checkout_token", "confirm_url", "confirmed_by", "reason"):
        if key in event.payload:
            payload[key] = event.payload[key]
    order = event.payload.get("order")
    if order is not None:
        payload["order_id"] = str(order.id)
        payload["order_code"] = order.code

    try:
        await publish_cart_update(cart.branch_id, payload)
    except Exception:  # noqa: BLE001
        logger.exception("failed to publish cart realtime update")


def register_subscribers(bus: EventBus) -> None:
    for name in sales_events.ALL_EVENT_NAMES:
        bus.subscribe(name, _on_cart_domain_event)


# Registered at import time (idempotent in practice — Python caches this
# module, and get_event_bus() is itself @lru_cache'd so this always
# targets the one process-wide bus instance) so realtime notification
# works no matter which process imports the sales application layer first:
# the FastAPI backend or a Celery worker.
register_subscribers(get_event_bus())
