"""Generic async repository implementing common CRUD operations.

Concrete repositories per bounded context should subclass `BaseRepository` and
set `model = SomeOrmEntity`. Repositories never commit — the service layer /
unit-of-work owns the transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, Sequence, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Minimal generic async repository. Extend per aggregate."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    # ---------- read ----------
    async def get(self, entity_id: UUID, *, include_deleted: bool = False) -> ModelT | None:
        stmt = select(self.model).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        if not include_deleted and hasattr(self.model, "is_deleted"):
            stmt = stmt.where(self.model.is_deleted.is_(False))  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> Sequence[ModelT]:
        stmt = select(self.model).limit(limit).offset(offset)
        if not include_deleted and hasattr(self.model, "is_deleted"):
            stmt = stmt.where(self.model.is_deleted.is_(False))  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def count(self, *, include_deleted: bool = False) -> int:
        stmt = select(func.count()).select_from(self.model)
        if not include_deleted and hasattr(self.model, "is_deleted"):
            stmt = stmt.where(self.model.is_deleted.is_(False))  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    # ---------- write ----------
    async def add(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        """Hard delete. Prefer `soft_delete` for entities that support it."""
        await self._session.delete(entity)
        await self._session.flush()

    async def soft_delete(self, entity: ModelT) -> None:
        if not hasattr(entity, "is_deleted"):
            raise TypeError(f"{type(entity).__name__} does not support soft delete")
        entity.deleted_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        entity.is_deleted = True  # type: ignore[attr-defined]
        await self._session.flush()
