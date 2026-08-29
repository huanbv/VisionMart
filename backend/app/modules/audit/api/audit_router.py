"""Admin-only router for browsing the immutable audit log."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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


@router.get("/export.csv")
async def export_audit_logs_csv(
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    user_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    max_rows: int = Query(10000, ge=1, le=100000),
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    org_filter = (
        None if "super_admin" in current.roles else current.organization_id
    )
    repo = SqlAlchemyAuditRepository(session)
    batch_size = 500

    async def _row_batches():
        offset = 0
        remaining = max_rows
        while remaining > 0:
            page_size = min(batch_size, remaining)
            events = await repo.list(
                organization_id=org_filter,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                user_id=user_id,
                date_from=date_from,
                date_to=date_to,
                skip=offset,
                limit=page_size,
            )
            if not events:
                return
            for ev in events:
                yield ev
            offset += len(events)
            if len(events) < page_size:
                return
            remaining -= len(events)

    async def _generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "created_at",
                "organization_id",
                "user_id",
                "action",
                "resource_type",
                "resource_id",
                "ip_address",
                "user_agent",
                "old_values",
                "new_values",
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        async for ev in _row_batches():
            writer.writerow(
                [
                    str(ev.id),
                    ev.created_at.isoformat() if ev.created_at else "",
                    str(ev.organization_id) if ev.organization_id else "",
                    str(ev.user_id) if ev.user_id else "",
                    ev.action,
                    ev.resource_type,
                    ev.resource_id or "",
                    ev.ip_address or "",
                    ev.user_agent or "",
                    json.dumps(ev.old_values, ensure_ascii=False)
                    if ev.old_values
                    else "",
                    json.dumps(ev.new_values, ensure_ascii=False)
                    if ev.new_values
                    else "",
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"audit_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        _generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
