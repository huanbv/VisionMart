"""Async SQLAlchemy engine + session factory with tuned connection pool."""

from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.config.settings import get_settings

_settings = get_settings()

# Kích thước pool tính theo TỔNG số tiến trình, không phải theo một tiến
# trình. Mỗi tiến trình dùng module này (backend, mỗi tiến trình con của
# celery-worker, celery-beat) tạo pool RIÊNG, nên số kết nối thực tế là
# pool_size × số tiến trình. Với cấu hình cũ (10+20=30) và celery mặc định
# spawn một con mỗi CPU, một VPS 4 nhân vượt max_connections=100 của
# Postgres và mọi endpoint đổ lỗi TooManyConnectionsError — đã gặp trên
# production.
#
# 5+10=15 mỗi tiến trình: với ~5 tiến trình là ~75 kết nối, còn dư biên an
# toàn dưới 100. Có thể chỉnh qua biến môi trường khi tải tăng, nhưng phải
# nhân với số tiến trình trước khi nâng.
_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))

engine = create_async_engine(
    _settings.DATABASE_URL,
    echo=False,
    future=True,
    pool_pre_ping=True,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=_POOL_SIZE,
    max_overflow=_MAX_OVERFLOW,
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
