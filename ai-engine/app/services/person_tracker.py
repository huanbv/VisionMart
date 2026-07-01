"""YOLOv8 + ByteTrack person tracker.

Reuses the shared `YoloDetector` weights but calls `model.track()` with
`persist=True` to maintain stable track ids across successive frames from the
same camera.

Track ids are namespaced by `camera_id` because ultralytics resets state per
model call, so we keep an in-process cache of per-camera detector instances.
"""

from __future__ import annotations

import asyncio
import io
import os
from dataclasses import dataclass
from typing import Any

from PIL import Image

_TRACKERS: dict[str, Any] = {}
_LOCK = asyncio.Lock()


def reset_trackers() -> None:
    """Clear the per-camera tracker cache so YOLO_MODEL changes take effect."""
    _TRACKERS.clear()


@dataclass(frozen=True)
class TrackedObject:
    track_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0


def _get_model(camera_key: str):
    from ultralytics import YOLO

    if camera_key in _TRACKERS:
        return _TRACKERS[camera_key]
    weights = os.getenv("YOLO_MODEL", "yolov8n.pt")
    model = YOLO(weights)
    _TRACKERS[camera_key] = model
    return model


async def track_frame(image_bytes: bytes, camera_key: str) -> list[TrackedObject]:
    async with _LOCK:
        model = _get_model(camera_key)
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Cannot decode image: {exc}") from exc

    loop = asyncio.get_event_loop()

    def _run() -> list[TrackedObject]:
        results = model.track(
            source=img,
            persist=True,
            tracker="bytetrack.yaml",
            verbose=False,
        )
        out: list[TrackedObject] = []
        if not results:
            return out
        first = results[0]
        names = first.names or {}
        if first.boxes is None:
            return out
        for box in first.boxes:
            tid = box.id
            if tid is None:
                continue
            cls_idx = int(box.cls[0]) if box.cls is not None else -1
            class_name = names.get(cls_idx, str(cls_idx))
            conf = float(box.conf[0]) if box.conf is not None else 0.0
            xy = box.xyxy[0].tolist()
            out.append(
                TrackedObject(
                    track_id=int(tid[0]),
                    class_name=str(class_name),
                    confidence=conf,
                    x1=float(xy[0]),
                    y1=float(xy[1]),
                    x2=float(xy[2]),
                    y2=float(xy[3]),
                )
            )
        return out

    return await loop.run_in_executor(None, _run)
