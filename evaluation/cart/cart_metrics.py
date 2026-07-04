"""Read-only Shopping Cart / Order metrics.

CRITICAL — production safety: this module NEVER writes to the production
database. Its session helper (`_readonly_session`) issues `SET TRANSACTION
READ ONLY` on the connection when the backend supports it (Postgres does;
this is a real database-enforced guardrail, not just a code convention),
and always rolls back (never commits) on exit. Nothing in this file calls
`session.add`, `session.commit`, `checkout_service.*`, `cart_service.*`,
or any other method from the sales module's mutating application layer —
only `select()` (read) statements against the ORM models.

Design note — why this runs as a SEPARATE PROCESS from the dataset-based
metrics (pipeline/camera-quality/detection/tracking/opencv-module-eval):
this module imports backend's `app.modules.*` package. The dataset-based
metrics import ai-engine's `app.vision` package. Both services define
their own unrelated top-level `app` package; importing both into the same
Python interpreter is unsafe — whichever is imported first wins the `app`
name in `sys.modules` and the other import silently returns the wrong
package. `evaluation/cli.py` therefore always runs cart metrics as an
isolated subprocess, never in-process alongside the vision-side metrics,
and `evaluation/reporting/*` merges the two JSON outputs afterwards.

Every field that cannot be reliably reconstructed from the current schema
is returned as `None` with a paired `..._reason` string explaining why —
see `checkout_cancelled_count`, `qr_confirmation_count`, and
`camera_uptime_percent` below. These are not oversights; the underlying
data does not exist in the database (confirmed by reading
`checkout_service.py`, `cart_sweeper.py`, and the audit module — see
reasons inline).
"""

from __future__ import annotations

import statistics
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator


@asynccontextmanager
async def _readonly_session(database_url: str) -> AsyncIterator[Any]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(database_url, echo=False, future=True, pool_pre_ping=True)
    session = AsyncSession(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        try:
            await session.execute(text("SET TRANSACTION READ ONLY"))
        except Exception:
            pass  # backend doesn't support it (e.g. SQLite in tests) — fine, discipline above still holds.
        yield session
    finally:
        await session.rollback()  # never commit, even implicitly
        await session.close()
        await engine.dispose()


@dataclass
class CartMetricsResult:
    window_start: datetime | None
    window_end: datetime | None

    cart_count_total: int = 0
    cart_count_by_status: dict[str, int] = field(default_factory=dict)
    checkout_requested_count: int = 0
    checkout_pending_now_count: int = 0
    converted_count: int = 0

    avg_cart_completion_seconds: float | None = None
    min_cart_completion_seconds: float | None = None
    max_cart_completion_seconds: float | None = None

    products_detected_total: int = 0
    avg_products_per_converted_cart: float | None = None

    order_count: int = 0
    order_status_counts: dict[str, int] = field(default_factory=dict)
    avg_order_total_amount: float | None = None

    customer_association_rate: float | None = None

    checkout_cancelled_count: int | None = None
    checkout_cancelled_reason: str = ""

    qr_confirmation_count: int | None = None
    qr_confirmation_reason: str = ""

    camera_total_count: int = 0
    camera_online_now_count: int = 0
    camera_uptime_percent: dict[str, None] = field(default_factory=dict)
    camera_uptime_reason: str = ""


def _summarize_carts(carts: list, cart_status_enum) -> dict:
    """Pure aggregation over already-fetched cart rows — no DB access, no
    SQLAlchemy — so it can be unit tested with plain fake objects that just
    happen to have the same attribute names as `ShoppingCart`."""
    status_counts: dict[str, int] = {}
    completion_seconds: list[float] = []
    product_counts_converted: list[int] = []
    products_total = 0
    customers_linked = 0
    checkout_requested = 0
    pending_now = 0
    converted = 0

    for cart in carts:
        status_counts[cart.status.value] = status_counts.get(cart.status.value, 0) + 1
        if cart.checkout_requested_at is not None:
            checkout_requested += 1
        if cart.status == cart_status_enum.PENDING_CHECKOUT:
            pending_now += 1
        if cart.customer_id is not None:
            customers_linked += 1
        n_items = len(cart.items) if cart.items else 0
        products_total += n_items
        if cart.status == cart_status_enum.CONVERTED:
            converted += 1
            product_counts_converted.append(n_items)
            if cart.converted_at is not None and cart.created_at is not None:
                completion_seconds.append((cart.converted_at - cart.created_at).total_seconds())

    return {
        "cart_count_total": len(carts),
        "cart_count_by_status": status_counts,
        "checkout_requested_count": checkout_requested,
        "checkout_pending_now_count": pending_now,
        "converted_count": converted,
        "products_detected_total": products_total,
        "avg_products_per_converted_cart": (
            round(statistics.mean(product_counts_converted), 2) if product_counts_converted else None
        ),
        "customer_association_rate": (
            round(customers_linked / len(carts), 3) if carts else None
        ),
        "avg_cart_completion_seconds": round(statistics.mean(completion_seconds), 1) if completion_seconds else None,
        "min_cart_completion_seconds": round(min(completion_seconds), 1) if completion_seconds else None,
        "max_cart_completion_seconds": round(max(completion_seconds), 1) if completion_seconds else None,
    }


def _summarize_orders(orders: list) -> dict:
    """Pure aggregation over already-fetched order rows — same rationale
    as `_summarize_carts`."""
    order_status_counts: dict[str, int] = {}
    totals = []
    for o in orders:
        order_status_counts[o.status.value] = order_status_counts.get(o.status.value, 0) + 1
        totals.append(float(o.total_amount))
    return {
        "order_count": len(orders),
        "order_status_counts": order_status_counts,
        "avg_order_total_amount": round(statistics.mean(totals), 2) if totals else None,
    }


async def collect_cart_metrics(
    database_url: str,
    *,
    organization_id: str | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> CartMetricsResult:
    """All queries are read-only SELECTs. `window_start`/`window_end`
    filter on `ShoppingCart.created_at` / `Order.created_at`; pass both
    None to read across all time (still read-only — just unfiltered)."""
    from sqlalchemy import select

    from app.modules.camera.infrastructure.models import Camera
    from app.modules.sales.infrastructure.models import (
        CartStatus,
        Order,
        ShoppingCart,
    )

    result = CartMetricsResult(window_start=window_start, window_end=window_end)

    async with _readonly_session(database_url) as session:
        cart_stmt = select(ShoppingCart).where(ShoppingCart.is_deleted.is_(False))
        if organization_id:
            cart_stmt = cart_stmt.where(ShoppingCart.organization_id == organization_id)
        if window_start:
            cart_stmt = cart_stmt.where(ShoppingCart.created_at >= window_start)
        if window_end:
            cart_stmt = cart_stmt.where(ShoppingCart.created_at <= window_end)
        carts = list((await session.execute(cart_stmt)).scalars().all())

        for k, v in _summarize_carts(carts, CartStatus).items():
            setattr(result, k, v)

        # --- Orders ---
        order_stmt = select(Order).where(Order.is_deleted.is_(False))
        if organization_id:
            order_stmt = order_stmt.where(Order.organization_id == organization_id)
        if window_start:
            order_stmt = order_stmt.where(Order.created_at >= window_start)
        if window_end:
            order_stmt = order_stmt.where(Order.created_at <= window_end)
        orders = list((await session.execute(order_stmt)).scalars().all())
        for k, v in _summarize_orders(orders).items():
            setattr(result, k, v)

        # --- Cameras (instantaneous snapshot only — see reason below) ---
        camera_stmt = select(Camera).where(Camera.is_deleted.is_(False))
        if organization_id:
            camera_stmt = camera_stmt.where(Camera.organization_id == organization_id)
        cameras = list((await session.execute(camera_stmt)).scalars().all())
        result.camera_total_count = len(cameras)
        result.camera_online_now_count = sum(1 for c in cameras if c.is_online)
        result.camera_uptime_percent = {c.code: None for c in cameras}
        result.camera_uptime_reason = (
            "Not measured: the `cameras` table stores only the current `is_online` flag and "
            "`last_seen_at` timestamp (a snapshot), not a historical online/offline event log or "
            "time series. A true uptime percentage over a time window requires periodic samples "
            "or state-transition history, neither of which this schema persists. Reporting the "
            "current snapshot (camera_online_now_count / camera_total_count) instead, which IS "
            "measured."
        )

    # --- Fields that are architecturally impossible to reconstruct from
    # the current schema, confirmed by reading the relevant service code
    # rather than assumed ---
    result.checkout_cancelled_count = None
    result.checkout_cancelled_reason = (
        "Not measured: `cancel_pending_checkout()` (checkout_service.py) reverts a cart to "
        "CartStatus.ACTIVE and clears checkout_token/checkout_requested_at — the same terminal "
        "state produced by the cart simply never having requested checkout. The scheduled sweeper "
        "(cart_sweeper.py) also calls this same path for checkouts that time out unconfirmed. "
        "Because no distinguishing field or audit record is written on cancel (checked: the "
        "`audit_logs` table has no entries for cart/checkout actions, and the in-memory event bus "
        "in app/core/events/ is not persisted), a point-in-time DB read cannot tell a cancelled "
        "checkout apart from a cart that never attempted one. Reconstructing this would require "
        "either persisting checkout_cancelled events to the audit log (a production code change, "
        "out of scope per this framework's constraints) or replaying live event-bus traffic during "
        "the evaluation window, which this read-only framework does not do."
    )
    result.qr_confirmation_count = None
    result.qr_confirmation_reason = (
        "Not measured: `_confirm_pending()` (checkout_service.py) receives a `confirmed_by` value "
        "of \"customer\" or \"staff\" and publishes it only as an in-memory domain event "
        "(sales_events.customer_confirmed) — it is never written to a cart/order column or to the "
        "audit log. Once the transaction commits, whether a given CONVERTED cart was confirmed via "
        "the customer's QR scan or by staff on the customer's behalf is not recoverable from the "
        "database."
    )

    return result
