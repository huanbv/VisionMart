"""Read-only reporting service for sales / inventory / customer aggregations."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.infrastructure.models import Product
from app.modules.customer.infrastructure.models import Customer
from app.modules.inventory.infrastructure.models import Inventory
from app.modules.sales.infrastructure.models import Order, OrderItem, OrderStatus
from app.modules.tenancy.infrastructure.models import Branch


class ReportsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sales_by_day(
        self,
        organization_id: uuid.UUID,
        *,
        date_from: datetime,
        date_to: datetime,
        branch_id: uuid.UUID | None = None,
    ) -> list[tuple[date, int, Decimal]]:
        day = func.date_trunc("day", Order.paid_at).label("day")
        stmt = (
            select(
                day,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
            )
            .where(
                Order.organization_id == organization_id,
                Order.status == OrderStatus.PAID,
                Order.is_deleted.is_(False),
                Order.paid_at >= date_from,
                Order.paid_at <= date_to,
            )
            .group_by(day)
            .order_by(day)
        )
        if branch_id is not None:
            stmt = stmt.where(Order.branch_id == branch_id)
        rows = (await self._session.execute(stmt)).all()
        result: list[tuple[date, int, Decimal]] = []
        for r in rows:
            ts = r[0]
            d = ts.date() if isinstance(ts, datetime) else ts
            result.append((d, int(r[1] or 0), Decimal(r[2] or 0)))
        return result

    async def sales_by_branch(
        self,
        organization_id: uuid.UUID,
        *,
        date_from: datetime,
        date_to: datetime,
    ) -> list[tuple[uuid.UUID, str, int, Decimal]]:
        stmt = (
            select(
                Branch.id,
                Branch.name,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0),
            )
            .join(Order, Order.branch_id == Branch.id)
            .where(
                Branch.organization_id == organization_id,
                Order.status == OrderStatus.PAID,
                Order.is_deleted.is_(False),
                Order.paid_at >= date_from,
                Order.paid_at <= date_to,
            )
            .group_by(Branch.id, Branch.name)
            .order_by(func.coalesce(func.sum(Order.total_amount), 0).desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            (r[0], r[1], int(r[2] or 0), Decimal(r[3] or 0)) for r in rows
        ]

    async def top_products(
        self,
        organization_id: uuid.UUID,
        *,
        date_from: datetime,
        date_to: datetime,
        limit: int,
        branch_id: uuid.UUID | None = None,
    ) -> list[tuple[uuid.UUID, str, str, int, Decimal]]:
        qty = func.coalesce(func.sum(OrderItem.quantity), 0).label("qty")
        revenue = func.coalesce(func.sum(OrderItem.subtotal), 0).label("revenue")
        stmt = (
            select(Product.id, Product.sku, Product.name, qty, revenue)
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Product.organization_id == organization_id,
                Order.status == OrderStatus.PAID,
                Order.is_deleted.is_(False),
                Order.paid_at >= date_from,
                Order.paid_at <= date_to,
            )
            .group_by(Product.id, Product.sku, Product.name)
            .order_by(revenue.desc())
            .limit(limit)
        )
        if branch_id is not None:
            stmt = stmt.where(Order.branch_id == branch_id)
        rows = (await self._session.execute(stmt)).all()
        return [
            (r[0], r[1], r[2], int(r[3] or 0), Decimal(r[4] or 0)) for r in rows
        ]

    async def inventory_valuation(
        self,
        organization_id: uuid.UUID,
        *,
        branch_id: uuid.UUID | None = None,
    ) -> list[tuple[str, str, str, int, Decimal, Decimal]]:
        value = (Inventory.quantity * Product.unit_price).label("value")
        stmt = (
            select(
                Product.sku,
                Product.name,
                Branch.name,
                Inventory.quantity,
                Product.unit_price,
                value,
            )
            .join(Product, Product.id == Inventory.product_id)
            .join(Branch, Branch.id == Inventory.branch_id)
            .where(
                Product.organization_id == organization_id,
                Inventory.is_deleted.is_(False),
                Product.is_deleted.is_(False),
                Inventory.quantity > 0,
            )
            .order_by(value.desc())
        )
        if branch_id is not None:
            stmt = stmt.where(Inventory.branch_id == branch_id)
        rows = (await self._session.execute(stmt)).all()
        return [
            (
                r[0],
                r[1],
                r[2],
                int(r[3] or 0),
                Decimal(r[4] or 0),
                Decimal(r[5] or 0),
            )
            for r in rows
        ]

    async def top_customers(
        self,
        organization_id: uuid.UUID,
        *,
        date_from: datetime,
        date_to: datetime,
        limit: int,
    ) -> list[tuple[uuid.UUID, str | None, str | None, int, Decimal]]:
        revenue = func.coalesce(func.sum(Order.total_amount), 0).label("revenue")
        stmt = (
            select(
                Customer.id,
                Customer.full_name,
                Customer.phone,
                func.count(Order.id),
                revenue,
            )
            .join(Order, Order.customer_id == Customer.id)
            .where(
                Customer.organization_id == organization_id,
                Order.status == OrderStatus.PAID,
                Order.is_deleted.is_(False),
                Order.paid_at >= date_from,
                Order.paid_at <= date_to,
            )
            .group_by(Customer.id, Customer.full_name, Customer.phone)
            .order_by(revenue.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            (r[0], r[1], r[2], int(r[3] or 0), Decimal(r[4] or 0)) for r in rows
        ]
