"""Runtime pause for the automatic cart-scan pipeline (Celery FRAME_PIPELINE).

Admin toggles this from Live Cart so they can test Chụp & Quét / upload
analyze without the background tick adding SKUs at the same time.
Manual trigger-scan and /cameras/{id}/analyze do not consult this flag.

Stored in Redis (no DB migration). ``0`` is an explicit UI opt-in and ``1``
is paused. A missing key follows ``FRAME_PIPELINE_ENABLED`` so the switch
never claims the pipeline is running while the global default is disabled.
"""

from __future__ import annotations

import uuid

import redis.asyncio as aioredis

from app.config.settings import get_settings

_KEY = "ai:auto_scan:paused:branch:{branch_id}"


def pause_key(branch_id: uuid.UUID | str) -> str:
    return _KEY.format(branch_id=str(branch_id))


def _paused_from_value(value: str | None, *, default_enabled: bool) -> bool:
    if value is None:
        return not default_enabled
    return value != "0"


async def _client() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )


async def is_branch_auto_scan_paused(branch_id: uuid.UUID | str) -> bool:
    client = await _client()
    try:
        value = await client.get(pause_key(branch_id))
        return _paused_from_value(
            value,
            default_enabled=get_settings().FRAME_PIPELINE_ENABLED,
        )
    finally:
        await client.aclose()


async def set_branch_auto_scan_paused(
    branch_id: uuid.UUID | str, paused: bool
) -> bool:
    client = await _client()
    try:
        key = pause_key(branch_id)
        # Persist both states. Deleting on resume made "explicitly enabled"
        # indistinguishable from "never configured", so a globally-disabled
        # worker silently stayed off while the UI switch showed on.
        await client.set(key, "1" if paused else "0")
        return paused
    finally:
        await client.aclose()


async def is_paused_on(client: aioredis.Redis, branch_id: uuid.UUID | str) -> bool:
    """Reuse an already-open Redis client (Celery scan loop)."""
    value = await client.get(pause_key(branch_id))
    return _paused_from_value(
        value,
        default_enabled=get_settings().FRAME_PIPELINE_ENABLED,
    )
