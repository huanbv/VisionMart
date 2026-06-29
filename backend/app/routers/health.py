"""Public health-check endpoints (unauthenticated)."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.schemas.common import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
async def health() -> HealthStatus:
    return HealthStatus(status="ok", service="backend", version=__version__)


@router.get("/ready", response_model=HealthStatus, summary="Readiness probe")
async def ready() -> HealthStatus:
    # Real readiness checks (DB, Redis, MinIO) will be added in later sprints.
    return HealthStatus(status="ready", service="backend", version=__version__)
