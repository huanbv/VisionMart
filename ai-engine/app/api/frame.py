"""End-to-end frame processing for AI-assisted checkout detection.

AI's job stops at proposing events (product_picked_up / product_returned /
checkout_initiated) to the backend — it never charges anyone. The backend
decides whether to accept the proposal and, for checkout_initiated, freezes
the cart into a "pending checkout" state that always requires an explicit
human confirmation (customer via QR, or staff) before any payment happens.
See backend/app/modules/sales/application/cart_service.py.

Pipeline (per uploaded frame):
  1. Run YOLOv8 + ByteTrack on the frame (persistent per camera).
  2. Split tracked objects into `persons` and `products` (using the
     class-to-SKU mapping — anything not mappable and not `person` is ignored).
  3. Associate each product detection with the nearest person's track_id
     (Euclidean bbox-center distance).
  4. Apply a per-track cooldown to suppress duplicate `product_picked_up`
     events for the same product within a short window.
  5. Emit one AI cart event per product + person association, forwarded to
     the backend `/ai/cart-events` inbox.
  6. Track which (track, sku) pairs are currently "held" (paired) so that
     when a previously-held product stops being paired with that same
     person — while the person is still visible in frame — for longer than
     ``PRODUCT_RETURN_MISSING_SECONDS``, emit `product_returned`. This is a
     proximity heuristic (no separate "shelf zone" detector): it cannot
     distinguish "put back on the shelf" from "occluded for a few seconds",
     which is why the missing-window is deliberately a few seconds, not
     instant.
  7. If the camera is marked as a checkout zone AND at least one person is
     present, additionally emit `checkout_initiated` for each such track.
  8. Optionally run face recognition and attach `customer_id` when a match
     is found.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.security import require_api_key
from app.services.face_recognizer import get_face_recognizer
from app.services.person_tracker import TrackedObject, track_frame
from app.services.product_mapper import map_class_to_sku

logger = logging.getLogger("ai-engine.frame")

router = APIRouter(prefix="/ai", tags=["ai-frame"], dependencies=[Depends(require_api_key)])

_COOLDOWN: dict[str, float] = {}
_CAMERA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CAMERA_TTL_SECONDS = 30.0

# --- "held product" state for product_returned detection ---
# track_key -> {sku: last_seen_ts} for skus that were picked up and are
# still being tracked as "in this person's hands".
_HELD: dict[str, dict[str, float]] = {}
# track_key -> last time this person was seen at all (any camera frame),
# used only to garbage-collect stale entries above — not for return logic.
_TRACK_LAST_SEEN: dict[str, float] = {}
_LAST_CLEANUP_TS = 0.0
_CLEANUP_INTERVAL_SECONDS = 60.0
_STALE_TRACK_SECONDS = 120.0


def _backend_base_url() -> str:
    return os.getenv("BACKEND_BASE_URL", "http://backend:8000/api/v1")


def _api_key() -> str:
    return os.getenv("AI_ENGINE_API_KEY", "change-me-ai-engine-key")


def _cooldown_seconds() -> float:
    try:
        return float(os.getenv("TRACK_PICK_COOLDOWN_SECONDS", "5"))
    except ValueError:
        return 5.0


def _return_missing_seconds() -> float:
    try:
        return float(os.getenv("PRODUCT_RETURN_MISSING_SECONDS", "3"))
    except ValueError:
        return 3.0


def _cleanup_stale_state(now: float) -> None:
    """Opportunistic GC for the module-level dicts above.

    None of `_COOLDOWN` / `_HELD` / `_TRACK_LAST_SEEN` ever had entries
    removed before — over a long-running ai-engine process watching many
    distinct tracks (a busy store, days of uptime) they'd grow without
    bound. Throttled to run at most once per `_CLEANUP_INTERVAL_SECONDS`
    since it's O(n) over all tracked keys.
    """
    global _LAST_CLEANUP_TS
    if now - _LAST_CLEANUP_TS < _CLEANUP_INTERVAL_SECONDS:
        return
    _LAST_CLEANUP_TS = now

    stale_tracks = [
        key
        for key, last_seen in _TRACK_LAST_SEEN.items()
        if now - last_seen > _STALE_TRACK_SECONDS
    ]
    for key in stale_tracks:
        _TRACK_LAST_SEEN.pop(key, None)
        _HELD.pop(key, None)

    stale_cooldowns = [
        key
        for key, last in _COOLDOWN.items()
        if now - last > _STALE_TRACK_SECONDS
    ]
    for key in stale_cooldowns:
        _COOLDOWN.pop(key, None)


async def _fetch_camera(camera_id: uuid.UUID) -> dict[str, Any] | None:
    key = str(camera_id)
    now = time.time()
    cached = _CAMERA_CACHE.get(key)
    if cached and (now - cached[0]) < _CAMERA_TTL_SECONDS:
        return cached[1]
    url = f"{_backend_base_url().rstrip('/')}/ai/cameras/{camera_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"X-AI-Engine-Key": _api_key()})
        if resp.status_code >= 400:
            return None
        data = resp.json()
        _CAMERA_CACHE[key] = (now, data)
        return data
    except httpx.HTTPError:
        logger.exception("fetch camera failed")
        return None


async def _lookup_customer_by_face(
    organization_id: uuid.UUID, ref: str
) -> uuid.UUID | None:
    url = f"{_backend_base_url().rstrip('/')}/ai/customers/by-face-ref"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                headers={"X-AI-Engine-Key": _api_key()},
                params={"organization_id": str(organization_id), "ref": ref},
            )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        if not data:
            return None
        return uuid.UUID(str(data["id"]))
    except (httpx.HTTPError, KeyError, ValueError):
        return None


async def _post_event(event: dict[str, Any]) -> dict[str, Any]:
    url = f"{_backend_base_url().rstrip('/')}/ai/cart-events"
    headers = {"X-AI-Engine-Key": _api_key(), "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=event, headers=headers)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": resp.text}
    return {"status": resp.status_code, "body": body}


def _track_key(camera_key: str, local_track_id: int) -> str:
    """Build a track key that is unique across cameras.

    ByteTrack assigns small sequential integers *per tracker instance*
    (person_tracker.py keeps one tracker per camera_key), so a bare
    "person-3" collides whenever two different cameras happen to both be
    tracking a "track 3" at the same time — the backend would then treat
    two different shoppers on two different cameras as the same cart
    session (`session_id = f"track:{event.track_id}"`), merging their carts.
    Prefixing with camera_key makes the id unique across the whole store.
    """
    return f"{camera_key}:person-{local_track_id}"


def _pair_products_with_persons(
    persons: list[TrackedObject],
    products: list[tuple[TrackedObject, str]],
    camera_key: str,
) -> list[tuple[str, TrackedObject, str]]:
    pairs: list[tuple[str, TrackedObject, str]] = []
    if not persons:
        return pairs
    for product, sku in products:
        best: tuple[float, TrackedObject] | None = None
        for person in persons:
            d = math.hypot(person.cx - product.cx, person.cy - product.cy)
            if best is None or d < best[0]:
                best = (d, person)
        if best is None:
            continue
        track_key = _track_key(camera_key, best[1].track_id)
        pairs.append((track_key, product, sku))
    return pairs


def _cooldown_ok(track_key: str, sku: str) -> bool:
    key = f"{track_key}:{sku}"
    now = time.time()
    last = _COOLDOWN.get(key, 0.0)
    if now - last < _cooldown_seconds():
        return False
    _COOLDOWN[key] = now
    return True


@router.post("/frame")
async def process_frame(
    organization_id: uuid.UUID = Form(...),
    branch_id: uuid.UUID = Form(...),
    camera_id: uuid.UUID | None = Form(None),
    recognize_face: bool = Form(False),
    min_confidence: float = Form(0.4),
    image: UploadFile = File(...),
) -> dict[str, Any]:
    content = await image.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty image upload")

    camera_key = str(camera_id) if camera_id else f"{organization_id}:{branch_id}"
    try:
        detections = await track_frame(content, camera_key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("tracking failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    persons: list[TrackedObject] = []
    products: list[tuple[TrackedObject, str]] = []
    for det in detections:
        if det.confidence < min_confidence:
            continue
        if det.class_name.lower() == "person":
            persons.append(det)
            continue
        sku = map_class_to_sku(
            str(organization_id), str(branch_id), det.class_name
        )
        if sku:
            products.append((det, sku))

    customer_id: uuid.UUID | None = None
    if recognize_face and persons:
        recognizer = get_face_recognizer()
        if recognizer.enabled:
            try:
                match = await recognizer.find_match(content)
            except Exception:  # noqa: BLE001
                match = None
            if match is not None:
                customer_id = await _lookup_customer_by_face(
                    organization_id, match.face_embedding_ref
                )

    camera_info: dict[str, Any] | None = None
    if camera_id is not None:
        camera_info = await _fetch_camera(camera_id)

    now = time.time()
    _cleanup_stale_state(now)

    present_track_keys = {_track_key(camera_key, p.track_id) for p in persons}
    for key in present_track_keys:
        _TRACK_LAST_SEEN[key] = now

    pairs = _pair_products_with_persons(persons, products, camera_key)

    # Refresh "held" state for every pair seen this frame *before* running
    # pickup/return logic below, so a product paired for the first time this
    # frame is never mistaken for one that just disappeared.
    paired_now: dict[str, set[str]] = {}
    for track_key, _product, sku in pairs:
        paired_now.setdefault(track_key, set()).add(sku)
        _HELD.setdefault(track_key, {})[sku] = now

    emitted: list[dict[str, Any]] = []
    for track_key, product, sku in pairs:
        if not _cooldown_ok(track_key, sku):
            continue
        event = {
            "event_id": uuid.uuid4().hex,
            "event_type": "product_picked_up",
            "organization_id": str(organization_id),
            "branch_id": str(branch_id),
            "camera_id": str(camera_id) if camera_id else None,
            "track_id": track_key,
            "product_id": None,
            "product_sku": sku,
            "quantity": 1,
            "confidence": product.confidence,
            "customer_id": str(customer_id) if customer_id else None,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        result = await _post_event(event)
        emitted.append({"event": event, "backend": result})

    # Product-returned detection: a sku that was picked up (has a cooldown
    # entry, i.e. we actually emitted product_picked_up for it) but hasn't
    # been paired with this same, still-visible person for more than
    # PRODUCT_RETURN_MISSING_SECONDS is treated as put back. The person
    # must still be in frame — if they simply left the camera's view we
    # don't know whether they kept the item (e.g. walked to checkout) or
    # put it down, so we stay silent and just let stale state expire (see
    # _cleanup_stale_state).
    missing_seconds = _return_missing_seconds()
    for track_key in present_track_keys:
        held = _HELD.get(track_key)
        if not held:
            continue
        currently_paired = paired_now.get(track_key, set())
        for sku in list(held.keys()):
            if sku in currently_paired:
                continue
            last_seen = held[sku]
            if now - last_seen < missing_seconds:
                continue
            pick_key = f"{track_key}:{sku}"
            if pick_key not in _COOLDOWN:
                # Was paired briefly but never actually resulted in a cart
                # addition (still within the original pickup cooldown) —
                # nothing to return.
                del held[sku]
                continue
            event = {
                "event_id": uuid.uuid4().hex,
                "event_type": "product_returned",
                "organization_id": str(organization_id),
                "branch_id": str(branch_id),
                "camera_id": str(camera_id) if camera_id else None,
                "track_id": track_key,
                "product_id": None,
                "product_sku": sku,
                "quantity": 1,
                "confidence": 1.0,
                "customer_id": str(customer_id) if customer_id else None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            result = await _post_event(event)
            emitted.append({"event": event, "backend": result})
            del held[sku]
            # Clear the cooldown too so picking the same item back up right
            # away emits a fresh product_picked_up instead of being
            # suppressed by the original cooldown window.
            _COOLDOWN.pop(pick_key, None)
        if not held:
            _HELD.pop(track_key, None)

    if camera_info and camera_info.get("is_checkout_zone") and persons:
        for person in persons:
            track_key = _track_key(camera_key, person.track_id)
            if not _cooldown_ok(track_key, "__checkout__"):
                continue
            event = {
                "event_id": uuid.uuid4().hex,
                "event_type": "checkout_initiated",
                "organization_id": str(organization_id),
                "branch_id": str(branch_id),
                "camera_id": str(camera_id) if camera_id else None,
                "track_id": track_key,
                "product_id": None,
                "product_sku": None,
                "quantity": 1,
                "confidence": person.confidence,
                "customer_id": str(customer_id) if customer_id else None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            result = await _post_event(event)
            emitted.append({"event": event, "backend": result})

    return {
        "detections": [
            {
                "track_id": d.track_id,
                "class_name": d.class_name,
                "confidence": d.confidence,
                "bbox": {"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2},
            }
            for d in detections
        ],
        "persons": len(persons),
        "products": len(products),
        "is_checkout_zone": bool(camera_info and camera_info.get("is_checkout_zone")),
        "customer_id": str(customer_id) if customer_id else None,
        "emitted_events": emitted,
    }
