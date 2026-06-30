"""SQLAlchemy repositories for the Camera bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.camera.infrastructure.models import Camera
from app.modules.tenancy.infrastructure.models import Branch


class SqlAlchemyCameraRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        branch_id: uuid.UUID | None = None,
        is_active: bool | None = None,
        is_online: bool | None = None,
    ) -> tuple[list[tuple[Camera, Branch]], int]:
        BranchAlias = aliased(Branch)
        base = (
            select(Camera, BranchAlias)
            .join(BranchAlias, BranchAlias.id == Camera.branch_id)
            .where(
                Camera.organization_id == organization_id,
                Camera.is_deleted.is_(False),
            )
        )
        total_stmt = select(func.count(Camera.id)).where(
            Camera.organization_id == organization_id,
            Camera.is_deleted.is_(False),
        )
        if search:
            pattern = f"%{search.lower()}%"
            cond = (
                func.lower(Camera.name).like(pattern)
                | func.lower(Camera.code).like(pattern)
                | func.lower(func.coalesce(Camera.location, "")).like(pattern)
            )
            base = base.where(cond)
            total_stmt = total_stmt.where(cond)
        if branch_id is not None:
            base = base.where(Camera.branch_id == branch_id)
            total_stmt = total_stmt.where(Camera.branch_id == branch_id)
        if is_active is not None:
            base = base.where(Camera.is_active.is_(is_active))
            total_stmt = total_stmt.where(Camera.is_active.is_(is_active))
        if is_online is not None:
            base = base.where(Camera.is_online.is_(is_online))
            total_stmt = total_stmt.where(Camera.is_online.is_(is_online))

        total = (await self._session.execute(total_stmt)).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(Camera.created_at.desc()).offset(skip).limit(limit)
            )
        ).all()
        return [(r[0], r[1]) for r in rows], int(total)

    async def get_by_id(
        self, organization_id: uuid.UUID, camera_id: uuid.UUID
    ) -> Camera | None:
        stmt = select(Camera).where(
            Camera.id == camera_id,
            Camera.organization_id == organization_id,
            Camera.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def code_exists(
        self,
        organization_id: uuid.UUID,
        code: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(Camera.id).where(
            Camera.organization_id == organization_id,
            Camera.code == code,
            Camera.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(Camera.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def get_branch_in_org(
        self, organization_id: uuid.UUID, branch_id: uuid.UUID
    ) -> Branch | None:
        stmt = select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == organization_id,
            Branch.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, camera: Camera) -> Camera:
        self._session.add(camera)
        await self._session.commit()
        await self._session.refresh(camera)
        return camera

    async def save(self, camera: Camera) -> Camera:
        await self._session.commit()
        await self._session.refresh(camera)
        return camera

    async def soft_delete(self, camera: Camera) -> None:
        camera.is_deleted = True
        camera.is_active = False
        camera.is_online = False
        await self._session.commit()

    async def mark_seen(self, camera: Camera, *, online: bool) -> Camera:
        camera.is_online = online
        camera.last_seen_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(camera)
        return camera

    async def stats(
        self, organization_id: uuid.UUID
    ) -> tuple[int, int, int]:
        stmt = select(
            func.count(Camera.id),
            func.coalesce(func.sum(cast(Camera.is_online, Integer)), 0),
            func.coalesce(func.sum(cast(Camera.is_active, Integer)), 0),
        ).where(
            Camera.organization_id == organization_id,
            Camera.is_deleted.is_(False),
        )
        row = (await self._session.execute(stmt)).one()
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)
