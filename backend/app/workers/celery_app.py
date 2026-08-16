"""Celery application instance. Task modules will be auto-discovered later."""

from __future__ import annotations

from celery import Celery
from celery.schedules import schedule

import app.models  # noqa: F401 — nạp TOÀN BỘ model registry trước khi bất kỳ
# task nào chạy. SQLAlchemy chỉ resolve khoá ngoại lúc mapper thực sự được
# dùng (query/flush đầu tiên), không phải lúc class được import — nên một
# task module chỉ import đúng model nó cần (vd ShoppingCart) vẫn có thể vỡ
# ngay khi flush, nếu model liên quan qua FK (vd Customer) chưa từng được
# import ở đâu trong tiến trình. Đây chính là nguyên nhân cart_sweeper task
# lỗi PendingRollbackError/NoReferencedTableError('customers') ở MỌI lần
# chạy trong 3 tuần liền — 9000+ giỏ AI hết hạn không bao giờ được dọn vì
# task luôn crash trước khi kịp abandon() cart nào. Import ở đây (module mà
# mọi task file đều `from app.workers.celery_app import celery_app`) đảm
# bảo registry đầy đủ ngay từ lúc worker khởi động, không phụ thuộc thứ tự
# import riêng của từng task.
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
