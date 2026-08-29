"""Branch router: CRUD scoped to the current tenant."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.tenancy.application.services import BranchService
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)
from app.modules.tenancy.schemas.branch import (
    BranchCreate,
    BranchListResponse,
    BranchResponse,
    BranchUpdate,
)

router = APIRouter(prefix="/branches", tags=["tenancy"])


def _service(session: AsyncSession) -> BranchService:
    return BranchService(SqlAlchemyBranchRepository(session))


@router.get("", response_model=BranchListResponse)
async def list_branches(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=120),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BranchListResponse:
    items, total = await _service(session).list(
        current.organization_id, skip=skip, limit=limit, search=search
    )
    return BranchListResponse(
        items=[BranchResponse.model_validate(b) for b in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(
    payload: BranchCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> BranchResponse:
    try:
        branch = await _service(session).create(
            current.organization_id,
            name=payload.name,
            code=payload.code,
            address=payload.address,
            timezone=payload.timezone,
            is_active=payload.is_active,
        )
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return BranchResponse.model_validate(branch)


@router.get("/{branch_id}", response_model=BranchResponse)
async def get_branch(
    branch_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BranchResponse:
    try:
        branch = await _service(session).get(current.organization_id, branch_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return BranchResponse.model_validate(branch)


@router.patch("/{branch_id}", response_model=BranchResponse)
async def update_branch(
    branch_id: uuid.UUID,
    payload: BranchUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> BranchResponse:
    try:
        branch = await _service(session).update(
            current.organization_id,
            branch_id,
            name=payload.name,
            code=payload.code,
            address=payload.address,
            timezone=payload.timezone,
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return BranchResponse.model_validate(branch)


@router.delete(
    "/{branch_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_branch(
    branch_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await _service(session).delete(current.organization_id, branch_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
