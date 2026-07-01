"""Celery application instance. Task modules will be auto-discovered later."""

from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

from app.config.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "visionmart",
    broker=_settings.CELERY_BROKER_URL,
    backend=_settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.alerts",
        "app.workers.tasks.rtsp_capture",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=_settings.APP_TIMEZONE,
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "alerts-scan-all": {
            "task": "alerts.scan_all",
            "schedule": schedule(run_every=_settings.ALERT_SCAN_INTERVAL_SECONDS),
        },
        "rtsp-scan-all": {
            "task": "rtsp.scan_all",
            "schedule": schedule(
                run_every=_settings.RTSP_CAPTURE_INTERVAL_SECONDS
            ),
        },
    },
)
