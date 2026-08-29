"""FastAPI dependency: extract authenticated user from `Authorization: Bearer ...`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, Header, HTTPException, status

from app.core.exceptions import UnauthorizedError
from app.modules.identity.application.jwt_service import get_jwt_service


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    roles: list[str]


def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = get_jwt_service().verify_access_token(token)
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


def require_roles(*role_codes: str) -> Callable[[CurrentUser], CurrentUser]:
    """Dependency factory: ensure the current user has at least one of given roles."""

    allowed = set(role_codes)

    def _checker(
        current: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not (allowed & set(current.roles)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return current

    return _checker

