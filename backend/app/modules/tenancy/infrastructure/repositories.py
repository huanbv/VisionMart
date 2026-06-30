"""SQLAlchemy repositories for the Tenancy bounded context."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tenancy.infrastructure.models import Branch, Organization


class SqlAlchemyOrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        stmt = select(Organization).where(
            Organization.id == organization_id,
            Organization.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


class SqlAlchemyBranchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
    ) -> tuple[list[Branch], int]:
        base = select(Branch).where(
            Branch.organization_id == organization_id,
            Branch.is_deleted.is_(False),
        )
        if search:
            pattern = f"%{search.lower()}%"
            base = base.where(
                func.lower(Branch.name).like(pattern)
                | func.lower(Branch.code).like(pattern)
            )

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        items_stmt = base.order_by(Branch.created_at.desc()).offset(skip).limit(limit)
        items = (await self._session.execute(items_stmt)).scalars().all()
        return list(items), int(total)

    async def get_by_id(
        self, organization_id: uuid.UUID, branch_id: uuid.UUID
    ) -> Branch | None:
        stmt = select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == organization_id,
            Branch.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def code_exists(
        self,
        organization_id: uuid.UUID,
        code: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(Branch.id).where(
            Branch.organization_id == organization_id,
            Branch.code == code,
            Branch.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(Branch.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def add(self, branch: Branch) -> Branch:
        self._session.add(branch)
        await self._session.commit()
        await self._session.refresh(branch)
        return branch

    async def save(self, branch: Branch) -> Branch:
        await self._session.commit()
        await self._session.refresh(branch)
        return branch

    async def soft_delete(self, branch: Branch) -> None:
        branch.is_deleted = True
        await self._session.commit()
