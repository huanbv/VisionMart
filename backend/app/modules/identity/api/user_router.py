"""User management router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.identity.application.password_hasher import PasswordHasher
from app.modules.identity.application.user_management_service import (
    UserManagementService,
)
from app.modules.identity.infrastructure.models import User
from app.modules.identity.infrastructure.repositories import (
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from app.modules.identity.schemas.user import (
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["identity"])


def _service(session: AsyncSession) -> UserManagementService:
    return UserManagementService(
        users=SqlAlchemyUserRepository(session),
        roles=SqlAlchemyRoleRepository(session),
        password_hasher=PasswordHasher(),
    )


def _to_response(user: User, roles: list[str]) -> UserResponse:
    return UserResponse(
        id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=roles,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("", response_model=UserListResponse)
async def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=120),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserListResponse:
    items, total = await _service(session).list(
        current.organization_id, skip=skip, limit=limit, search=search
    )
    return UserListResponse(
        items=[_to_response(u, codes) for u, codes in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    try:
        user, roles = await _service(session).create(
            current.organization_id,
            email=payload.email,
            username=payload.username,
            password=payload.password,
            full_name=payload.full_name,
            is_active=payload.is_active,
            role_codes=payload.role_codes,
        )
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_response(user, roles)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    try:
        user, roles = await _service(session).get(current.organization_id, user_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(user, roles)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    try:
        user, roles = await _service(session).update(
            current.organization_id,
            user_id,
            full_name=payload.full_name,
            is_active=payload.is_active,
            password=payload.password,
            role_codes=payload.role_codes,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_response(user, roles)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def deactivate_user(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if user_id == current.user_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself"
        )
    try:
        await _service(session).deactivate(current.organization_id, user_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
