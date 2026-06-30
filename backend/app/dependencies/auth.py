"""FastAPI dependency: extract authenticated user from `Authorization: Bearer ...`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app.config.settings import Settings, get_settings
from app.core.exceptions import UnauthorizedError
from app.modules.identity.application.jwt_service import JWTService


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    roles: list[str]


def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = JWTService(settings).verify_access_token(token)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return CurrentUser(
        user_id=uuid.UUID(claims.sub),
        organization_id=uuid.UUID(claims.organization_id),
        roles=claims.roles,
    )
