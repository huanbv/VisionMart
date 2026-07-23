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


# --------------------------------------------------------------- catalog
# The OCR stage needs to turn "AQUAFINA" + 500 ml into a SKU. That needs a
# brand/size catalog, which the class->SKU map above cannot express (it is
# keyed by YOLO class, and every water bottle is class "bottle").
#
# Kept as a second file rather than folded into the first because they have
# different owners and lifecycles: class_to_sku is tuned by whoever trains
# the detector, while the catalog mirrors the shop's product list and is
# regenerated whenever products change.
#
#   {"<organization_id>": [
#       {"sku": "AQUA-500", "brand": "Aquafina", "volume_ml": 500},
#       {"sku": "AQUA-1500", "brand": "Aquafina", "volume_ml": 1500}
#   ]}
_CATALOG_CACHE: dict[str, Any] = {"data": {}, "mtime": 0.0, "path": None}


def _catalog_path() -> str:
    return os.getenv("PRODUCT_CATALOG_PATH", "/app/config/product_catalog.json")


def _load_catalog() -> dict[str, Any]:
    path = _catalog_path()
    if not os.path.isfile(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
        if (
            _CATALOG_CACHE.get("path") == path
            and _CATALOG_CACHE.get("mtime") == mtime
            and _CATALOG_CACHE.get("data")
        ):
            return _CATALOG_CACHE["data"]
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("product catalog is not an object: %s", path)
            return {}
        _CATALOG_CACHE.update({"data": data, "mtime": mtime, "path": path})
        return data
    except Exception:  # noqa: BLE001
        logger.exception("failed to load product catalog: %s", path)
        return {}


def list_known_brands(organization_id: str) -> list[str]:
    """Brands this tenant actually stocks, for OCR brand matching.

    Scoped to the tenant rather than a global list so OCR only tries to
    match names that could really be on the shelf — a shorter, cleaner
    candidate set means fewer false brand matches from noisy text.
    """
    with _LOCK:
        data = _load_catalog()
    items = data.get(str(organization_id)) or data.get("_default") or []
    brands = {
        str(item["brand"]).strip()
        for item in items
        if isinstance(item, dict) and item.get("brand")
    }
    return sorted(brands)


def find_sku_by_brand_volume(
    organization_id: str,
    brand: str | None,
    volume_ml: int | None,
    weight_g: int | None = None,
    *,
    volume_tolerance: float = 0.1,
) -> str | None:
    """Resolve a SKU from what OCR could read off the label.

    Requires a brand: size alone is never enough ("500ml" describes half
    the shelf), so a size-only reading correctly resolves to nothing rather
    than guessing. If the brand is known but the size is not, the answer is
    only returned when that brand has exactly *one* product — otherwise
    there is a real ambiguity and inventing an answer would be worse than
    admitting it.

    The 10% tolerance exists because OCR routinely reads "500ml" as "50Oml"
    or picks up "473ml" from an adjacent unit line; requiring an exact
    match would throw away readings that are plainly close enough.
    """
    if not brand:
        return None
    with _LOCK:
        data = _load_catalog()
    items = data.get(str(organization_id)) or data.get("_default") or []

    brand_key = brand.strip().lower()
    candidates = [
        item for item in items
        if isinstance(item, dict) and str(item.get("brand", "")).strip().lower() == brand_key
    ]
    if not candidates:
        return None
    if volume_ml is None and weight_g is None:
        return str(candidates[0]["sku"]) if len(candidates) == 1 else None

    best: tuple[float, str] | None = None
    for item in candidates:
        for field, target in (("volume_ml", volume_ml), ("weight_g", weight_g)):
            if target is None:
                continue
            value = item.get(field)
            if not value:
                continue
            diff = abs(float(value) - float(target)) / float(target)
            if diff <= volume_tolerance and (best is None or diff < best[0]):
                best = (diff, str(item["sku"]))
    return best[1] if best else None


def get_debug_snapshot() -> dict[str, Any]:
    with _LOCK:
        data = _load()
    return {
        "path": _CACHE.get("path"),
        "mtime": _CACHE.get("mtime"),
        "org_count": len(data),
        "loaded_at": time.time(),
    }
