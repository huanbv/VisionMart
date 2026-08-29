"""Notification router (in-app inbox for the current user)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.notification.application.services import NotificationService
from app.modules.notification.application.alert_service import AlertService
from app.modules.notification.infrastructure.repositories import (
    SqlAlchemyNotificationRepository,
)
from app.modules.notification.schemas.notification import (
    MarkAllReadResponse,
    NotificationCreate,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)

router = APIRouter(prefix="/notifications", tags=["notification"])


def _service(session: AsyncSession) -> NotificationService:
    return NotificationService(SqlAlchemyNotificationRepository(session))


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    unread_only: bool = False,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationListResponse:
    svc = _service(session)
    items, total = await svc.list(
        current.organization_id,
        current.user_id,
        skip=skip,
        limit=limit,
        unread_only=unread_only,
    )
    unread = await svc.unread_count(current.organization_id, current.user_id)
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
        skip=skip,
        limit=limit,
        unread=unread,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UnreadCountResponse:
    unread = await _service(session).unread_count(
        current.organization_id, current.user_id
    )
    return UnreadCountResponse(unread=unread)


@router.post(
    "/{notification_id}/read",
    response_model=NotificationResponse,
)
async def mark_read(
    notification_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NotificationResponse:
    try:
        n = await _service(session).mark_read(
            current.organization_id, current.user_id, notification_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return NotificationResponse.model_validate(n)


@router.post("/read-all", response_model=MarkAllReadResponse)
async def mark_all_read(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MarkAllReadResponse:
    updated = await _service(session).mark_all_read(
        current.organization_id, current.user_id
    )
    return MarkAllReadResponse(updated=updated)


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_notification(
    notification_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await _service(session).delete(
            current.organization_id, current.user_id, notification_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_notification(
    payload: NotificationCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> NotificationResponse:
    try:
        n = await _service(session).create(
            current.organization_id,
            type=payload.type,
            title=payload.title,
            body=payload.body,
            recipient_user_id=payload.recipient_user_id,
            recipient_role_id=payload.recipient_role_id,
            channel=payload.channel,
            priority=payload.priority,
            payload=payload.payload,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return NotificationResponse.model_validate(n)


@router.post("/alerts/scan", status_code=status.HTTP_200_OK)
async def trigger_alert_scan(
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await AlertService(session).scan_organization(current.organization_id)
    return {"organization_id": str(current.organization_id), **result}
