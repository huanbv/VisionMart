"""Authentication application service: login, refresh, logout, current-user lookup."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config.settings import Settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.modules.identity.application.jwt_service import JWTService
from app.modules.identity.application.password_hasher import PasswordHasher
from app.modules.identity.application.repositories import (
    RefreshTokenRepository,
    UserRepository,
)
from app.modules.identity.infrastructure.models import RefreshToken, User


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    access_token_expires_in: int
    refresh_token: str
    refresh_token_expires_in: int


class AuthService:
    def __init__(
        self,
        *,
        settings: Settings,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        password_hasher: PasswordHasher,
        jwt_service: JWTService,
    ) -> None:
        self._settings = settings
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._password_hasher = password_hasher
        self._jwt = jwt_service

    # ---- public API ----

    async def authenticate(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, IssuedTokens]:
        user = await self._users.get_by_email(email.lower().strip())
        if user is None or not user.is_active:
            raise UnauthorizedError("Invalid credentials")
        if not self._password_hasher.verify(user.hashed_password, password):
            raise UnauthorizedError("Invalid credentials")

        await self._users.update_last_login(user.id, datetime.now(timezone.utc))
        roles = await self._users.list_role_codes(user.id)
        tokens = await self._issue_token_pair(
            user=user,
            roles=roles,
            family_id=uuid.uuid4(),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return user, tokens

    async def refresh(
        self,
        *,
        refresh_token: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> IssuedTokens:
        token_id, secret = self._parse_refresh_token(refresh_token)
        stored = await self._refresh_tokens.get_by_id(token_id)
        if stored is None:
            raise UnauthorizedError("Unknown refresh token")

        now = datetime.now(timezone.utc)
        if stored.revoked_at is not None:
            # Reuse attempt on a revoked token -> burn the whole family.
            await self._refresh_tokens.revoke_family(stored.family_id)
            raise UnauthorizedError("Refresh token reuse detected")
        if stored.expires_at <= now:
            raise UnauthorizedError("Refresh token expired")
        if not self._verify_secret(secret, stored.secret_hash):
            raise UnauthorizedError("Refresh token mismatch")

        user = await self._users.get_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Account disabled")

        roles = await self._users.list_role_codes(user.id)
        new_tokens = await self._issue_token_pair(
            user=user,
            roles=roles,
            family_id=stored.family_id,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        new_id, _ = self._parse_refresh_token(new_tokens.refresh_token)
        await self._refresh_tokens.revoke(stored.id, replaced_by=new_id)
        return new_tokens

    async def logout(self, *, refresh_token: str) -> None:
        try:
            token_id, _ = self._parse_refresh_token(refresh_token)
        except UnauthorizedError:
            return
        stored = await self._refresh_tokens.get_by_id(token_id)
        if stored is None or stored.revoked_at is not None:
            return
        await self._refresh_tokens.revoke(stored.id)

    async def get_current_user(self, user_id: uuid.UUID) -> tuple[User, list[str]]:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found")
        roles = await self._users.list_role_codes(user.id)
        return user, roles

    # ---- helpers ----

    async def _issue_token_pair(
        self,
        *,
        user: User,
        roles: list[str],
        family_id: uuid.UUID,
        user_agent: str | None,
        ip_address: str | None,
    ) -> IssuedTokens:
        access_token, access_ttl = self._jwt.issue_access_token(
            user_id=user.id, organization_id=user.organization_id, roles=roles
        )
        refresh_secret = JWTService.generate_refresh_secret()
        refresh_ttl = self._settings.REFRESH_TOKEN_TTL_SECONDS
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=refresh_ttl)
        stored = RefreshToken(
            user_id=user.id,
            family_id=family_id,
            secret_hash=self._hash_secret(refresh_secret),
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        stored = await self._refresh_tokens.create(stored)
        token_value = f"{stored.id.hex}.{refresh_secret}"
        return IssuedTokens(
            access_token=access_token,
            access_token_expires_in=access_ttl,
            refresh_token=token_value,
            refresh_token_expires_in=refresh_ttl,
        )

    def _hash_secret(self, secret: str) -> str:
        key = self._settings.BACKEND_SECRET_KEY.encode("utf-8")
        return hmac.new(key, secret.encode("utf-8"), hashlib.sha256).hexdigest()

    def _verify_secret(self, secret: str, expected_hash: str) -> bool:
        return hmac.compare_digest(self._hash_secret(secret), expected_hash)

    @staticmethod
    def _parse_refresh_token(token: str) -> tuple[uuid.UUID, str]:
        if not token or "." not in token:
            raise UnauthorizedError("Malformed refresh token")
        token_id, _, secret = token.partition(".")
        try:
            return uuid.UUID(hex=token_id), secret
        except ValueError as exc:
            raise UnauthorizedError("Malformed refresh token") from exc
