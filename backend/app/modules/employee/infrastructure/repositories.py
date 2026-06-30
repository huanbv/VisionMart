"""SQLAlchemy repositories for the Employee bounded context."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.employee.infrastructure.models import Employee
from app.modules.identity.infrastructure.models import User
from app.modules.tenancy.infrastructure.models import Branch


class SqlAlchemyEmployeeRepository:
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
        position: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[tuple[Employee, Branch, User | None]], int]:
        UserAlias = aliased(User)
        BranchAlias = aliased(Branch)
        base = (
            select(Employee, BranchAlias, UserAlias)
            .join(BranchAlias, BranchAlias.id == Employee.branch_id)
            .outerjoin(UserAlias, UserAlias.id == Employee.user_id)
            .where(
                Employee.organization_id == organization_id,
                Employee.is_deleted.is_(False),
            )
        )
        if search:
            pattern = f"%{search.lower()}%"
            base = base.where(
                func.lower(Employee.full_name).like(pattern)
                | func.lower(Employee.code).like(pattern)
                | func.lower(func.coalesce(Employee.position, "")).like(pattern)
            )
        if branch_id is not None:
            base = base.where(Employee.branch_id == branch_id)
        if position is not None:
            base = base.where(Employee.position == position)
        if is_active is not None:
            base = base.where(Employee.is_active.is_(is_active))

        total_stmt = select(func.count(Employee.id)).where(
            Employee.organization_id == organization_id,
            Employee.is_deleted.is_(False),
        )
        if search:
            pattern = f"%{search.lower()}%"
            total_stmt = total_stmt.where(
                func.lower(Employee.full_name).like(pattern)
                | func.lower(Employee.code).like(pattern)
                | func.lower(func.coalesce(Employee.position, "")).like(pattern)
            )
        if branch_id is not None:
            total_stmt = total_stmt.where(Employee.branch_id == branch_id)
        if position is not None:
            total_stmt = total_stmt.where(Employee.position == position)
        if is_active is not None:
            total_stmt = total_stmt.where(Employee.is_active.is_(is_active))

        total = (await self._session.execute(total_stmt)).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(Employee.created_at.desc()).offset(skip).limit(limit)
            )
        ).all()
        items: list[tuple[Employee, Branch, User | None]] = [
            (row[0], row[1], row[2]) for row in rows
        ]
        return items, int(total)

    async def get_by_id(
        self, organization_id: uuid.UUID, employee_id: uuid.UUID
    ) -> Employee | None:
        stmt = select(Employee).where(
            Employee.id == employee_id,
            Employee.organization_id == organization_id,
            Employee.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def code_exists(
        self,
        organization_id: uuid.UUID,
        code: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(Employee.id).where(
            Employee.organization_id == organization_id,
            Employee.code == code,
            Employee.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(Employee.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def user_linked(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(Employee.id).where(
            Employee.organization_id == organization_id,
            Employee.user_id == user_id,
            Employee.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(Employee.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def get_user_in_org(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> User | None:
        stmt = select(User).where(
            User.id == user_id,
            User.organization_id == organization_id,
            User.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_branch_in_org(
        self, organization_id: uuid.UUID, branch_id: uuid.UUID
    ) -> Branch | None:
        stmt = select(Branch).where(
            Branch.id == branch_id,
            Branch.organization_id == organization_id,
            Branch.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, employee: Employee) -> Employee:
        self._session.add(employee)
        await self._session.commit()
        await self._session.refresh(employee)
        return employee

    async def save(self, employee: Employee) -> Employee:
        await self._session.commit()
        await self._session.refresh(employee)
        return employee

    async def soft_delete(self, employee: Employee) -> None:
        employee.is_deleted = True
        employee.is_active = False
        await self._session.commit()
