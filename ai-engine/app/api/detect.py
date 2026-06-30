"""Detection endpoint.

Currently a deterministic stub: returns the image dimensions and a
single placeholder bounding box. Real YOLOv8/ONNX backends will replace
the stub once their weights ship in this image.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("ai-engine.detect")

router = APIRouter(tags=["detection"])


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

    detections = _stub_detections(width, height)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    return {
        "model": model or "stub-v0",
        "image": {
            "width": width,
            "height": height,
            "format": fmt,
            "size_bytes": len(content),
        },
        "detections": detections,
        "elapsed_ms": elapsed_ms,
    }
