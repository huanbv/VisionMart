"""Runtime pause for the automatic cart-scan pipeline (Celery FRAME_PIPELINE).

Admin toggles this from Live Cart so they can test Chụp & Quét / upload
analyze without the background tick adding SKUs at the same time.
Manual trigger-scan and /cameras/{id}/analyze do not consult this flag.

Stored in Redis (no DB migration): key lives until explicitly cleared or
Redis is flushed. Default (missing key) = auto-scan running.
"""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis

from app.config.settings import get_settings

_KEY = "ai:auto_scan:paused:branch:{branch_id}"


def pause_key(branch_id: uuid.UUID | str) -> str:
    return _KEY.format(branch_id=str(branch_id))


async def _client() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )


async def is_branch_auto_scan_paused(branch_id: uuid.UUID | str) -> bool:
    client = await _client()
    try:
        return await client.get(pause_key(branch_id)) == "1"
    finally:
        await client.aclose()


async def set_branch_auto_scan_paused(
    branch_id: uuid.UUID | str, paused: bool
) -> bool:
    client = await _client()
    try:
        key = pause_key(branch_id)
        if paused:
            await client.set(key, "1")
        else:
            await client.delete(key)
        return paused
    finally:
        await client.aclose()


async def is_paused_on(client: aioredis.Redis, branch_id: uuid.UUID | str) -> bool:
    """Reuse an already-open Redis client (Celery scan loop)."""
    return await client.get(pause_key(branch_id)) == "1"
