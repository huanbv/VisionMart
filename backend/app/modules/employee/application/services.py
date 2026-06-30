"""Application services for the Employee bounded context."""

from __future__ import annotations

import uuid
from datetime import date

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.employee.infrastructure.models import Employee
from app.modules.employee.infrastructure.repositories import (
    SqlAlchemyEmployeeRepository,
)
from app.modules.identity.infrastructure.models import User
from app.modules.tenancy.infrastructure.models import Branch


_UNSET: object = object()


class EmployeeService:
    def __init__(self, repository: SqlAlchemyEmployeeRepository) -> None:
        self._repo = repository

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
        search: str | None,
        branch_id: uuid.UUID | None,
        position: str | None,
        is_active: bool | None,
    ) -> tuple[list[tuple[Employee, Branch, User | None]], int]:
        return await self._repo.list_for_org(
            organization_id,
            skip=skip,
            limit=limit,
            search=search,
            branch_id=branch_id,
            position=position,
            is_active=is_active,
        )

    async def get(
        self, organization_id: uuid.UUID, employee_id: uuid.UUID
    ) -> Employee:
        e = await self._repo.get_by_id(organization_id, employee_id)
        if e is None:
            raise NotFoundError("Employee not found")
        return e

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        code: str,
        full_name: str,
        branch_id: uuid.UUID,
        position: str | None,
        user_id: uuid.UUID | None,
        hired_at: date | None,
        is_active: bool,
    ) -> Employee:
        branch = await self._repo.get_branch_in_org(organization_id, branch_id)
        if branch is None:
            raise ValidationError("Branch does not belong to this organization")
        if await self._repo.code_exists(organization_id, code):
            raise ConflictError(f"Employee code '{code}' already exists")
        if user_id is not None:
            user = await self._repo.get_user_in_org(organization_id, user_id)
            if user is None:
                raise ValidationError("User does not belong to this organization")
            if await self._repo.user_linked(organization_id, user_id):
                raise ConflictError("User is already linked to another employee")
        e = Employee(
            organization_id=organization_id,
            branch_id=branch_id,
            user_id=user_id,
            code=code,
            full_name=full_name,
            position=position,
            hired_at=hired_at,
            is_active=is_active,
        )
        return await self._repo.add(e)

    async def update(
        self,
        organization_id: uuid.UUID,
        employee_id: uuid.UUID,
        *,
        code: str | None = None,
        full_name: str | None = None,
        branch_id: uuid.UUID | None = None,
        position: object = _UNSET,
        user_id: object = _UNSET,
        hired_at: object = _UNSET,
        is_active: bool | None = None,
    ) -> Employee:
        e = await self.get(organization_id, employee_id)
        if code is not None and code != e.code:
            if await self._repo.code_exists(
                organization_id, code, exclude_id=employee_id
            ):
                raise ConflictError(f"Employee code '{code}' already exists")
            e.code = code
        if full_name is not None:
            e.full_name = full_name
        if branch_id is not None and branch_id != e.branch_id:
            branch = await self._repo.get_branch_in_org(organization_id, branch_id)
            if branch is None:
                raise ValidationError("Branch does not belong to this organization")
            e.branch_id = branch_id
        if position is not _UNSET:
            e.position = position  # type: ignore[assignment]
        if user_id is not _UNSET:
            if user_id is None:
                e.user_id = None
            else:
                user = await self._repo.get_user_in_org(
                    organization_id, user_id  # type: ignore[arg-type]
                )
                if user is None:
                    raise ValidationError(
                        "User does not belong to this organization"
                    )
                if await self._repo.user_linked(
                    organization_id,
                    user_id,  # type: ignore[arg-type]
                    exclude_id=employee_id,
                ):
                    raise ConflictError(
                        "User is already linked to another employee"
                    )
                e.user_id = user_id  # type: ignore[assignment]
        if hired_at is not _UNSET:
            e.hired_at = hired_at  # type: ignore[assignment]
        if is_active is not None:
            e.is_active = is_active
        return await self._repo.save(e)

    async def terminate(
        self,
        organization_id: uuid.UUID,
        employee_id: uuid.UUID,
        *,
        terminated_at: date,
    ) -> Employee:
        e = await self.get(organization_id, employee_id)
        e.terminated_at = terminated_at
        e.is_active = False
        return await self._repo.save(e)

    async def delete(
        self, organization_id: uuid.UUID, employee_id: uuid.UUID
    ) -> None:
        e = await self.get(organization_id, employee_id)
        await self._repo.soft_delete(e)
