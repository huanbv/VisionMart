"""Category router: CRUD scoped to the current tenant."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.catalog.application.services import CategoryService
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyCategoryRepository,
)
from app.modules.catalog.schemas.category import (
    CategoryCreate,
    CategoryResponse,
    CategoryUpdate,
)

router = APIRouter(prefix="/categories", tags=["catalog"])


def _service(session: AsyncSession) -> CategoryService:
    return CategoryService(SqlAlchemyCategoryRepository(session))


@router.get("", response_model=list[CategoryResponse])
async def list_categories(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[CategoryResponse]:
    items = await _service(session).list(current.organization_id)
    return [CategoryResponse.model_validate(c) for c in items]


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> CategoryResponse:
    try:
        cat = await _service(session).create(
            current.organization_id,
            name=payload.name,
            slug=payload.slug,
            parent_id=payload.parent_id,
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CategoryResponse.model_validate(cat)


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CategoryResponse:
    try:
        cat = await _service(session).get(current.organization_id, category_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CategoryResponse.model_validate(cat)


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> CategoryResponse:
    parent_arg: uuid.UUID | None | object = ...
    if payload.parent_unset:
        parent_arg = None
    elif payload.parent_id is not None:
        parent_arg = payload.parent_id
    try:
        cat = await _service(session).update(
            current.organization_id,
            category_id,
            name=payload.name,
            slug=payload.slug,
            parent_id=parent_arg,
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CategoryResponse.model_validate(cat)


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_category(
    category_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await _service(session).delete(current.organization_id, category_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
