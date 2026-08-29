"""Anonymous cross-camera visitor linking (customer journey continuity).

Problem: ByteTrack track ids are only stable *within one camera's* tracker
instance (see ai-engine/app/services/person_tracker.py — one tracker per
camera). There is no face recognition or appearance re-identification model
in this system (by design — the project scope is behavior analytics, not
biometric identification), so when a shopper walks from the entrance camera's
view into a shelf camera's view, the two cameras report two completely
unrelated track ids for the same physical person.

This module assigns a `global_track_id` that best-effort survives across
cameras, so a shopper's journey (entrance -> shelf -> checkout) can be
reconstructed for analytics even though the cart itself stays scoped to a
single camera-local track (see ai_cart_event_service.apply_ai_event / _track_key in
frame.py — that scoping is what keeps *billing* correct; this module is only
for *analytics/journey* linkage and must never be used to merge carts).

Heuristic (v1, no ML): "nearest active visitor in time, same branch."
  * If this exact (camera_id, local_track_id) was already seen recently,
    keep returning the same global_track_id (trivial continuity).
  * Otherwise, if the branch has a `global_track_id` that was active in the
    last VISITOR_HANDOFF_WINDOW_SECONDS, hand it to this new sighting —
    modelling "the person who just left camera A's view is probably the one
    who just entered camera B's view."
  * Otherwise, mint a brand new global_track_id (new visitor).

Known limitation: with two or more shoppers crossing camera boundaries
within the same handoff window, this will misattribute journeys between
them. It is a placeholder for a real appearance-embedding ReID model
(e.g. a person-reid CNN over crops from yolo_detector), which is the
natural next step and does not require any interface change here — only
`_pick_handoff_candidate` below would need to start scoring by appearance
similarity instead of pure recency.
"""

from __future__ import annotations

import time
import uuid

import redis.asyncio as aioredis

from app.config.settings import Settings

_TRACK_KEY_FMT = "visitor:track:{org}:{branch}:{camera}:{track}"
_ACTIVE_ZSET_FMT = "visitor:active:{org}:{branch}"


def _client(settings: Settings) -> aioredis.Redis:
    return aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )


async def resolve_global_track_id(
    *,
    settings: Settings,
    organization_id: str,
    branch_id: str,
    camera_id: str | None,
    local_track_id: str,
    now: float | None = None,
) -> str:
    """Return the global_track_id for this sighting, creating one if needed.

    Safe to call even if Redis is briefly unavailable: falls back to minting
    a fresh, unlinked global_track_id rather than raising, since journey
    linkage is a nice-to-have for analytics and must never block the AI
    cart-event pipeline itself.
    """
    now = now if now is not None else time.time()
    camera_key = camera_id or "no-camera"
    track_key = _TRACK_KEY_FMT.format(
        org=organization_id, branch=branch_id, camera=camera_key, track=local_track_id
    )
    active_key = _ACTIVE_ZSET_FMT.format(org=organization_id, branch=branch_id)

    client = _client(settings)
    try:
        existing = await client.get(track_key)
        if existing:
            await client.expire(track_key, settings.VISITOR_TRACK_TTL_SECONDS)
            await client.zadd(active_key, {existing: now})
            return existing

        candidate = await _pick_handoff_candidate(
            client,
            active_key=active_key,
            now=now,
            window_seconds=settings.VISITOR_HANDOFF_WINDOW_SECONDS,
        )
        global_id = candidate or uuid.uuid4().hex

        await client.set(track_key, global_id, ex=settings.VISITOR_TRACK_TTL_SECONDS)
        await client.zadd(active_key, {global_id: now})
        await client.expire(active_key, settings.VISITOR_ACTIVE_TTL_SECONDS)
        return global_id
    except Exception:
        # Redis hiccup shouldn't break checkout — degrade to "no linkage"
        # for this one sighting instead of failing the whole AI event.
        return uuid.uuid4().hex
    finally:
        await client.aclose()


async def _pick_handoff_candidate(
    client: aioredis.Redis,
    *,
    active_key: str,
    now: float,
    window_seconds: int,
) -> str | None:
    """Most recently active global_track_id for this branch, if within window."""
    top = await client.zrevrange(active_key, 0, 0, withscores=True)
    if not top:
        return None
    global_id, last_seen = top[0]
    if now - last_seen > window_seconds:
        return None
    return global_id
