"""Prometheus metrics for the backend service.

Metric names follow the Prometheus best-practice `_total` suffix for
counters. All metrics live in the default registry so they are picked up
by `generate_latest()`.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

DETECTION_EVENTS_TOTAL = Counter(
    "visionmart_detection_events_total",
    "Number of detection events persisted, labelled by camera.",
    ["camera_id"],
)

DETECTION_OBJECTS_TOTAL = Counter(
    "visionmart_detection_objects_total",
    "Number of detected objects, labelled by class.",
    ["class_name"],
)

ALERTS_SENT_TOTAL = Counter(
    "visionmart_alerts_sent_total",
    "In-app alerts dispatched by DetectionAlertDispatcher.",
    ["camera_id", "class_name"],
)

RTSP_CAPTURES_TOTAL = Counter(
    "visionmart_rtsp_captures_total",
    "RTSP capture attempts by outcome.",
    ["outcome"],
)

AI_ENGINE_CALL_LATENCY = Histogram(
    "visionmart_ai_engine_call_seconds",
    "Latency of calls from backend to ai-engine.",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
