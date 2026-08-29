"""Monitoring service FastAPI app.

Every endpoint under `/api/*` is read-only (no `POST`/`PUT`/`DELETE`
anywhere in this router) and requires the monitoring service's own static
bearer token (`MONITORING_API_TOKEN`) -- a credential entirely separate
from the main application's user auth system. In production, the
recommended access path is: frontend -> backend's authenticated
`ops_monitoring` proxy router (reuses the app's existing staff login,
never exposes this token to a browser) -> this service. See
`docs/MONITORING.md` for the full access-control discussion, including
the honest caveat about what this design does and does not protect
against if this service is exposed directly.

`/health` is intentionally unauthenticated (used by Docker's own
healthcheck and by the backend proxy to decide whether monitoring itself
is up) and reveals nothing beyond "the process is alive."
"""

from __future__ import annotations

import hmac
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from monitoring.audit.session_lifecycle import collect_session_lifecycle
from monitoring.collectors.release_info import collect_release_info
from monitoring.config import get_monitoring_config
from monitoring.health_score import compute_health_score
from monitoring.logging_config import configure_logging
from monitoring.scheduler import MonitoringScheduler
from monitoring.storage import db as monitoring_db

cfg = get_monitoring_config()
configure_logging(cfg)
monitoring_db.init_db(cfg.sqlite_path)

app = FastAPI(title="VisionMart Operational Monitoring", version="1.0.0", docs_url="/docs", redoc_url=None)
scheduler = MonitoringScheduler(cfg)

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def _require_token(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token, cfg.api_token):
        raise HTTPException(status_code=403, detail="Invalid token")


@app.on_event("startup")
async def _on_startup() -> None:
    scheduler.start()


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    await scheduler.stop()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "monitoring",
        "last_poll_ts": scheduler.last_poll_ts,
        "last_poll_age_seconds": (time.time() - scheduler.last_poll_ts) if scheduler.last_poll_ts else None,
        "last_error": scheduler.last_error,
    }


@app.get("/api/overview")
async def overview(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    camera = monitoring_db.latest_snapshot(cfg.sqlite_path, "camera") or {}
    pipeline = monitoring_db.latest_snapshot(cfg.sqlite_path, "ai_pipeline") or {}
    system = monitoring_db.latest_snapshot(cfg.sqlite_path, "system") or {}
    service_health = monitoring_db.latest_snapshot(cfg.sqlite_path, "service_health") or {}
    evaluation = monitoring_db.latest_snapshot(cfg.sqlite_path, "evaluation") or {}
    health_score = monitoring_db.latest_snapshot(cfg.sqlite_path, "health_score") or {}
    active_alerts = monitoring_db.active_alerts(cfg.sqlite_path)

    cameras = camera.get("cameras", [])
    camera_summary = {
        "total": len(cameras),
        "online": sum(1 for c in cameras if c.get("is_online_db")),
    }

    return {
        "generated_at": time.time(),
        "poller": {
            "last_poll_ts": scheduler.last_poll_ts,
            "poll_interval_seconds": cfg.poll_interval_seconds,
            "last_error": scheduler.last_error,
        },
        "health_score": health_score,
        "service_health": service_health,
        "camera_summary": camera_summary,
        "ai_pipeline": pipeline,
        "system": system,
        "evaluation": evaluation,
        "active_alert_count": len(active_alerts),
        "active_alerts": active_alerts,
    }


@app.get("/api/health-score")
async def health_score(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    latest = monitoring_db.latest_snapshot(cfg.sqlite_path, "health_score")
    if latest is not None:
        return latest
    # No poll has completed yet -- compute one fresh from whatever partial
    # snapshots exist so far, rather than returning an empty response.
    snapshots = {
        "backend_health": monitoring_db.latest_snapshot(cfg.sqlite_path, "service_health") or {},
        "camera": monitoring_db.latest_snapshot(cfg.sqlite_path, "camera") or {},
        "ai_pipeline": monitoring_db.latest_snapshot(cfg.sqlite_path, "ai_pipeline") or {},
        "system": monitoring_db.latest_snapshot(cfg.sqlite_path, "system") or {},
        "evaluation": monitoring_db.latest_snapshot(cfg.sqlite_path, "evaluation"),
    }
    service_health = snapshots["backend_health"]
    snapshots["backend_health"] = service_health.get("backend") or {"ok": False, "reason": "No poll has completed yet."}
    snapshots["ai_engine_health"] = service_health.get("ai_engine") or {"ok": False, "reason": "No poll has completed yet."}
    return compute_health_score(snapshots, cfg).to_dict()


@app.get("/api/evaluation")
async def evaluation(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    return monitoring_db.latest_snapshot(cfg.sqlite_path, "evaluation") or {"note": "No poll has completed yet."}


@app.get("/api/release-info")
async def release_info(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    system = monitoring_db.latest_snapshot(cfg.sqlite_path, "system") or {}
    postgres_version = (system.get("postgres") or {}).get("version")
    return collect_release_info(cfg.repo_root, postgres_version)


@app.get("/api/readiness")
async def readiness(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    # `visionmart` is a sibling standalone package (see visionmart/__init__.py
    # for why importing it here is safe / not the app-package-collision this
    # project otherwise guards against) copied into this image by
    # monitoring/Dockerfile specifically so this endpoint can reuse its
    # checks rather than re-implementing them -- see Part 5/6 of
    # docs/45_DEPLOYMENT_VALIDATION.md.
    from visionmart.readiness import build_readiness_report

    return await build_readiness_report()


@app.get("/api/cameras")
async def cameras(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    return monitoring_db.latest_snapshot(cfg.sqlite_path, "camera") or {"cameras": [], "note": "No poll has completed yet."}


@app.get("/api/ai-pipeline")
async def ai_pipeline(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    return monitoring_db.latest_snapshot(cfg.sqlite_path, "ai_pipeline") or {"note": "No poll has completed yet."}


@app.get("/api/system")
async def system(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    return monitoring_db.latest_snapshot(cfg.sqlite_path, "system") or {"note": "No poll has completed yet."}


@app.get("/api/alerts")
async def alerts_active(authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    return {"active": monitoring_db.active_alerts(cfg.sqlite_path)}


@app.get("/api/alerts/history")
async def alerts_history(limit: int = Query(100, le=1000), authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    return {"alerts": monitoring_db.recent_alerts(cfg.sqlite_path, limit=limit)}


@app.get("/api/sessions")
async def sessions(
    since_hours: int = Query(24, le=24 * 30),
    limit: int = Query(200, le=2000),
    organization_id: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> dict:
    _require_token(authorization)
    snap = await collect_session_lifecycle(
        cfg.database_url, cfg.sqlite_path, since_hours=since_hours, limit=limit, organization_id=organization_id,
    )
    return snap.to_dict()


@app.get("/api/history/{category}")
async def history(category: str, since_minutes: int = Query(60, le=60 * 24 * 7), authorization: str | None = Header(default=None)) -> dict:
    _require_token(authorization)
    if category not in ("camera", "ai_pipeline", "system", "service_health", "evaluation", "health_score"):
        raise HTTPException(status_code=404, detail="Unknown category")
    since_ts = time.time() - since_minutes * 60
    return {"category": category, "points": monitoring_db.snapshot_history(cfg.sqlite_path, category, since_ts)}


if _STATIC_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=str(_STATIC_DIR), html=True), name="dashboard")
