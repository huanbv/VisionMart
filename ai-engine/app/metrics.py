"""Prometheus metrics for the AI engine."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

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

# ---- vision/ pipeline metrics (Module 5 — OpenCV Integration Sprint) ----
# Only emitted when ENABLE_PERFORMANCE_METRICS=true (see
# app/vision/pipeline.py::record_pipeline_timing); always *declared* here
# so importing app.metrics never depends on that flag's value.
VISION_OPENCV_SECONDS = Histogram(
    "ai_engine_vision_opencv_seconds",
    "Time spent in the OpenCV preprocessing stage (decode + ROI + enhancement + quality) before YOLO.",
    ["camera_key"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

VISION_YOLO_BYTETRACK_SECONDS = Histogram(
    "ai_engine_vision_yolo_bytetrack_seconds",
    "Time spent in the combined YOLO+ByteTrack model.track() call. Not split further — "
    "see app/vision/metrics/timers.py docstring for why.",
    ["camera_key"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

VISION_PIPELINE_TOTAL_SECONDS = Histogram(
    "ai_engine_vision_pipeline_total_seconds",
    "Total per-frame pipeline time: OpenCV stage + YOLO/ByteTrack stage.",
    ["camera_key"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

VISION_CAMERA_FPS = Gauge(
    "ai_engine_vision_camera_fps",
    "Inferred per-camera FPS (1 / inter-frame delta, smoothed) for the /ai/frame pipeline.",
    ["camera_key"],
)

VISION_DROPPED_FRAMES_TOTAL = Counter(
    "ai_engine_vision_dropped_frames_total",
    "Frames that failed to capture or decode, labelled by camera.",
    ["camera_key"],
)
