"""Single source of truth for the detection weight on disk.

``YoloDetector`` (``/detect``, ``/capture``, live overlay) and
``person_tracker`` (the cart pipeline in ``frame.py``) historically read
two different env vars — ``YOLO_MODEL`` vs ``YOLO_MODEL_PATH`` — so a
deployed custom weight could drive one path while the other kept running
stock ``yolov8n``. Both now resolve through ``resolve_detection_weight``.

Precedence:
1. ``YOLO_MODEL_PATH`` from vision runtime config (admin deploy / picker)
2. ``YOLO_MODEL`` env (legacy docker-compose / ``.env``)
3. Stock ``yolov8n.pt`` under ``MODELS_DIR``, then ``/models``

``MODELS_DIR`` defaults to ``/models`` — the volume docker-compose mounts.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("ai-engine.model_path")

DEFAULT_MODELS_DIR = "/models"
STOCK_WEIGHT = "yolov8n.pt"


def models_dir() -> str:
    raw = (os.getenv("MODELS_DIR") or "").strip()
    return raw or DEFAULT_MODELS_DIR


def _configured_weight() -> str:
    """Bare filename or path the operator asked for, before filesystem lookup."""
    try:
        from app.vision.config import get_vision_config

        configured = (get_vision_config().yolo_model_path or "").strip()
    except Exception:  # noqa: BLE001 — config must not take detection down
        logger.exception("could not read YOLO_MODEL_PATH from vision config")
        configured = ""
    if configured:
        return configured
    return (os.getenv("YOLO_MODEL") or "").strip() or STOCK_WEIGHT


def _search_dirs() -> list[str]:
    seen: list[str] = []
    for base in (models_dir(), DEFAULT_MODELS_DIR, "models", "."):
        if base not in seen:
            seen.append(base)
    return seen


def _lookup(name: str) -> str | None:
    if os.path.isabs(name) and os.path.exists(name):
        return name
    if os.path.exists(name):
        return name
    basename = os.path.basename(name)
    for base in _search_dirs():
        for candidate in (
            os.path.join(base, basename),
            os.path.join(base, name) if name != basename else "",
        ):
            if candidate and os.path.exists(candidate):
                return candidate
    return None


def resolve_detection_weight() -> str:
    """Filesystem path (or ultralytics name) both detectors must load."""
    configured = _configured_weight()
    found = _lookup(configured)
    if found:
        return found
    if configured != STOCK_WEIGHT:
        logger.warning(
            "YOLO_MODEL_PATH=%s not found under MODELS_DIR=%s; falling back to %s",
            configured,
            models_dir(),
            STOCK_WEIGHT,
        )
    stock = _lookup(STOCK_WEIGHT)
    return stock or STOCK_WEIGHT


def reload_detection_models() -> None:
    """Drop cached YOLO instances so the next inference reloads the resolved weight."""
    try:
        from app.services.yolo_detector import YoloDetector

        YoloDetector.reset()
    except Exception:  # noqa: BLE001
        logger.exception("could not reset YoloDetector")
    try:
        from app.services.person_tracker import reset_trackers

        reset_trackers()
    except Exception:  # noqa: BLE001
        logger.exception("could not reset person_tracker")
