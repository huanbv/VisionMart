"""Concrete SQLAlchemy repositories for Identity."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.infrastructure.models import (
    RefreshToken,
    Role,
    User,
    UserRole,
)


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id, User.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == email, User.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def update_last_login(self, user_id: uuid.UUID, when: datetime) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(last_login_at=when)
        )
        await self._session.commit()

    async def list_role_codes(self, user_id: uuid.UUID) -> list[str]:
        stmt = (
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.is_deleted.is_(False))
        )
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    # ---- management ----

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        search: str | None = None,
    ) -> tuple[list[User], int]:
        base = select(User).where(
            User.organization_id == organization_id,
            User.is_deleted.is_(False),
        )
        if search:
            pattern = f"%{search.lower()}%"
            base = base.where(
                func.lower(User.email).like(pattern)
                | func.lower(User.username).like(pattern)
                | func.lower(func.coalesce(User.full_name, "")).like(pattern)
            )

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        items = (
            (
                await self._session.execute(
                    base.order_by(User.created_at.desc()).offset(skip).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(items), int(total)

    async def email_exists(
        self,
        organization_id: uuid.UUID,
        email: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(User.id).where(
            User.organization_id == organization_id,
            User.email == email,
            User.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def username_exists(
        self,
        organization_id: uuid.UUID,
        username: str,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        stmt = select(User.id).where(
            User.organization_id == organization_id,
            User.username == username,
            User.is_deleted.is_(False),
        )
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        return (await self._session.execute(stmt)).first() is not None

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def save(self, user: User) -> User:
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def soft_delete(self, user: User) -> None:
        user.is_deleted = True
        user.is_active = False
        await self._session.commit()


class SqlAlchemyRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(self, organization_id: uuid.UUID) -> list[Role]:
        stmt = (
            select(Role)
            .where(
                Role.organization_id == organization_id,
                Role.is_deleted.is_(False),
            )
            .order_by(Role.code.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_codes(
        self, organization_id: uuid.UUID, codes: list[str]
    ) -> list[Role]:
        if not codes:
            return []
        stmt = select(Role).where(
            Role.organization_id == organization_id,
            Role.code.in_(codes),
            Role.is_deleted.is_(False),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def replace_user_roles(
        self, user_id: uuid.UUID, role_ids: list[uuid.UUID]
    ) -> None:
        await self._session.execute(
            delete(UserRole).where(UserRole.user_id == user_id)
        )
        for rid in role_ids:
            self._session.add(UserRole(user_id=user_id, role_id=rid))
        await self._session.commit()


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, token: RefreshToken) -> RefreshToken:
        self._session.add(token)
        await self._session.commit()
        await self._session.refresh(token)
        return token

    async def get_by_id(self, token_id: uuid.UUID) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.id == token_id)
        )
        return result.scalar_one_or_none()

    async def revoke(
        self, token_id: uuid.UUID, *, replaced_by: uuid.UUID | None = None
    ) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.utcnow(), replaced_by=replaced_by)
        )
        await self._session.commit()

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.utcnow())
        )
        await self._session.commit()

