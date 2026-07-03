"""Detection endpoint.

Runs YOLOv8 by default; a deterministic stub is still available via
`?model=stub` for smoke tests and when weights are not yet available.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.metrics import (
    DETECT_REQUESTS_TOTAL,
    DETECTED_OBJECTS_TOTAL,
    INFERENCE_LATENCY,
)
from app.security import require_api_key
from app.services.yolo_detector import YoloDetector

logger = logging.getLogger("ai-engine.detect")

router = APIRouter(tags=["detection"], dependencies=[Depends(require_api_key)])


def _stub_detections(width: int, height: int) -> list[dict[str, Any]]:
    cx, cy = width // 2, height // 2
    half_w, half_h = max(20, width // 6), max(20, height // 6)
    return [
        {
            "class_name": "person",
            "confidence": 0.0,
            "bbox": {
                "x1": max(0, cx - half_w),
                "y1": max(0, cy - half_h),
                "x2": min(width, cx + half_w),
                "y2": min(height, cy + half_h),
            },
            "stub": True,
        }
    ]


@router.post("/detect")
async def detect(
    image: UploadFile = File(...),
    model: str | None = Query(None),
) -> dict[str, Any]:
    content = await image.read()
    if not content:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Empty image upload"
        )

    started = time.perf_counter()
    try:
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            fmt = img.format or "unknown"
    except UnidentifiedImageError as exc:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image format",
        ) from exc

    use_stub = (model or "").lower() == "stub"
    if use_stub:
        detections = _stub_detections(width, height)
        model_name = "stub-v0"
    else:
        try:
            detector = YoloDetector.get()
            detections = await detector.detect(content)
            model_name = detector.model_name
        except Exception as exc:  # noqa: BLE001
            DETECT_REQUESTS_TOTAL.labels(outcome="error").inc()
            logger.exception("YOLO inference failed")
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"YOLO inference failed: {exc}",
            ) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    INFERENCE_LATENCY.labels(model=model_name, endpoint="detect").observe(
        elapsed_ms / 1000.0
    )
    DETECT_REQUESTS_TOTAL.labels(outcome="ok").inc()
    for det in detections:
        cls = str(det.get("class_name") or "unknown")
        DETECTED_OBJECTS_TOTAL.labels(class_name=cls).inc()

    return {
        "model": model_name,
        "image": {
            "width": width,
            "height": height,
            "format": fmt,
            "size_bytes": len(content),
        },
        "detections": detections,
        "elapsed_ms": elapsed_ms,
    }
