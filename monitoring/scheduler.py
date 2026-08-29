"""Background polling loop.

Ties every collector + the Alert Engine + the retention sweep together on
one asyncio loop, started once from `monitoring/server.py`'s FastAPI
startup event. This is the only place in the package that runs
periodically and with side effects — and the only side effects are writes
to monitoring's own SQLite file and (optionally) a webhook POST; nothing
here ever writes to production Postgres, Redis, or the Docker engine.
"""

from __future__ import annotations

import asyncio
import logging
import time

from monitoring.alerts.engine import AlertEngine
from monitoring.alerts.rules import build_default_rules
from monitoring.collectors import ai_pipeline_health, camera_health, evaluation_health, system_resources
from monitoring.collectors.http_metrics import check_health
from monitoring.config import MonitoringConfig
from monitoring.storage import db as monitoring_db
from monitoring.storage.retention import run_retention_sweep

logger = logging.getLogger("monitoring.scheduler")

RETENTION_SWEEP_EVERY_N_POLLS = 120  # e.g. every ~1h at a 30s poll interval


class MonitoringScheduler:
    def __init__(self, cfg: MonitoringConfig) -> None:
        self.cfg = cfg
        self.alert_engine = AlertEngine(build_default_rules(cfg), cfg.sqlite_path, cfg.webhook_url)
        self._task: asyncio.Task | None = None
        self._poll_count = 0
        self.last_error: str | None = None
        self.last_poll_ts: float | None = None

    async def _poll_once(self) -> dict:
        cfg = self.cfg

        backend_ok, backend_reason, backend_latency = await check_health(f"{cfg.backend_url}/health")
        ai_engine_ok, ai_engine_reason, ai_engine_latency = await check_health(f"{cfg.ai_engine_url}/health")

        camera_snap = await camera_health.collect_camera_health(cfg.database_url, cfg.ai_engine_url, cfg.sqlite_path)
        pipeline_snap = await ai_pipeline_health.collect_ai_pipeline_health(cfg.ai_engine_url, cfg.redis_url)
        system_snap = await system_resources.collect_system_resources(
            cfg.database_url, cfg.redis_url, cfg.celery_broker, cfg.docker_socket, cfg.docker_container_prefix,
        )
        evaluation_snap = evaluation_health.check_evaluation_reports(cfg.evaluation_reports_dir)

        snapshots = {
            "backend_health": {"ok": backend_ok, "reason": backend_reason, "latency_ms": backend_latency},
            "ai_engine_health": {"ok": ai_engine_ok, "reason": ai_engine_reason, "latency_ms": ai_engine_latency},
            "camera": camera_snap.to_dict(),
            "ai_pipeline": pipeline_snap.to_dict(),
            "system": system_snap.to_dict(),
            "evaluation": evaluation_snap.to_dict(),
        }

        monitoring_db.insert_snapshot(cfg.sqlite_path, "camera", snapshots["camera"])
        monitoring_db.insert_snapshot(cfg.sqlite_path, "ai_pipeline", snapshots["ai_pipeline"])
        monitoring_db.insert_snapshot(cfg.sqlite_path, "system", snapshots["system"])
        monitoring_db.insert_snapshot(cfg.sqlite_path, "evaluation", snapshots["evaluation"])
        monitoring_db.insert_snapshot(cfg.sqlite_path, "service_health", {
            "backend": snapshots["backend_health"], "ai_engine": snapshots["ai_engine_health"],
        })

        alert_summary = await self.alert_engine.evaluate(snapshots)
        snapshots["alerts"] = alert_summary

        from monitoring.health_score import compute_health_score

        snapshots["health_score"] = compute_health_score(snapshots, cfg).to_dict()
        monitoring_db.insert_snapshot(cfg.sqlite_path, "health_score", snapshots["health_score"])
        return snapshots

    async def _loop(self) -> None:
        logger.info("Monitoring scheduler starting, poll interval=%ss", self.cfg.poll_interval_seconds)
        while True:
            try:
                await self._poll_once()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 — one bad poll must not kill the loop
                logger.exception("Monitoring poll failed")
                self.last_error = str(exc)
            self.last_poll_ts = time.time()
            self._poll_count += 1

            if self._poll_count % RETENTION_SWEEP_EVERY_N_POLLS == 0:
                try:
                    run_retention_sweep(self.cfg.sqlite_path, self.cfg.retention_days)
                except Exception:  # noqa: BLE001
                    logger.exception("Retention sweep failed")

            await asyncio.sleep(self.cfg.poll_interval_seconds)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
