"""Admin-only router for browsing the immutable audit log."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import CurrentUser, require_roles
from app.modules.audit.application.audit_service import AuditService
from app.modules.audit.infrastructure.repositories import (
    SqlAlchemyAuditRepository,
)
from app.modules.audit.schemas.audit_log import (
    AuditLogListResponse,
    AuditLogResponse,
)

router = APIRouter(prefix="/audit-logs", tags=["audit"])


def _service(session: AsyncSession) -> AuditService:
    return AuditService(SqlAlchemyAuditRepository(session))


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    user_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> AuditLogListResponse:
    org_filter = (
        None if "super_admin" in current.roles else current.organization_id
    )
    items, total = await _service(session).list(
        organization_id=org_filter,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit,
    )
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(it) for it in items],
        total=total,
        skip=skip,
        limit=limit,
    )
