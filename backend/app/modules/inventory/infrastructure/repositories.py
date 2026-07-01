"""SQLAlchemy repositories for the Inventory bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.infrastructure.models import Product
from app.modules.inventory.infrastructure.models import (
    Inventory,
    StockMovement,
    StockMovementType,
)
from app.modules.tenancy.infrastructure.models import Branch


class SqlAlchemyInventoryRepository:
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
        low_stock: bool = False,
    ) -> tuple[list[tuple[Inventory, Product, Branch]], int]:
        base = (
            select(Inventory, Product, Branch)
            .join(Product, Product.id == Inventory.product_id)
            .join(Branch, Branch.id == Inventory.branch_id)
            .where(
                Product.organization_id == organization_id,
                Branch.organization_id == organization_id,
                Inventory.is_deleted.is_(False),
                Product.is_deleted.is_(False),
                Branch.is_deleted.is_(False),
            )
        )
        if search:
            pattern = f"%{search.lower()}%"
            base = base.where(
                func.lower(Product.name).like(pattern)
                | func.lower(Product.sku).like(pattern)
                | func.lower(func.coalesce(Product.barcode, "")).like(pattern)
            )
        if branch_id is not None:
            base = base.where(Inventory.branch_id == branch_id)
        if low_stock:
            base = base.where(
                Inventory.reorder_level > 0,
                Inventory.quantity <= Inventory.reorder_level,
            )

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(Product.name.asc(), Branch.name.asc())
                .offset(skip)
                .limit(limit)
            )
        ).all()
        return [(r[0], r[1], r[2]) for r in rows], int(total)

    async def get_by_id(
        self, organization_id: uuid.UUID, inventory_id: uuid.UUID
    ) -> tuple[Inventory, Product, Branch] | None:
        stmt = (
            select(Inventory, Product, Branch)
            .join(Product, Product.id == Inventory.product_id)
            .join(Branch, Branch.id == Inventory.branch_id)
            .where(
                Inventory.id == inventory_id,
                Product.organization_id == organization_id,
                Inventory.is_deleted.is_(False),
            )
        )
        row = (await self._session.execute(stmt)).first()
        return (row[0], row[1], row[2]) if row else None

    async def get_by_product_branch(
        self,
        organization_id: uuid.UUID,
        product_id: uuid.UUID,
        branch_id: uuid.UUID,
    ) -> Inventory | None:
        stmt = (
            select(Inventory)
            .join(Product, Product.id == Inventory.product_id)
            .where(
                and_(
                    Inventory.product_id == product_id,
                    Inventory.branch_id == branch_id,
                    Product.organization_id == organization_id,
                    Inventory.is_deleted.is_(False),
                )
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, inventory: Inventory) -> Inventory:
        self._session.add(inventory)
        await self._session.flush()
        return inventory

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh(self, inventory: Inventory) -> None:
        await self._session.refresh(inventory)


class SqlAlchemyStockMovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, movement: StockMovement) -> StockMovement:
        self._session.add(movement)
        await self._session.flush()
        return movement

    async def list_for_inventory(
        self,
        organization_id: uuid.UUID,
        product_id: uuid.UUID,
        branch_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[StockMovement], int]:
        base = select(StockMovement).where(
            StockMovement.organization_id == organization_id,
            StockMovement.product_id == product_id,
            StockMovement.branch_id == branch_id,
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        items = (
            (
                await self._session.execute(
                    base.order_by(StockMovement.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(items), int(total)

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 500,
        branch_id: uuid.UUID | None = None,
        product_id: uuid.UUID | None = None,
        movement_type: StockMovementType | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[tuple[StockMovement, Product, Branch]]:
        stmt = (
            select(StockMovement, Product, Branch)
            .join(Product, Product.id == StockMovement.product_id)
            .join(Branch, Branch.id == StockMovement.branch_id)
            .where(StockMovement.organization_id == organization_id)
        )
        if branch_id is not None:
            stmt = stmt.where(StockMovement.branch_id == branch_id)
        if product_id is not None:
            stmt = stmt.where(StockMovement.product_id == product_id)
        if movement_type is not None:
            stmt = stmt.where(StockMovement.movement_type == movement_type)
        if date_from is not None:
            stmt = stmt.where(StockMovement.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(StockMovement.created_at <= date_to)
        stmt = (
            stmt.order_by(StockMovement.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(r[0], r[1], r[2]) for r in rows]
