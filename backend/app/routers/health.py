"""Public health-check endpoints (unauthenticated)."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import httpx
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from minio import Minio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.schemas.common import HealthStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

READY_CHECK_TIMEOUT_SECONDS = 2.0


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
async def health() -> HealthStatus:
    """Liveness — process is alive. Must not depend on external systems."""
    return HealthStatus(status="ok", service="backend", version=__version__)


async def _check_database(session: AsyncSession) -> str:
    await asyncio.wait_for(
        session.execute(text("SELECT 1")),
        timeout=READY_CHECK_TIMEOUT_SECONDS,
    )
    return "ok"


async def _check_redis(settings: Settings) -> str:
    client = aioredis.from_url(
        settings.REDIS_URL, encoding="utf-8", decode_responses=True
    )
    try:
        await asyncio.wait_for(
            client.ping(), timeout=READY_CHECK_TIMEOUT_SECONDS
        )
    finally:
        await client.aclose()
    return "ok"


async def _check_minio(settings: Settings) -> str:
    def _probe() -> None:
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ROOT_USER,
            secret_key=settings.MINIO_ROOT_PASSWORD,
            secure=settings.MINIO_USE_SSL,
        )
        client.bucket_exists(settings.MINIO_BUCKET)

    await asyncio.wait_for(
        asyncio.to_thread(_probe), timeout=READY_CHECK_TIMEOUT_SECONDS
    )
    return "ok"


async def _check_ai_engine(settings: Settings) -> str:
    async with httpx.AsyncClient(timeout=READY_CHECK_TIMEOUT_SECONDS) as client:
        response = await client.get(
            f"{settings.AI_ENGINE_BASE_URL.rstrip('/')}/health"
        )
        response.raise_for_status()
    return "ok"


async def _run_check(name: str, coro) -> tuple[str, str]:
    try:
        return name, await coro
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        logger.warning("Readiness check %s failed: %s", name, exc)
        return name, "unavailable"


@router.get("/ready", summary="Readiness probe")
async def ready(session: SessionDep, settings: SettingsDep) -> JSONResponse:
    """Readiness — process is able to serve traffic (all dependencies reachable)."""
    results = await asyncio.gather(
        _run_check("database", _check_database(session)),
        _run_check("redis", _check_redis(settings)),
        _run_check("minio", _check_minio(settings)),
        _run_check("ai_engine", _check_ai_engine(settings)),
    )
    checks = dict(results)
    overall = (
        status.HTTP_200_OK
        if all(v == "ok" for v in checks.values())
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    body = HealthStatus(
        status="ready" if overall == status.HTTP_200_OK else "degraded",
        service="backend",
        version=__version__,
    ).model_dump()
    body["checks"] = checks
    return JSONResponse(status_code=overall, content=body)
