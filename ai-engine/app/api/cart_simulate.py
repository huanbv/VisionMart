"""AI Engine → Backend cart-event simulator.

For MVP the AI stack is not yet wired to real object tracking + recognition,
so this endpoint lets operators (or the demo script) inject synthetic
`ProductPickedUp` / `ProductReturned` / `CheckoutInitiated` events.

The endpoint accepts a payload, adds the API key header, and forwards it to
the backend's `/api/v1/ai/cart-events` inbox. Later sprints will replace the
manual trigger with a real tracker + recognizer loop.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.security import require_api_key

logger = logging.getLogger("ai-engine.cart")

router = APIRouter(prefix="/cart", tags=["cart"], dependencies=[Depends(require_api_key)])


class CartEventSimulation(BaseModel):
    event_type: Literal[
        "product_picked_up", "product_returned", "checkout_initiated"
    ]
    organization_id: uuid.UUID
    branch_id: uuid.UUID
    track_id: str = Field(..., min_length=1, max_length=80)
    product_id: uuid.UUID | None = None
    product_sku: str | None = None
    quantity: int = Field(default=1, gt=0, le=20)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    camera_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None


class CartEventForwardResponse(BaseModel):
    forwarded: bool
    backend_status: int
    backend_body: dict


def _backend_base_url() -> str:
    return os.getenv("BACKEND_BASE_URL", "http://backend:8000/api/v1")


def _api_key() -> str:
    return os.getenv("AI_ENGINE_API_KEY", "change-me-ai-engine-key")


@router.post("/simulate", response_model=CartEventForwardResponse)
async def simulate_cart_event(
    payload: CartEventSimulation,
) -> CartEventForwardResponse:
    if payload.product_id is None and not payload.product_sku:
        if payload.event_type != "checkout_initiated":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Either product_id or product_sku is required",
            )

    body = {
        "event_id": uuid.uuid4().hex,
        "event_type": payload.event_type,
        "organization_id": str(payload.organization_id),
        "branch_id": str(payload.branch_id),
        "camera_id": str(payload.camera_id) if payload.camera_id else None,
        "track_id": payload.track_id,
        "product_id": str(payload.product_id) if payload.product_id else None,
        "product_sku": payload.product_sku,
        "quantity": payload.quantity,
        "confidence": payload.confidence,
        "customer_id": str(payload.customer_id) if payload.customer_id else None,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }

    url = f"{_backend_base_url().rstrip('/')}/ai/cart-events"
    headers = {"X-AI-Engine-Key": _api_key(), "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.exception("cart-event forward failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    try:
        parsed = resp.json()
    except Exception:
        parsed = {"raw": resp.text}

    return CartEventForwardResponse(
        forwarded=resp.status_code < 400,
        backend_status=resp.status_code,
        backend_body=parsed,
    )
