"""SQLAlchemy repositories for the Sales bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.sales.infrastructure.models import (
    Order,
    OrderItem,
    OrderStatus,
    ShoppingCart,
    CartStatus,
)
from app.modules.tenancy.infrastructure.models import Branch


class SqlAlchemyOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        branch_id: uuid.UUID | None = None,
        status: OrderStatus | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> tuple[list[tuple[Order, Branch]], int]:
        base = (
            select(Order, Branch)
            .join(Branch, Branch.id == Order.branch_id)
            .where(
                Order.organization_id == organization_id,
                Order.is_deleted.is_(False),
            )
        )
        if branch_id is not None:
            base = base.where(Order.branch_id == branch_id)
        if status is not None:
            base = base.where(Order.status == status)
        if date_from is not None:
            base = base.where(Order.created_at >= date_from)
        if date_to is not None:
            base = base.where(Order.created_at <= date_to)
        if search:
            base = base.where(func.lower(Order.code).like(f"%{search.lower()}%"))

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(Order.created_at.desc()).offset(skip).limit(limit)
            )
        ).all()
        return [(r[0], r[1]) for r in rows], int(total)

    async def get_by_id(
        self, organization_id: uuid.UUID, order_id: uuid.UUID
    ) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.id == order_id,
                Order.organization_id == organization_id,
                Order.is_deleted.is_(False),
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def next_code(self, organization_id: uuid.UUID) -> str:
        today = datetime.utcnow().strftime("%Y%m%d")
        prefix = f"ORD-{today}-"
        stmt = select(func.count()).where(
            Order.organization_id == organization_id,
            Order.code.like(f"{prefix}%"),
        )
        count = (await self._session.execute(stmt)).scalar_one()
        return f"{prefix}{int(count) + 1:04d}"

    async def add(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.flush()
        return order

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh_with_items(self, order: Order) -> Order:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order.id)
        )
        return (await self._session.execute(stmt)).scalar_one()


class SqlAlchemyOrderItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, item: OrderItem) -> OrderItem:
        self._session.add(item)
        await self._session.flush()
        return item


class SqlAlchemyCartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, cart: ShoppingCart) -> ShoppingCart:
        self._session.add(cart)
        await self._session.flush()
        return cart

    async def get_by_id(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart | None:
        stmt = select(ShoppingCart).where(
            ShoppingCart.id == cart_id,
            ShoppingCart.organization_id == organization_id,
            ShoppingCart.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_open_for_session(
        self,
        organization_id: uuid.UUID,
        branch_id: uuid.UUID,
        session_id: str,
    ) -> ShoppingCart | None:
        stmt = select(ShoppingCart).where(
            ShoppingCart.organization_id == organization_id,
            ShoppingCart.branch_id == branch_id,
            ShoppingCart.session_id == session_id,
            ShoppingCart.status == CartStatus.ACTIVE,
            ShoppingCart.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        branch_id: uuid.UUID | None = None,
        status: CartStatus | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[ShoppingCart], int]:
        base = select(ShoppingCart).where(
            ShoppingCart.organization_id == organization_id,
            ShoppingCart.is_deleted.is_(False),
        )
        if branch_id is not None:
            base = base.where(ShoppingCart.branch_id == branch_id)
        if status is not None:
            base = base.where(ShoppingCart.status == status)
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        rows = (
            (
                await self._session.execute(
                    base.order_by(ShoppingCart.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    async def list_expired(
        self, cutoff: datetime, *, limit: int = 200
    ) -> list[ShoppingCart]:
        stmt = (
            select(ShoppingCart)
            .where(
                ShoppingCart.status == CartStatus.ACTIVE,
                ShoppingCart.expires_at.is_not(None),
                ShoppingCart.expires_at < cutoff,
                ShoppingCart.is_deleted.is_(False),
            )
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh(self, cart: ShoppingCart) -> None:
        await self._session.refresh(cart)
