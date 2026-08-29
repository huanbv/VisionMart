"""Inbound endpoint for AI Engine cart proposals.

Authentication: shared API key via `X-AI-Engine-Key` header (rotate via env).
AI Engine posts observations here; the backend decides what to do with them.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.modules.camera.infrastructure.models import Camera
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.customer.infrastructure.models import Customer
from app.modules.sales.api.cart_router import build_cart_service, build_checkout_service
from app.modules.sales.application.ai_cart_event_service import AiCartEventService
from app.modules.sales.schemas.ai_events import (
    AICartEventRequest,
    AICartEventResponse,
)


def build_ai_cart_event_service(session: AsyncSession) -> AiCartEventService:
    return AiCartEventService(
        cart_service=build_cart_service(session),
        checkout_service=build_checkout_service(session),
        products=SqlAlchemyProductRepository(session),
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


class AICameraInfo(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    branch_id: uuid.UUID
    code: str
    name: str
    is_active: bool
    is_online: bool
    is_checkout_zone: bool
    alert_classes: str | None
    alert_min_confidence: float | None
    # Vung nhan dien ve tren Admin — di kem luon trong lan goi camera-info
    # ma ai-engine da thuc hien san (va cache 30s), nen khong them mot luot
    # goi mang nao tren duong xu ly khung hinh.
    roi_zones: list | None = None


class AICustomerInfo(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    branch_id: uuid.UUID | None
    full_name: str | None
    face_embedding_ref: str | None


@router.post(
    "/cart-events",
    response_model=AICartEventResponse,
    dependencies=[Depends(_require_api_key)],
)
async def ingest_cart_event(
    event: AICartEventRequest,
    session: AsyncSession = Depends(get_session),
) -> AICartEventResponse:
    service = build_ai_cart_event_service(session)
    reason, cart, order = await service.apply_ai_event(event)
    accepted = reason in (
        "accepted",
        "accepted_pending_confirmation",
        "accepted_already_in_cart",  # SKU đã trong giỏ — idempotent, không phải lỗi
    )
    return AICartEventResponse(
        accepted=accepted,
        # Keep the "pending confirmation" nuance visible to the AI engine /
        # caller even though the event was accepted — it did NOT result in
        # an instant charge like a plain "accepted" used to.
        reason=None if reason == "accepted" else reason,
        cart_id=cart.id if cart else None,
        order_id=order.id if order else None,
    )


@router.get(
    "/cameras/{camera_id}",
    response_model=AICameraInfo,
    dependencies=[Depends(_require_api_key)],
)
async def get_ai_camera_info(
    camera_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> AICameraInfo:
    stmt = select(Camera).where(
        Camera.id == camera_id, Camera.is_deleted.is_(False)
    )
    camera = (await session.execute(stmt)).scalar_one_or_none()
    if camera is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Camera not found")
    return AICameraInfo(
        id=camera.id,
        organization_id=camera.organization_id,
        branch_id=camera.branch_id,
        code=camera.code,
        name=camera.name,
        is_active=camera.is_active,
        is_online=camera.is_online,
        is_checkout_zone=camera.is_checkout_zone,
        alert_classes=camera.alert_classes,
        alert_min_confidence=camera.alert_min_confidence,
        roi_zones=camera.roi_zones,
    )


@router.get(
    "/customers/by-face-ref",
    response_model=AICustomerInfo | None,
    dependencies=[Depends(_require_api_key)],
)
async def lookup_customer_by_face_ref(
    organization_id: uuid.UUID = Query(...),
    ref: str = Query(..., min_length=1, max_length=255),
    session: AsyncSession = Depends(get_session),
) -> AICustomerInfo | None:
    stmt = select(Customer).where(
        Customer.organization_id == organization_id,
        Customer.face_embedding_ref == ref,
        Customer.is_deleted.is_(False),
        Customer.is_active.is_(True),
    )
    customer = (await session.execute(stmt)).scalar_one_or_none()
    if customer is None:
        return None
    return AICustomerInfo(
        id=customer.id,
        organization_id=customer.organization_id,
        branch_id=customer.branch_id,
        full_name=customer.full_name,
        face_embedding_ref=customer.face_embedding_ref,
    )
