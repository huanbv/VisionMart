"""Application services for the Tenancy bounded context."""

from __future__ import annotations

import uuid

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.tenancy.infrastructure.models import Branch, Organization
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
    SqlAlchemyOrganizationRepository,
)


class OrganizationService:
    def __init__(self, repository: SqlAlchemyOrganizationRepository) -> None:
        self._repo = repository

    async def get(self, organization_id: uuid.UUID) -> Organization:
        org = await self._repo.get_by_id(organization_id)
        if org is None:
            raise NotFoundError("Organization not found")
        return org

    async def update(
        self,
        organization_id: uuid.UUID,
        *,
        name: str | None = None,
        settings: dict | None = None,
    ) -> Organization:
        org = await self.get(organization_id)
        if name is not None:
            org.name = name
        if settings is not None:
            org.settings = settings
        await self._repo._session.commit()  # noqa: SLF001
        await self._repo._session.refresh(org)  # noqa: SLF001
        return org


class BranchService:
    def __init__(self, repository: SqlAlchemyBranchRepository) -> None:
        self._repo = repository

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
    ) -> tuple[list[Branch], int]:
        return await self._repo.list_for_org(
            organization_id, skip=skip, limit=limit, search=search
        )

    async def get(self, organization_id: uuid.UUID, branch_id: uuid.UUID) -> Branch:
        branch = await self._repo.get_by_id(organization_id, branch_id)
        if branch is None:
            raise NotFoundError("Branch not found")
        return branch

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        name: str,
        code: str,
        address: dict | None,
        timezone: str,
        is_active: bool,
    ) -> Branch:
        if await self._repo.code_exists(organization_id, code):
            raise ConflictError(f"Branch code '{code}' already exists")
        branch = Branch(
            organization_id=organization_id,
            name=name,
            code=code,
            address=address,
            timezone=timezone,
            is_active=is_active,
        )
        return await self._repo.add(branch)

    async def update(
        self,
        organization_id: uuid.UUID,
        branch_id: uuid.UUID,
        *,
        name: str | None = None,
        code: str | None = None,
        address: dict | None = None,
        timezone: str | None = None,
        is_active: bool | None = None,
    ) -> Branch:
        branch = await self.get(organization_id, branch_id)
        if code is not None and code != branch.code:
            if await self._repo.code_exists(
                organization_id, code, exclude_id=branch_id
            ):
                raise ConflictError(f"Branch code '{code}' already exists")
            branch.code = code
        if name is not None:
            branch.name = name
        if address is not None:
            branch.address = address
        if timezone is not None:
            branch.timezone = timezone
        if is_active is not None:
            branch.is_active = is_active
        return await self._repo.save(branch)

    async def delete(
        self, organization_id: uuid.UUID, branch_id: uuid.UUID
    ) -> None:
        branch = await self.get(organization_id, branch_id)
        await self._repo.soft_delete(branch)
