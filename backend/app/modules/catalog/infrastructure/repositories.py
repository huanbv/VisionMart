"""SQLAlchemy repositories for the Catalog bounded context."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.infrastructure.models import Category, Product


class SqlAlchemyCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(self, organization_id: uuid.UUID) -> list[Category]:
        stmt = (
            select(Category)
            .where(
                Category.organization_id == organization_id,
                Category.is_deleted.is_(False),
            )
            .order_by(Category.name.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_id(
        self, organization_id: uuid.UUID, category_id: uuid.UUID
    ) -> Category | None:
        stmt = select(Category).where(
            Category.id == category_id,
            Category.organization_id == organization_id,
            Category.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def slug_exists(
        self,
        organization_id: uuid.UUID,
        slug: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(Category.id).where(
            Category.organization_id == organization_id,
            Category.slug == slug,
            Category.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(Category.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def add(self, category: Category) -> Category:
        self._session.add(category)
        await self._session.commit()
        await self._session.refresh(category)
        return category

    async def save(self, category: Category) -> Category:
        await self._session.commit()
        await self._session.refresh(category)
        return category

    async def soft_delete(self, category: Category) -> None:
        category.is_deleted = True
        await self._session.commit()


class SqlAlchemyProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        category_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[Product], int]:
        base = select(Product).where(
            Product.organization_id == organization_id,
            Product.is_deleted.is_(False),
        )
        if search:
            pattern = f"%{search.lower()}%"
            base = base.where(
                func.lower(Product.name).like(pattern)
                | func.lower(Product.sku).like(pattern)
                | func.lower(func.coalesce(Product.barcode, "")).like(pattern)
            )
        if category_id is not None:
            base = base.where(Product.category_id == category_id)
        if is_active is not None:
            base = base.where(Product.is_active.is_(is_active))

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        items = (
            (
                await self._session.execute(
                    base.order_by(Product.created_at.desc()).offset(skip).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(items), int(total)

    async def get_by_id(
        self, organization_id: uuid.UUID, product_id: uuid.UUID
    ) -> Product | None:
        stmt = select(Product).where(
            Product.id == product_id,
            Product.organization_id == organization_id,
            Product.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def sku_exists(
        self,
        organization_id: uuid.UUID,
        sku: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(Product.id).where(
            Product.organization_id == organization_id,
            Product.sku == sku,
            Product.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(Product.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def add(self, product: Product) -> Product:
        self._session.add(product)
        await self._session.commit()
        await self._session.refresh(product)
        return product

    async def save(self, product: Product) -> Product:
        await self._session.commit()
        await self._session.refresh(product)
        return product

    async def soft_delete(self, product: Product) -> None:
        product.is_deleted = True
        await self._session.commit()
