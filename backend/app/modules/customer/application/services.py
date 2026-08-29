"""Application services for the Customer bounded context."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.customer.infrastructure.models import Customer
from app.modules.customer.infrastructure.repositories import (
    SqlAlchemyCustomerRepository,
)


_UNSET: object = object()


class CustomerService:
    def __init__(self, repository: SqlAlchemyCustomerRepository) -> None:
        self._repo = repository

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
        search: str | None,
        branch_id: uuid.UUID | None,
        is_active: bool | None,
    ) -> tuple[list[Customer], int]:
        return await self._repo.list_for_org(
            organization_id,
            skip=skip,
            limit=limit,
            search=search,
            branch_id=branch_id,
            is_active=is_active,
        )

    async def get(
        self, organization_id: uuid.UUID, customer_id: uuid.UUID
    ) -> Customer:
        c = await self._repo.get_by_id(organization_id, customer_id)
        if c is None:
            raise NotFoundError("Customer not found")
        return c

    async def stats(
        self, organization_id: uuid.UUID, customer_id: uuid.UUID
    ) -> tuple[int, Decimal]:
        await self.get(organization_id, customer_id)
        return await self._repo.stats(organization_id, customer_id)

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        full_name: str | None,
        email: str | None,
        phone: str | None,
        branch_id: uuid.UUID | None,
        attributes: dict | None,
        is_active: bool,
    ) -> Customer:
        if email and await self._repo.email_exists(organization_id, email):
            raise ConflictError(f"Email '{email}' already exists")
        if phone and await self._repo.phone_exists(organization_id, phone):
            raise ConflictError(f"Phone '{phone}' already exists")
        c = Customer(
            organization_id=organization_id,
            full_name=full_name,
            email=email,
            phone=phone,
            branch_id=branch_id,
            attributes=attributes,
            is_active=is_active,
        )
        return await self._repo.add(c)

    async def update(
        self,
        organization_id: uuid.UUID,
        customer_id: uuid.UUID,
        *,
        full_name: object = _UNSET,
        email: object = _UNSET,
        phone: object = _UNSET,
        branch_id: object = _UNSET,
        attributes: object = _UNSET,
        is_active: bool | None = None,
    ) -> Customer:
        c = await self.get(organization_id, customer_id)
        if full_name is not _UNSET:
            c.full_name = full_name  # type: ignore[assignment]
        if email is not _UNSET:
            if email and await self._repo.email_exists(
                organization_id, str(email), exclude_id=customer_id
            ):
                raise ConflictError(f"Email '{email}' already exists")
            c.email = email  # type: ignore[assignment]
        if phone is not _UNSET:
            if phone and await self._repo.phone_exists(
                organization_id, str(phone), exclude_id=customer_id
            ):
                raise ConflictError(f"Phone '{phone}' already exists")
            c.phone = phone  # type: ignore[assignment]
        if branch_id is not _UNSET:
            c.branch_id = branch_id  # type: ignore[assignment]
        if attributes is not _UNSET:
            c.attributes = attributes  # type: ignore[assignment]
        if is_active is not None:
            c.is_active = is_active
        return await self._repo.save(c)

    async def delete(
        self, organization_id: uuid.UUID, customer_id: uuid.UUID
    ) -> None:
        c = await self.get(organization_id, customer_id)
        await self._repo.soft_delete(c)
