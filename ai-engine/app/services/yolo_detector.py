"""YOLOv8 detector wrapping the ultralytics package.

Lazy-initialised singleton so the model weights (auto-downloaded on first
use by ultralytics) are loaded exactly once per process.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
from typing import Any

from PIL import Image

from app.services.model_path import resolve_detection_weight

logger = logging.getLogger("ai-engine.yolo")


class YoloDetector:
    _instance: "YoloDetector | None" = None
    _lock = threading.Lock()

    def __init__(self, model_name: str, conf_threshold: float, device: str) -> None:
        from ultralytics import YOLO  # local import: heavy dependency

        logger.info(
            "loading YOLO model=%s device=%s conf=%.2f",
            model_name,
            device,
            conf_threshold,
        )
        self._model = YOLO(model_name)
        self._model_name = model_name
        self._conf = conf_threshold
        self._device = device

    @classmethod
    def get(cls) -> "YoloDetector":
        # Same resolver as person_tracker: YOLO_MODEL_PATH (runtime) wins,
        # then YOLO_MODEL, then stock yolov8n. If the admin deployed a
        # different weight under us, drop the stale singleton.
        want = resolve_detection_weight()
        if cls._instance is not None and cls._instance._model_name != want:
            logger.info(
                "YOLO detection weight changed: %s -> %s",
                cls._instance._model_name,
                want,
            )
            cls.reset()
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(
                        model_name=want,
                        conf_threshold=float(
                            os.getenv("YOLO_CONF_THRESHOLD", "0.25")
                        ),
                        device=os.getenv("YOLO_DEVICE", "cpu"),
                    )
        return cls._instance

    @classmethod
    def reset(cls, new_model_path: str | None = None) -> None:
        """Drop the cached detector so the next call reloads (optionally new weight)."""
        with cls._lock:
            if new_model_path:
                # Keep both names in sync so anything still reading the
                # legacy YOLO_MODEL env sees the same file as YOLO_MODEL_PATH.
                os.environ["YOLO_MODEL"] = new_model_path
                os.environ["YOLO_MODEL_PATH"] = new_model_path
            cls._instance = None

    @property
    def model_name(self) -> str:
        return self._model_name

    def _detect_sync(self, content: bytes) -> list[dict[str, Any]]:
        with Image.open(io.BytesIO(content)) as img:
            rgb = img.convert("RGB")
            results = self._model.predict(
                source=rgb,
                conf=self._conf,
                device=self._device,
                verbose=False,
            )
        detections: list[dict[str, Any]] = []
        for result in results:
            names = result.names
            boxes = result.boxes
            if boxes is None:
                continue
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            classes = boxes.cls.cpu().numpy().astype(int)
            for (x1, y1, x2, y2), conf, cls_id in zip(xyxy, confs, classes):
                detections.append(
                    {
                        "class_name": str(names.get(int(cls_id), str(cls_id))),
                        "confidence": float(conf),
                        "bbox": {
                            "x1": int(x1),
                            "y1": int(y1),
                            "x2": int(x2),
                            "y2": int(y2),
                        },
                    }
                )
        return detections

    async def detect(self, content: bytes) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._detect_sync, content)
