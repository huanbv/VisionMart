"""Realtime helpers for shopping cart events.

Publishes cart mutations to Redis pub/sub so WebSocket clients (dashboard,
cashier station display) receive live updates.
"""

from __future__ import annotations

import uuid

from app.core.realtime import publish_event


def cart_channel(branch_id: uuid.UUID) -> str:
    return f"cart:branch:{branch_id}"


async def publish_cart_update(
    branch_id: uuid.UUID, payload: dict
) -> None:
    await publish_event([cart_channel(branch_id)], payload)
