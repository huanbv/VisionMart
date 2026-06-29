"""Async SQLAlchemy engine + session factory with tuned connection pool."""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config.settings import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_timeout=30,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an async session and rolls back on error."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
