"""Read-only aggregation queries for the Dashboard bounded context.

This is a reporting/read-model layer. It deliberately reads ORM models from
other bounded contexts to compute cross-cutting KPIs. It never writes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.camera.infrastructure.models import Camera
from app.modules.catalog.infrastructure.models import Product
from app.modules.customer.infrastructure.models import Customer
from app.modules.employee.infrastructure.models import Employee
from app.modules.inventory.infrastructure.models import Inventory
from app.modules.sales.infrastructure.models import Order, OrderItem, OrderStatus
from app.modules.tenancy.infrastructure.models import Branch


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- summary ----

    async def sales_total(
        self,
        organization_id: uuid.UUID,
        *,
        since: datetime | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> tuple[int, Decimal]:
        stmt = select(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_amount), 0),
        ).where(
            Order.organization_id == organization_id,
            Order.status == OrderStatus.PAID,
            Order.is_deleted.is_(False),
        )
        if since is not None:
            stmt = stmt.where(Order.paid_at >= since)
        if branch_id is not None:
            stmt = stmt.where(Order.branch_id == branch_id)
        row = (await self._session.execute(stmt)).one()
        return int(row[0] or 0), Decimal(row[1] or 0)

    async def customers_total(
        self, organization_id: uuid.UUID, *, since: datetime | None = None
    ) -> int:
        stmt = select(func.count(Customer.id)).where(
            Customer.organization_id == organization_id,
            Customer.is_deleted.is_(False),
        )
        if since is not None:
            stmt = stmt.where(Customer.created_at >= since)
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def products_total(self, organization_id: uuid.UUID) -> int:
        stmt = select(func.count(Product.id)).where(
            Product.organization_id == organization_id,
            Product.is_deleted.is_(False),
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def low_stock_count(
        self, organization_id: uuid.UUID, *, branch_id: uuid.UUID | None = None
    ) -> int:
        stmt = (
            select(func.count(Inventory.id))
            .join(Product, Product.id == Inventory.product_id)
            .where(
                Product.organization_id == organization_id,
                Inventory.is_deleted.is_(False),
                Inventory.reorder_level > 0,
                Inventory.quantity <= Inventory.reorder_level,
            )
        )
        if branch_id is not None:
            stmt = stmt.where(Inventory.branch_id == branch_id)
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def cameras_summary(
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

    async def employees_active(self, organization_id: uuid.UUID) -> int:
        stmt = select(func.count(Employee.id)).where(
            Employee.organization_id == organization_id,
            Employee.is_deleted.is_(False),
            Employee.is_active.is_(True),
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    async def branches_count(self, organization_id: uuid.UUID) -> int:
        stmt = select(func.count(Branch.id)).where(
            Branch.organization_id == organization_id,
            Branch.is_deleted.is_(False),
        )
        return int((await self._session.execute(stmt)).scalar_one() or 0)

    # ---- trends ----

    async def sales_trend(
        self,
        organization_id: uuid.UUID,
        *,
        since: datetime,
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
                Order.paid_at >= since,
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

    async def top_products(
        self,
        organization_id: uuid.UUID,
        *,
        since: datetime,
        limit: int,
        branch_id: uuid.UUID | None = None,
    ) -> list[tuple[uuid.UUID, str, str, int, Decimal]]:
        qty = func.coalesce(func.sum(OrderItem.quantity), 0).label("qty")
        revenue = func.coalesce(func.sum(OrderItem.subtotal), 0).label("revenue")
        stmt = (
            select(
                Product.id,
                Product.sku,
                Product.name,
                qty,
                revenue,
            )
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Product.organization_id == organization_id,
                Order.status == OrderStatus.PAID,
                Order.is_deleted.is_(False),
                Order.paid_at >= since,
            )
            .group_by(Product.id, Product.sku, Product.name)
            .order_by(qty.desc())
            .limit(limit)
        )
        if branch_id is not None:
            stmt = stmt.where(Order.branch_id == branch_id)
        rows = (await self._session.execute(stmt)).all()
        return [
            (r[0], r[1], r[2], int(r[3] or 0), Decimal(r[4] or 0)) for r in rows
        ]

    async def low_stock_items(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int,
        branch_id: uuid.UUID | None = None,
    ) -> list[tuple[uuid.UUID, str, str, str, int, int, int]]:
        stmt = (
            select(
                Inventory.id,
                Product.sku,
                Product.name,
                Branch.name,
                Inventory.quantity,
                Inventory.reserved_quantity,
                Inventory.reorder_level,
            )
            .join(Product, Product.id == Inventory.product_id)
            .join(Branch, Branch.id == Inventory.branch_id)
            .where(
                Product.organization_id == organization_id,
                Inventory.is_deleted.is_(False),
                Inventory.reorder_level > 0,
                Inventory.quantity <= Inventory.reorder_level,
            )
            .order_by(
                (Inventory.quantity - Inventory.reorder_level).asc()
            )
            .limit(limit)
        )
        if branch_id is not None:
            stmt = stmt.where(Inventory.branch_id == branch_id)
        rows = (await self._session.execute(stmt)).all()
        return [
            (r[0], r[1], r[2], r[3], int(r[4]), int(r[5]), int(r[6])) for r in rows
        ]

    async def recent_orders(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int,
        branch_id: uuid.UUID | None = None,
    ) -> list[tuple[Order, Branch]]:
        stmt = (
            select(Order, Branch)
            .join(Branch, Branch.id == Order.branch_id)
            .where(
                Order.organization_id == organization_id,
                Order.is_deleted.is_(False),
            )
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        if branch_id is not None:
            stmt = stmt.where(Order.branch_id == branch_id)
        rows = (await self._session.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]


def utc_start_of_day(d: date | None = None) -> datetime:
    target = d or datetime.now(timezone.utc).date()
    return datetime(target.year, target.month, target.day, tzinfo=timezone.utc)


def utc_days_ago(days: int) -> datetime:
    return utc_start_of_day() - timedelta(days=days)
