"""Application service for the Detection bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from app.modules.detection.infrastructure.models import DetectionEvent
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)


def archive_product_detections(
    pipeline_detections: object,
    fallback_detections: object,
    sku_names: dict[str, str],
    *,
    image_width: int = 0,
    image_height: int = 0,
    roi_zones: object = None,
) -> list[dict]:
    """JSON stored on DetectionEvent: SKU + catalog name, no person boxes.

    Live / Chụp & Quét / Tải ảnh run the cart pipeline (tiled + class→SKU).
    `/detect` alone often emits one full-image box with no SKU — that is
    what used to show up empty on /detections.
    """
    if isinstance(pipeline_detections, list):
        raw = pipeline_detections
    elif isinstance(fallback_detections, list):
        raw = fallback_detections
    else:
        raw = []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        class_name = str(item.get("class_name") or "")
        if class_name.lower() == "person":
            continue
        sku_raw = item.get("sku")
        sku = str(sku_raw).strip() if sku_raw else None
        if sku == "":
            sku = None
        if class_name.lower() == "region" and not sku:
            continue
        bbox = item.get("bbox")
        if _is_giant_scene_box(bbox, image_width, image_height):
            continue
        if not _bbox_center_in_roi(bbox, image_width, image_height, roi_zones):
            continue
        if float(item.get("confidence") or 0.0) < _ARCHIVE_MIN_CONF:
            continue
        out.append(
            {
                "class_name": class_name,
                "sku": sku,
                "name": sku_names.get(sku) if sku else None,
                "confidence": float(item.get("confidence") or 0.0),
                "bbox": bbox,
            }
        )
    return out


_GIANT_BOX_FRAC = 0.35
_ARCHIVE_MIN_CONF = 0.45


def _is_giant_scene_box(bbox: object, width: int, height: int) -> bool:
    if not isinstance(bbox, dict) or width <= 0 or height <= 0:
        return False
    try:
        x1, y1 = float(bbox["x1"]), float(bbox["y1"])
        x2, y2 = float(bbox["x2"]), float(bbox["y2"])
    except (KeyError, TypeError, ValueError):
        return False
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return area / float(width * height) >= _GIANT_BOX_FRAC


def _point_in_ring(x: float, y: float, points: list) -> bool:
    n = len(points)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        try:
            xi, yi = float(points[i][0]), float(points[i][1])
            xj, yj = float(points[j][0]), float(points[j][1])
        except (IndexError, TypeError, ValueError):
            return False
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _bbox_center_in_roi(
    bbox: object, width: int, height: int, roi_zones: object
) -> bool:
    if not roi_zones:
        return True
    if not isinstance(bbox, dict) or width <= 0 or height <= 0:
        return True
    try:
        x1, y1 = float(bbox["x1"]), float(bbox["y1"])
        x2, y2 = float(bbox["x2"]), float(bbox["y2"])
    except (KeyError, TypeError, ValueError):
        return True
    cx = ((x1 + x2) / 2.0) / float(width)
    cy = ((y1 + y2) / 2.0) / float(height)
    if not isinstance(roi_zones, list):
        return True
    for zone in roi_zones:
        if not isinstance(zone, dict):
            continue
        points = zone.get("points")
        if isinstance(points, list) and _point_in_ring(cx, cy, points):
            return True
    return False


class DetectionService:
    def __init__(self, repo: SqlAlchemyDetectionRepository) -> None:
        self._repo = repo

    async def record(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID,
        user_id: uuid.UUID | None,
        result: dict,
        image_key: str | None = None,
    ) -> DetectionEvent:
        image = result.get("image", {}) or {}
        detections = result.get("detections", []) or []
        confidences = [
            float(d.get("confidence", 0.0) or 0.0)
            for d in detections
            if isinstance(d, dict)
        ]
        event = DetectionEvent(
            organization_id=organization_id,
            camera_id=camera_id,
            user_id=user_id,
            model=str(result.get("model") or "unknown"),
            image_width=int(image.get("width") or 0),
            image_height=int(image.get("height") or 0),
            image_format=image.get("format"),
            image_size_bytes=int(image.get("size_bytes") or 0),
            elapsed_ms=int(result.get("elapsed_ms") or 0),
            detection_count=len(detections),
            max_confidence=max(confidences) if confidences else 0.0,
            image_key=image_key,
            detections=detections,
        )
        return await self._repo.add(event)

    async def get(
        self, organization_id: uuid.UUID, event_id: uuid.UUID
    ) -> DetectionEvent | None:
        return await self._repo.get(organization_id, event_id)

    async def list(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        model: str | None = None,
        min_confidence: float | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[DetectionEvent], int]:
        items = await self._repo.list(
            organization_id=organization_id,
            camera_id=camera_id,
            model=model,
            min_confidence=min_confidence,
            date_from=date_from,
            date_to=date_to,
            skip=skip,
            limit=limit,
        )
        total = await self._repo.count(
            organization_id=organization_id,
            camera_id=camera_id,
            model=model,
            min_confidence=min_confidence,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total
