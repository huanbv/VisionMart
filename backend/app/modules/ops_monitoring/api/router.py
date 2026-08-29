"""Read-only proxy to the standalone `monitoring` service.

Every route here requires `require_roles("super_admin", "org_admin")` —
the same dependency already used for other admin-only endpoints (e.g.
`camera_router.py`) — and issues a single `GET` to the monitoring
service, injecting `settings.MONITORING_API_TOKEN` server-side. The
browser never sees that token; it only ever sends its normal JWT to this
backend, exactly as for every other endpoint in the app.

If the monitoring service is unreachable, these endpoints return a 502
with the underlying reason rather than raising an unhandled error —
monitoring being down must never be confused with an auth failure or a
bug in this proxy.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config.settings import get_settings
from app.dependencies.auth import CurrentUser, require_roles

router = APIRouter(prefix="/ops-monitoring", tags=["ops-monitoring"])

_ADMIN_ROLES = ("super_admin", "org_admin")


async def _forward(path: str, params: dict[str, Any] | None = None) -> dict:
    import httpx

    settings = get_settings()
    url = f"{settings.MONITORING_SERVICE_URL}{path}"
    headers = {"Authorization": f"Bearer {settings.MONITORING_API_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params or {})
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Monitoring service unreachable: {exc}") from exc

    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Monitoring service returned HTTP {resp.status_code}")
    return resp.json()


@router.get("/overview")
async def overview(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/overview")


@router.get("/cameras")
async def cameras(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/cameras")


@router.get("/ai-pipeline")
async def ai_pipeline(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/ai-pipeline")


@router.get("/system")
async def system(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/system")


@router.get("/health-score")
async def health_score(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/health-score")


@router.get("/evaluation")
async def evaluation(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/evaluation")


@router.get("/release-info")
async def release_info(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/release-info")


@router.get("/readiness")
async def readiness(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/readiness")


@router.get("/alerts")
async def alerts_active(current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES))) -> dict:
    return await _forward("/api/alerts")


@router.get("/alerts/history")
async def alerts_history(
    limit: int = Query(100, le=1000),
    current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES)),
) -> dict:
    return await _forward("/api/alerts/history", {"limit": limit})


@router.get("/sessions")
async def sessions(
    since_hours: int = Query(24, le=24 * 30),
    limit: int = Query(200, le=2000),
    current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES)),
) -> dict:
    return await _forward("/api/sessions", {"since_hours": since_hours, "limit": limit})


@router.get("/history/{category}")
async def history(
    category: str,
    since_minutes: int = Query(60, le=60 * 24 * 7),
    current: CurrentUser = Depends(require_roles(*_ADMIN_ROLES)),
) -> dict:
    return await _forward(f"/api/history/{category}", {"since_minutes": since_minutes})
