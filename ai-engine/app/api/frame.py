"""End-to-end frame processing for autonomous checkout.

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
  6. If the camera is marked as a checkout zone AND at least one person is
     present, additionally emit `checkout_initiated` for each such track.
  7. Optionally run face recognition and attach `customer_id` when a match
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

from app.services.face_recognizer import get_face_recognizer
from app.services.person_tracker import TrackedObject, track_frame
from app.services.product_mapper import map_class_to_sku

logger = logging.getLogger("ai-engine.frame")

router = APIRouter(prefix="/ai", tags=["ai-frame"])

_COOLDOWN: dict[str, float] = {}
_CAMERA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CAMERA_TTL_SECONDS = 30.0


def _backend_base_url() -> str:
    return os.getenv("BACKEND_BASE_URL", "http://backend:8000/api/v1")


def _api_key() -> str:
    return os.getenv("AI_ENGINE_API_KEY", "change-me-ai-engine-key")


def _cooldown_seconds() -> float:
    try:
        return float(os.getenv("TRACK_PICK_COOLDOWN_SECONDS", "5"))
    except ValueError:
        return 5.0


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


def _pair_products_with_persons(
    persons: list[TrackedObject],
    products: list[tuple[TrackedObject, str]],
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
        track_key = f"person-{best[1].track_id}"
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

    pairs = _pair_products_with_persons(persons, products)
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

    if camera_info and camera_info.get("is_checkout_zone") and persons:
        for person in persons:
            track_key = f"person-{person.track_id}"
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
