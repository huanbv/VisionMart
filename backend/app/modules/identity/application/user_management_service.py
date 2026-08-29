"""User management application service: list/create/update/deactivate + role assignment."""

from __future__ import annotations

import uuid

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.identity.application.password_hasher import PasswordHasher
from app.modules.identity.infrastructure.models import User
from app.modules.identity.infrastructure.repositories import (
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)


class UserManagementService:
    def __init__(
        self,
        *,
        users: SqlAlchemyUserRepository,
        roles: SqlAlchemyRoleRepository,
        password_hasher: PasswordHasher,
    ) -> None:
        self._users = users
        self._roles = roles
        self._hasher = password_hasher

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
    ) -> tuple[list[tuple[User, list[str]]], int]:
        items, total = await self._users.list_for_org(
            organization_id, skip=skip, limit=limit, search=search
        )
        enriched: list[tuple[User, list[str]]] = []
        for user in items:
            roles = await self._users.list_role_codes(user.id)
            enriched.append((user, roles))
        return enriched, total

    async def get(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[User, list[str]]:
        user = await self._users.get_by_id(user_id)
        if user is None or user.organization_id != organization_id:
            raise NotFoundError("User not found")
        roles = await self._users.list_role_codes(user.id)
        return user, roles

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        email: str,
        username: str,
        password: str,
        full_name: str | None,
        is_active: bool,
        role_codes: list[str],
    ) -> tuple[User, list[str]]:
        normalized_email = email.lower().strip()
        if await self._users.email_exists(organization_id, normalized_email):
            raise ConflictError(f"Email '{email}' already exists")
        if await self._users.username_exists(organization_id, username):
            raise ConflictError(f"Username '{username}' already exists")
        roles = await self._roles.get_by_codes(organization_id, role_codes)
        if len(roles) != len(set(role_codes)):
            raise ValidationError("One or more role codes are invalid")
        user = User(
            organization_id=organization_id,
            email=normalized_email,
            username=username,
            hashed_password=self._hasher.hash(password),
            full_name=full_name,
            is_active=is_active,
            is_superuser=False,
        )
        user = await self._users.add(user)
        if roles:
            await self._roles.replace_user_roles(user.id, [r.id for r in roles])
        codes = await self._users.list_role_codes(user.id)
        return user, codes

    async def update(
        self,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        full_name: str | None = None,
        is_active: bool | None = None,
        password: str | None = None,
        role_codes: list[str] | None = None,
    ) -> tuple[User, list[str]]:
        user, _ = await self.get(organization_id, user_id)
        if full_name is not None:
            user.full_name = full_name
        if is_active is not None:
            user.is_active = is_active
        if password:
            user.hashed_password = self._hasher.hash(password)
        user = await self._users.save(user)
        if role_codes is not None:
            roles = await self._roles.get_by_codes(organization_id, role_codes)
            if len(roles) != len(set(role_codes)):
                raise ValidationError("One or more role codes are invalid")
            await self._roles.replace_user_roles(user.id, [r.id for r in roles])
        codes = await self._users.list_role_codes(user.id)
        return user, codes

    async def deactivate(
        self, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        user, _ = await self.get(organization_id, user_id)
        await self._users.soft_delete(user)
