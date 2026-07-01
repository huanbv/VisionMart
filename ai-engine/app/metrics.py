"""Prometheus metrics for the AI engine."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

DETECT_REQUESTS_TOTAL = Counter(
    "ai_engine_detect_requests_total",
    "Detection requests, labelled by outcome (ok / error).",
    ["outcome"],
)

CAPTURE_REQUESTS_TOTAL = Counter(
    "ai_engine_capture_requests_total",
    "Capture (RTSP) requests, labelled by outcome.",
    ["outcome"],
)

INFERENCE_LATENCY = Histogram(
    "ai_engine_inference_seconds",
    "End-to-end inference latency including image decode.",
    ["model", "endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

DETECTED_OBJECTS_TOTAL = Counter(
    "ai_engine_detected_objects_total",
    "Detected object count, labelled by class.",
    ["class_name"],
)
