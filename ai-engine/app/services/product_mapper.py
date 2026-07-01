"""Product recognition mapper.

Reads a JSON file describing which YOLO class names correspond to which
product SKUs, per organization and per branch. Structure:

```
{
  "<organization_id>": {
    "<branch_id>": {
      "bottle": "SKU-COKE-500ML",
      "cup":    "SKU-COFFEE-M"
    }
  }
}
```

Missing keys simply mean "unrecognised" — the recognizer just skips those
detections instead of raising. The file is re-read on demand so operators
can update mappings without restarting the AI Engine.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("ai-engine.recognition")

_CACHE: dict[str, Any] = {"data": {}, "mtime": 0.0, "path": None}
_LOCK = threading.Lock()


def _path() -> str:
    return os.getenv("CLASS_TO_SKU_PATH", "/app/config/class_to_sku.json")


def _load() -> dict[str, Any]:
    path = _path()
    if not os.path.isfile(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
        if (
            _CACHE.get("path") == path
            and _CACHE.get("mtime") == mtime
            and _CACHE.get("data")
        ):
            return _CACHE["data"]
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("class_to_sku file is not an object: %s", path)
            return {}
        _CACHE["data"] = data
        _CACHE["mtime"] = mtime
        _CACHE["path"] = path
        return data
    except Exception:  # noqa: BLE001
        logger.exception("failed to load class_to_sku file: %s", path)
        return {}


def map_class_to_sku(
    organization_id: str, branch_id: str, class_name: str
) -> str | None:
    with _LOCK:
        data = _load()
    if not data:
        return None
    org_map = data.get(str(organization_id)) or {}
    branch_map = org_map.get(str(branch_id)) or {}
    sku = branch_map.get(class_name)
    if sku:
        return str(sku)
    fallback = (data.get("_default") or {}).get(class_name)
    return str(fallback) if fallback else None


def get_debug_snapshot() -> dict[str, Any]:
    with _LOCK:
        data = _load()
    return {
        "path": _CACHE.get("path"),
        "mtime": _CACHE.get("mtime"),
        "org_count": len(data),
        "loaded_at": time.time(),
    }
