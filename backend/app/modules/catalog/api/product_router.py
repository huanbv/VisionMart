"""Product router: CRUD scoped to the current tenant."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.catalog.application.services import ProductService
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyCategoryRepository,
    SqlAlchemyProductRepository,
)
from app.modules.catalog.schemas.product import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["catalog"])


def _service(session: AsyncSession) -> ProductService:
    return ProductService(
        products=SqlAlchemyProductRepository(session),
        categories=SqlAlchemyCategoryRepository(session),
    )


@router.get("", response_model=ProductListResponse)
async def list_products(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=120),
    category_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProductListResponse:
    items, total = await _service(session).list(
        current.organization_id,
        skip=skip,
        limit=limit,
        search=search,
        category_id=category_id,
        is_active=is_active,
    )
    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    try:
        prod = await _service(session).create(
            current.organization_id,
            sku=payload.sku,
            name=payload.name,
            category_id=payload.category_id,
            barcode=payload.barcode,
            description=payload.description,
            unit_price=payload.unit_price,
            currency=payload.currency,
            attributes=payload.attributes,
            image_url=payload.image_url,
            is_active=payload.is_active,
        )
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProductResponse.model_validate(prod)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    try:
        prod = await _service(session).get(current.organization_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProductResponse.model_validate(prod)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    def _maybe(value, unset: bool):
        if unset:
            return None
        return value if value is not None else ...

    try:
        prod = await _service(session).update(
            current.organization_id,
            product_id,
            sku=payload.sku,
            name=payload.name,
            category_id=_maybe(payload.category_id, payload.category_unset),
            barcode=_maybe(payload.barcode, payload.barcode_unset),
            description=_maybe(payload.description, payload.description_unset),
            unit_price=payload.unit_price,
            currency=payload.currency,
            attributes=_maybe(payload.attributes, payload.attributes_unset),
            image_url=_maybe(payload.image_url, payload.image_url_unset),
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProductResponse.model_validate(prod)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_product(
    product_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await _service(session).delete(current.organization_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
