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
        "app.workers.tasks.frame_pipeline",
        "app.workers.tasks.detection_cleanup",
        "app.workers.tasks.ai_pipeline_cleanup",
        "app.workers.tasks.cart_sweeper",
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
        "frame-pipeline-scan-all": {
            "task": "frame_pipeline.scan_all",
            "schedule": schedule(
                run_every=_settings.FRAME_PIPELINE_INTERVAL_SECONDS
            ),
        },
        "ai-pipeline-cleanup": {
            "task": "ai_pipeline.cleanup",
            "schedule": schedule(
                run_every=_settings.AI_PIPELINE_CLEANUP_INTERVAL_SECONDS
            ),
        },
        "detection-cleanup": {
            "task": "detection.cleanup",
            "schedule": schedule(
                run_every=_settings.DETECTION_CLEANUP_INTERVAL_SECONDS
            ),
        },
        "cart-sweep-expired": {
            "task": "cart.sweep_expired",
            "schedule": schedule(
                run_every=_settings.CART_SWEEPER_INTERVAL_SECONDS
            ),
        },
    },
)
