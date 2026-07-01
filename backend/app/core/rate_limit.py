"""Simple Redis-backed fixed-window rate limiter.

Sufficient for auth endpoints; not intended for high-precision throttling.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, status

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


async def _hit(redis_url: str, key: str, window_seconds: int) -> int:
    client = aioredis.from_url(
        redis_url, encoding="utf-8", decode_responses=True
    )
    try:
        pipe = client.pipeline()
        pipe.incr(key, 1)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()
        return int(results[0])
    finally:
        await client.aclose()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce(
    request: Request,
    *,
    bucket: str,
    limit: int,
    window_seconds: int,
    settings: Settings | None = None,
) -> None:
    """Increment the counter for the caller's IP and raise HTTP 429 if over limit."""

    if limit <= 0 or window_seconds <= 0:
        return
    cfg = settings or get_settings()
    ip = _client_ip(request)
    key = f"ratelimit:{bucket}:{ip}"
    try:
        current = await _hit(cfg.REDIS_URL, key, window_seconds)
    except Exception:  # noqa: BLE001
        logger.exception("rate limit backend failed, allowing request")
        return
    if current > limit:
        retry_after = window_seconds
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests, please retry later.",
            headers={"Retry-After": str(retry_after)},
        )
