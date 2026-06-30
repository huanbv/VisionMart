"""JWT issuance & verification (RS256)."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jose import JWTError, jwt

from app.config.settings import Settings
from app.core.exceptions import UnauthorizedError


@dataclass(frozen=True)
class AccessTokenClaims:
    sub: str
    organization_id: str
    roles: list[str]
    exp: int
    iat: int
    iss: str
    aud: str
    jti: str


class JWTService:
    """Issues access tokens and verifies them. Refresh tokens are opaque and live in DB."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._private_key = Path(settings.JWT_PRIVATE_KEY_PATH).read_text(encoding="utf-8")
        self._public_key = Path(settings.JWT_PUBLIC_KEY_PATH).read_text(encoding="utf-8")

    def issue_access_token(
        self, *, user_id: uuid.UUID, organization_id: uuid.UUID, roles: list[str]
    ) -> tuple[str, int]:
        now = datetime.now(timezone.utc)
        ttl = self._settings.ACCESS_TOKEN_TTL_SECONDS
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "organization_id": str(organization_id),
            "roles": roles,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
            "iss": self._settings.JWT_ISSUER,
            "aud": self._settings.JWT_AUDIENCE,
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(payload, self._private_key, algorithm=self._settings.JWT_ALGORITHM)
        return token, ttl

    def verify_access_token(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=[self._settings.JWT_ALGORITHM],
                audience=self._settings.JWT_AUDIENCE,
                issuer=self._settings.JWT_ISSUER,
            )
        except JWTError as exc:
            raise UnauthorizedError("Invalid or expired token") from exc
        return AccessTokenClaims(
            sub=payload["sub"],
            organization_id=payload["organization_id"],
            roles=payload.get("roles", []),
            exp=payload["exp"],
            iat=payload["iat"],
            iss=payload["iss"],
            aud=payload["aud"],
            jti=payload["jti"],
        )

    @staticmethod
    def generate_refresh_secret() -> str:
        """URL-safe random secret embedded in the opaque refresh token."""
        return secrets.token_urlsafe(48)
