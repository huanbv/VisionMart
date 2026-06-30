"""Auth router: /auth/login, /auth/refresh, /auth/logout, /auth/me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user
from app.modules.identity.application.auth_service import AuthService
from app.modules.identity.application.jwt_service import JWTService
from app.modules.identity.application.password_hasher import PasswordHasher
from app.modules.identity.infrastructure.repositories import (
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyUserRepository,
)
from app.modules.identity.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_service(
    session: AsyncSession,
    settings: Settings,
) -> AuthService:
    return AuthService(
        settings=settings,
        users=SqlAlchemyUserRepository(session),
        refresh_tokens=SqlAlchemyRefreshTokenRepository(session),
        password_hasher=PasswordHasher(),
        jwt_service=JWTService(settings),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    service = _build_service(session, settings)
    try:
        _, tokens = await service.authenticate(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except UnauthorizedError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.access_token_expires_in,
        refresh_expires_in=tokens.refresh_token_expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    service = _build_service(session, settings)
    try:
        tokens = await service.refresh(
            refresh_token=payload.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    except UnauthorizedError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.access_token_expires_in,
        refresh_expires_in=tokens.refresh_token_expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    service = _build_service(session, settings)
    await service.logout(refresh_token=payload.refresh_token)


@router.get("/me", response_model=CurrentUserResponse)
async def me(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CurrentUserResponse:
    service = _build_service(session, settings)
    try:
        user, roles = await service.get_current_user(current.user_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CurrentUserResponse(
        id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=roles,
        last_login_at=user.last_login_at,
    )
