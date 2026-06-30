"""Cross-process realtime pub/sub backed by Redis.

Used to push notification events from any FastAPI process or Celery worker
to all currently-connected WebSocket clients regardless of which API
worker holds the socket.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Iterable

import redis.asyncio as aioredis

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def _client() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )


def channels_for_notification(
    *,
    organization_id: uuid.UUID,
    recipient_user_id: uuid.UUID | None,
    recipient_role_id: uuid.UUID | None,
) -> list[str]:
    channels: list[str] = []
    if recipient_user_id is not None:
        channels.append(f"user:{recipient_user_id}")
    if recipient_role_id is not None:
        channels.append(
            f"org:{organization_id}:role:{recipient_role_id}"
        )
    return channels


async def publish_event(channels: Iterable[str], payload: dict) -> None:
    chans = [c for c in channels if c]
    if not chans:
        return
    client = _client()
    try:
        data = json.dumps(payload, default=str)
        for ch in chans:
            await client.publish(ch, data)
    except Exception:
        logger.exception("realtime publish failed")
    finally:
        await client.aclose()


def open_pubsub() -> tuple[aioredis.Redis, aioredis.client.PubSub]:
    client = _client()
    return client, client.pubsub()
