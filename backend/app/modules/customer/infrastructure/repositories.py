"""SQLAlchemy repositories for the Customer bounded context."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customer.infrastructure.models import Customer
from app.modules.sales.infrastructure.models import Order, OrderStatus


class SqlAlchemyCustomerRepository:
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
    ) -> tuple[list[Customer], int]:
        base = select(Customer).where(
            Customer.organization_id == organization_id,
            Customer.is_deleted.is_(False),
        )
        if search:
            pattern = f"%{search.lower()}%"
            base = base.where(
                func.lower(func.coalesce(Customer.full_name, "")).like(pattern)
                | func.lower(func.coalesce(Customer.email, "")).like(pattern)
                | func.lower(func.coalesce(Customer.phone, "")).like(pattern)
            )
        if branch_id is not None:
            base = base.where(Customer.branch_id == branch_id)
        if is_active is not None:
            base = base.where(Customer.is_active.is_(is_active))

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        items = (
            (
                await self._session.execute(
                    base.order_by(Customer.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(items), int(total)

    async def get_by_id(
        self, organization_id: uuid.UUID, customer_id: uuid.UUID
    ) -> Customer | None:
        stmt = select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
            Customer.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def email_exists(
        self,
        organization_id: uuid.UUID,
        email: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(Customer.id).where(
            Customer.organization_id == organization_id,
            Customer.email == email,
            Customer.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(Customer.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def phone_exists(
        self,
        organization_id: uuid.UUID,
        phone: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(Customer.id).where(
            Customer.organization_id == organization_id,
            Customer.phone == phone,
            Customer.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(Customer.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def add(self, customer: Customer) -> Customer:
        self._session.add(customer)
        await self._session.commit()
        await self._session.refresh(customer)
        return customer

    async def save(self, customer: Customer) -> Customer:
        await self._session.commit()
        await self._session.refresh(customer)
        return customer

    async def soft_delete(self, customer: Customer) -> None:
        customer.is_deleted = True
        customer.is_active = False
        await self._session.commit()

    async def stats(
        self, organization_id: uuid.UUID, customer_id: uuid.UUID
    ) -> tuple[int, Decimal]:
        stmt = select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
        ).where(
            Order.organization_id == organization_id,
            Order.customer_id == customer_id,
            Order.status == OrderStatus.PAID,
            Order.is_deleted.is_(False),
        )
        row = (await self._session.execute(stmt)).one()
        return int(row[0]), Decimal(row[1])
