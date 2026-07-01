"""Inbound endpoint for AI Engine cart proposals.

Authentication: shared API key via `X-AI-Engine-Key` header (rotate via env).
AI Engine posts observations here; the backend decides what to do with them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.modules.sales.api.cart_router import build_cart_service
from app.modules.sales.schemas.ai_events import (
    AICartEventRequest,
    AICartEventResponse,
)

router = APIRouter(prefix="/ai", tags=["ai-cart"])


def _require_api_key(
    x_ai_engine_key: str | None = Header(default=None, alias="X-AI-Engine-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.AI_ENGINE_API_KEY
    if not expected or x_ai_engine_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid AI engine key",
        )


@router.post(
    "/cart-events",
    response_model=AICartEventResponse,
    dependencies=[Depends(_require_api_key)],
)
async def ingest_cart_event(
    event: AICartEventRequest,
    session: AsyncSession = Depends(get_session),
) -> AICartEventResponse:
    service = build_cart_service(session)
    reason, cart, order = await service.apply_ai_event(event)
    accepted = reason == "accepted"
    return AICartEventResponse(
        accepted=accepted,
        reason=None if accepted else reason,
        cart_id=cart.id if cart else None,
        order_id=order.id if order else None,
    )
