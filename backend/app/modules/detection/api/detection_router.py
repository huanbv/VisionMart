"""Router for browsing persisted detection events."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user
from app.modules.detection.application.detection_service import DetectionService
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)
from app.modules.detection.schemas.detection import (
    DetectionEventListResponse,
    DetectionEventResponse,
    DetectionEventSummary,
)

router = APIRouter(prefix="/detections", tags=["detection"])


def _service(session: AsyncSession) -> DetectionService:
    return DetectionService(SqlAlchemyDetectionRepository(session))


@router.get("", response_model=DetectionEventListResponse)
async def list_detections(
    camera_id: uuid.UUID | None = None,
    model: str | None = None,
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DetectionEventListResponse:
    items, total = await _service(session).list(
        organization_id=current.organization_id,
        camera_id=camera_id,
        model=model,
        min_confidence=min_confidence,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit,
    )
    return DetectionEventListResponse(
        items=[DetectionEventSummary.model_validate(it) for it in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{event_id}", response_model=DetectionEventResponse)
async def get_detection(
    event_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DetectionEventResponse:
    event = await _service(session).get(current.organization_id, event_id)
    if event is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Detection event not found"
        )
    return DetectionEventResponse.model_validate(event)
