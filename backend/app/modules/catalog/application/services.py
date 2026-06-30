"""Application services for the Catalog bounded context."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.catalog.infrastructure.models import Category, Product
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyCategoryRepository,
    SqlAlchemyProductRepository,
)


class CategoryService:
    def __init__(self, repository: SqlAlchemyCategoryRepository) -> None:
        self._repo = repository

    async def list(self, organization_id: uuid.UUID) -> list[Category]:
        return await self._repo.list_for_org(organization_id)

    async def get(
        self, organization_id: uuid.UUID, category_id: uuid.UUID
    ) -> Category:
        cat = await self._repo.get_by_id(organization_id, category_id)
        if cat is None:
            raise NotFoundError("Category not found")
        return cat

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        name: str,
        slug: str,
        parent_id: uuid.UUID | None,
        is_active: bool,
    ) -> Category:
        if await self._repo.slug_exists(organization_id, slug):
            raise ConflictError(f"Category slug '{slug}' already exists")
        if parent_id is not None:
            await self.get(organization_id, parent_id)
        cat = Category(
            organization_id=organization_id,
            name=name,
            slug=slug,
            parent_id=parent_id,
            is_active=is_active,
        )
        return await self._repo.add(cat)

    async def update(
        self,
        organization_id: uuid.UUID,
        category_id: uuid.UUID,
        *,
        name: str | None = None,
        slug: str | None = None,
        parent_id: uuid.UUID | None | object = ...,
        is_active: bool | None = None,
    ) -> Category:
        cat = await self.get(organization_id, category_id)
        if slug is not None and slug != cat.slug:
            if await self._repo.slug_exists(
                organization_id, slug, exclude_id=category_id
            ):
                raise ConflictError(f"Category slug '{slug}' already exists")
            cat.slug = slug
        if name is not None:
            cat.name = name
        if parent_id is not ...:
            if parent_id == category_id:
                raise ValidationError("Category cannot be its own parent")
            if parent_id is not None:
                await self.get(organization_id, parent_id)
            cat.parent_id = parent_id  # type: ignore[assignment]
        if is_active is not None:
            cat.is_active = is_active
        return await self._repo.save(cat)

    async def delete(
        self, organization_id: uuid.UUID, category_id: uuid.UUID
    ) -> None:
        cat = await self.get(organization_id, category_id)
        await self._repo.soft_delete(cat)


class ProductService:
    def __init__(
        self,
        *,
        products: SqlAlchemyProductRepository,
        categories: SqlAlchemyCategoryRepository,
    ) -> None:
        self._products = products
        self._categories = categories

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
        category_id: uuid.UUID | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[Product], int]:
        return await self._products.list_for_org(
            organization_id,
            skip=skip,
            limit=limit,
            search=search,
            category_id=category_id,
            is_active=is_active,
        )

    async def get(
        self, organization_id: uuid.UUID, product_id: uuid.UUID
    ) -> Product:
        prod = await self._products.get_by_id(organization_id, product_id)
        if prod is None:
            raise NotFoundError("Product not found")
        return prod

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        sku: str,
        name: str,
        category_id: uuid.UUID | None,
        barcode: str | None,
        description: str | None,
        unit_price: Decimal,
        currency: str,
        attributes: dict | None,
        image_url: str | None,
        is_active: bool,
    ) -> Product:
        if await self._products.sku_exists(organization_id, sku):
            raise ConflictError(f"SKU '{sku}' already exists")
        if category_id is not None:
            if (
                await self._categories.get_by_id(organization_id, category_id)
                is None
            ):
                raise ValidationError("Category not found")
        prod = Product(
            organization_id=organization_id,
            sku=sku,
            name=name,
            category_id=category_id,
            barcode=barcode,
            description=description,
            unit_price=unit_price,
            currency=currency,
            attributes=attributes,
            image_url=image_url,
            is_active=is_active,
        )
        return await self._products.add(prod)

    async def update(
        self,
        organization_id: uuid.UUID,
        product_id: uuid.UUID,
        *,
        sku: str | None = None,
        name: str | None = None,
        category_id: uuid.UUID | None | object = ...,
        barcode: str | None | object = ...,
        description: str | None | object = ...,
        unit_price: Decimal | None = None,
        currency: str | None = None,
        attributes: dict | None | object = ...,
        image_url: str | None | object = ...,
        is_active: bool | None = None,
    ) -> Product:
        prod = await self.get(organization_id, product_id)
        if sku is not None and sku != prod.sku:
            if await self._products.sku_exists(
                organization_id, sku, exclude_id=product_id
            ):
                raise ConflictError(f"SKU '{sku}' already exists")
            prod.sku = sku
        if name is not None:
            prod.name = name
        if category_id is not ...:
            if category_id is not None:
                if (
                    await self._categories.get_by_id(
                        organization_id, category_id  # type: ignore[arg-type]
                    )
                    is None
                ):
                    raise ValidationError("Category not found")
            prod.category_id = category_id  # type: ignore[assignment]
        if barcode is not ...:
            prod.barcode = barcode  # type: ignore[assignment]
        if description is not ...:
            prod.description = description  # type: ignore[assignment]
        if unit_price is not None:
            prod.unit_price = unit_price
        if currency is not None:
            prod.currency = currency
        if attributes is not ...:
            prod.attributes = attributes  # type: ignore[assignment]
        if image_url is not ...:
            prod.image_url = image_url  # type: ignore[assignment]
        if is_active is not None:
            prod.is_active = is_active
        return await self._products.save(prod)

    async def delete(
        self, organization_id: uuid.UUID, product_id: uuid.UUID
    ) -> None:
        prod = await self.get(organization_id, product_id)
        await self._products.soft_delete(prod)
