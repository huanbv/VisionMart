"""Public health-check endpoints (unauthenticated)."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.database.session import get_session
from app.schemas.common import HealthStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
async def health() -> HealthStatus:
    """Liveness — process is alive. Must not depend on external systems."""
    return HealthStatus(status="ok", service="backend", version=__version__)


@router.get("/ready", summary="Readiness probe")
async def ready(session: SessionDep) -> JSONResponse:
    """Readiness — process is able to serve traffic (database reachable)."""
    checks: dict[str, str] = {}
    overall = status.HTTP_200_OK

    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness must never raise
        logger.warning("Readiness DB check failed: %s", exc)
        checks["database"] = "unavailable"
        overall = status.HTTP_503_SERVICE_UNAVAILABLE

    body = HealthStatus(
        status="ready" if overall == status.HTTP_200_OK else "degraded",
        service="backend",
        version=__version__,
    ).model_dump()
    body["checks"] = checks
    return JSONResponse(status_code=overall, content=body)
