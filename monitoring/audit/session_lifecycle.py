"""Read-only shopping session (cart) lifecycle audit.

Reads `shopping_carts` via a raw, parameterized `SELECT` (no ORM import,
no write statements anywhere in this module — see `_fetch_recent_carts`)
and derives each cart's current lifecycle stage from its existing
`status`/timestamp columns. Nothing here writes to `shopping_carts`,
`orders`, or any other production table; observed stages are recorded
only into monitoring's own SQLite store (`monitoring/storage/db.py`).

Stage derivation (from `backend/app/modules/sales/infrastructure/models.py`
and `checkout_service.py`, read, not guessed):

  - `status = active`, no items yet       -> "tracking"        (AI is
    building the cart; nothing added yet)
  - `status = active`, has items          -> "cart_active"     (shopping in progress)
  - `status = pending_checkout`           -> "pending_checkout" (bill frozen,
    waiting for QR/staff confirmation)
  - `status = converted`                  -> "completed"
  - `status = abandoned`                  -> "abandoned"        (this status is
    ONLY reached via the regular ACTIVE-cart expiry sweep in
    `cart_service.py` — a cart that never had anything added and timed out.
    A cancelled or expired PENDING_CHECKOUT reverts to `active`, not
    `abandoned` — see `checkout_service.py::cancel_pending_checkout` — so it
    is indistinguishable from a cart that never attempted checkout, using
    only the current row. This is the same limitation documented in
    `evaluation/cart/cart_metrics.py`'s `checkout_cancelled_reason`.)

Because there is no event-sourcing table for cart status changes anywhere
in the schema, a FULL retroactive lifecycle history cannot be reconstructed
for any cart from a single read. What this module does instead — and what
makes it more than a snapshot — is compare each cart's freshly-derived
stage against the last stage THIS SERVICE recorded for that cart id
(`monitoring/storage/db.py`'s `session_lifecycle_events` table) on every
poll, and append a new event only when the stage actually changed. From
the moment monitoring starts running, this produces a genuine, observed
transition trail per session; before that moment, only the current stage
is known. Every returned view says explicitly whether its history is a
single "first observation" or an observed multi-step trail.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from monitoring.storage import db as monitoring_db

_STATUS_TO_STAGE_NO_ITEMS = {
    "active": "tracking",
    "pending_checkout": "pending_checkout",
    "converted": "completed",
    "abandoned": "abandoned",
}


def _derive_stage(status: str, has_items: bool) -> str:
    if status == "active":
        return "cart_active" if has_items else "tracking"
    return _STATUS_TO_STAGE_NO_ITEMS.get(status, "unknown")


@dataclass
class SessionLifecycleView:
    cart_id: str
    source: str
    current_stage: str
    status: str
    item_count: int
    total_amount: str
    created_at: str | None
    checkout_requested_at: str | None
    converted_at: str | None
    observed_events: list[dict] = field(default_factory=list)
    observation_note: str = ""


@dataclass
class SessionLifecycleSnapshot:
    checked_at: float
    reachable: bool
    reason: str | None
    sessions: list[SessionLifecycleView] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "checked_at": self.checked_at,
            "reachable": self.reachable,
            "reason": self.reason,
            "sessions": [
                {**vars(s)} for s in self.sessions
            ],
        }


async def _fetch_recent_carts(database_url: str, since_hours: int, limit: int, organization_id: str | None) -> list[dict]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        query = (
            "SELECT id, organization_id, source, status, items, total_amount, currency, "
            "created_at, checkout_requested_at, converted_at "
            "FROM shopping_carts WHERE is_deleted = false AND created_at >= :cutoff"
        )
        params: dict = {"cutoff": cutoff}
        if organization_id:
            query += " AND organization_id = :org_id"
            params["org_id"] = organization_id
        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit
        async with engine.connect() as conn:
            result = await conn.execute(text(query), params)
            rows = [dict(r._mapping) for r in result]
        return rows
    finally:
        await engine.dispose()


async def collect_session_lifecycle(
    database_url: str,
    sqlite_path: str,
    *,
    since_hours: int = 24,
    limit: int = 200,
    organization_id: str | None = None,
) -> SessionLifecycleSnapshot:
    now = time.time()
    try:
        rows = await _fetch_recent_carts(database_url, since_hours, limit, organization_id)
    except Exception as exc:  # noqa: BLE001
        return SessionLifecycleSnapshot(checked_at=now, reachable=False, reason=str(exc))

    views: list[SessionLifecycleView] = []
    for row in rows:
        cart_id = str(row["id"])
        items = row["items"] or []
        stage = _derive_stage(str(row["status"]), bool(items))

        last_recorded = monitoring_db.last_session_stage(sqlite_path, cart_id)
        if last_recorded != stage:
            monitoring_db.record_session_stage(
                sqlite_path, cart_id, stage,
                detail={
                    "status": str(row["status"]), "item_count": len(items),
                    "total_amount": str(row["total_amount"]),
                },
                ts=now,
            )

        events = monitoring_db.session_events(sqlite_path, cart_id)
        note = (
            "Single first-observation snapshot — this cart's stage before monitoring started "
            "polling is not recoverable (no event-sourcing table exists for cart status changes)."
            if len(events) <= 1
            else f"Observed {len(events)} stage transitions since monitoring started tracking this session."
        )

        views.append(
            SessionLifecycleView(
                cart_id=cart_id,
                source=str(row["source"]),
                current_stage=stage,
                status=str(row["status"]),
                item_count=len(items),
                total_amount=str(row["total_amount"]),
                created_at=str(row["created_at"]) if row["created_at"] else None,
                checkout_requested_at=str(row["checkout_requested_at"]) if row["checkout_requested_at"] else None,
                converted_at=str(row["converted_at"]) if row["converted_at"] else None,
                observed_events=events,
                observation_note=note,
            )
        )

    return SessionLifecycleSnapshot(checked_at=now, reachable=True, reason=None, sessions=views)
