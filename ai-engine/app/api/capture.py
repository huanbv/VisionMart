"""Capture a single frame from a remote video source and run detection."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import cv2  # type: ignore[import-not-found]
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.metrics import (
    CAPTURE_REQUESTS_TOTAL,
    DETECTED_OBJECTS_TOTAL,
    INFERENCE_LATENCY,
)
from app.security import require_api_key
from app.services.yolo_detector import YoloDetector

logger = logging.getLogger("ai-engine.capture")

router = APIRouter(tags=["capture"], dependencies=[Depends(require_api_key)])


class CaptureRequest(BaseModel):
    stream_url: str = Field(min_length=1, max_length=1024)
    model: str | None = None
    open_timeout_ms: int = Field(default=5000, ge=500, le=30000)


def _grab_frame(url: str, open_timeout_ms: int) -> np.ndarray:
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, open_timeout_ms)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, open_timeout_ms)
    except Exception:  # pragma: no cover — older OpenCV builds
        pass
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open stream: {url}")
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        raise RuntimeError("Failed to read frame from stream")
    return frame


@router.post("/capture")
async def capture(payload: CaptureRequest) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        frame = await asyncio.to_thread(
            _grab_frame, payload.stream_url, payload.open_timeout_ms
        )
    except Exception as exc:  # noqa: BLE001
        CAPTURE_REQUESTS_TOTAL.labels(outcome="error").inc()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    height, width = frame.shape[:2]
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encode frame as JPEG",
        )
    jpeg_bytes = buf.tobytes()

    use_stub = (payload.model or "").lower() == "stub"
    if use_stub:
        detections = [
            {
                "class_name": "person",
                "confidence": 0.0,
                "bbox": {
                    "x1": width // 3,
                    "y1": height // 3,
                    "x2": (width * 2) // 3,
                    "y2": (height * 2) // 3,
                },
                "stub": True,
            }
        ]
        model_name = "stub-v0"
    else:
        try:
            detector = YoloDetector.get()
            detections = await detector.detect(jpeg_bytes)
            model_name = detector.model_name
        except Exception as exc:  # noqa: BLE001
            logger.exception("YOLO inference failed during capture")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"YOLO inference failed: {exc}",
            ) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    INFERENCE_LATENCY.labels(model=model_name, endpoint="capture").observe(
        elapsed_ms / 1000.0
    )
    CAPTURE_REQUESTS_TOTAL.labels(outcome="ok").inc()
    for det in detections:
        cls = str(det.get("class_name") or "unknown")
        DETECTED_OBJECTS_TOTAL.labels(class_name=cls).inc()
    return {
        "model": model_name,
        "image": {
            "width": int(width),
            "height": int(height),
            "format": "JPEG",
            "size_bytes": len(jpeg_bytes),
        },
        "detections": detections,
        "elapsed_ms": elapsed_ms,
        "frame_base64": base64.b64encode(jpeg_bytes).decode("ascii"),
    }
