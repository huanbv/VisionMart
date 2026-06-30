"""Application service for the Audit bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from app.modules.audit.infrastructure.models import AuditLog
from app.modules.audit.infrastructure.repositories import (
    SqlAlchemyAuditRepository,
)


class AuditService:
    def __init__(self, repo: SqlAlchemyAuditRepository) -> None:
        self._repo = repo

    async def record(
        self,
        *,
        organization_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        log = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return await self._repo.add(log)

    async def list(
        self,
        *,
        organization_id: uuid.UUID | None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        user_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[AuditLog], int]:
        items = await self._repo.list(
            organization_id=organization_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            skip=skip,
            limit=limit,
        )
        total = await self._repo.count(
            organization_id=organization_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total
