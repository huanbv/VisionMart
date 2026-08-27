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


def is_custom_weight_path(path: str | None) -> bool:
    """True when ``path`` is a fine-tuned ``.pt``, not stock COCO ``yolov8n``."""
    if not path:
        return False
    return os.path.basename(path) != STOCK_WEIGHT


def is_custom_detection_weight() -> bool:
    """True when a deployed fine-tuned weight is active (not stock COCO yolov8n)."""
    configured = os.path.basename(_configured_weight())
    resolved = os.path.basename(resolve_detection_weight())
    return configured != STOCK_WEIGHT and resolved != STOCK_WEIGHT


def sanitize_try_weight_key(key: str | None) -> str | None:
    """Allow only MinIO keys written by Train AI / bbox jobs: ``models/<file>.pt``.

    Rejects path traversal and anything that is not a training-job object, so
    a video-analysis request cannot point the detector at an arbitrary file.
    """
    if not key:
        return None
    raw = key.strip()
    if not raw or ".." in raw or "\\" in raw or raw.startswith("/"):
        return None
    if raw.count("/") != 1:
        return None
    prefix, name = raw.split("/", 1)
    if prefix != "models" or not name.endswith(".pt") or not name or name == ".pt":
        return None
    if "/" in name or name.startswith("."):
        return None
    return raw


def ensure_try_weight(weight_key: str) -> str:
    """Local path for a job weight **without** swapping the live detector.

    Reuses a file already under ``MODELS_DIR`` (after deploy) or downloads
    once into ``MODELS_DIR/try/``.
    """
    safe = sanitize_try_weight_key(weight_key)
    if not safe:
        raise ValueError("weight_key must be models/<job>.pt")
    basename = os.path.basename(safe)
    found = _lookup(basename)
    if found:
        return found
    dest_dir = os.path.join(models_dir(), "try")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, basename)
    if os.path.exists(dest):
        return dest
    from app.services import object_storage as storage

    storage.download(safe, dest)
    return dest


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
