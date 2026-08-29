"""Runtime editing of the detector class -> SKU mapping, plus the small
lookups the admin "Nhận diện sản phẩm" screen needs to drive it.

Why this exists: with the stock COCO detector, an uploaded product photo is
labelled with a generic COCO class ("bottle", and sometimes nonsense like
"kite"), never a real SKU. The frame pipeline only turns a detection into a
cart line when it can resolve that class to a SKU — via the trained SKU
classifier (Module 9) or, failing that, this class->SKU map. Letting an
operator edit the map from the UI is the fastest path to "upload photo ->
order appears" without training anything.

Endpoints (all under the shared ai-engine API key):
  GET  /ai/class-sku-map?organization_id=  -> current org mapping + options
  PUT  /ai/class-sku-map                    -> replace the org mapping
  GET  /ai/models                           -> weights available to select

The mapping is stored at the org level (see product_mapper.save_class_map),
so it applies to every branch/camera of that tenant.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import require_api_key
from app.services.product_mapper import (
    get_class_map,
    list_coco_classes,
    save_class_map,
)

router = APIRouter(prefix="/ai", tags=["ai-class-sku"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger("ai-engine.api.class_sku")


class ClassSkuUpdate(BaseModel):
    organization_id: str
    # class_name -> SKU. The editor always sends the full table; the server
    # replaces the org bucket wholesale (empty rows are dropped on save).
    mapping: dict[str, str] = Field(default_factory=dict)


def _models_dir() -> str:
    from app.services.model_path import models_dir

    return models_dir()


def _list_weights() -> list[str]:
    """Filenames of the .pt weights sitting in the models volume — the
    dropdown of models an operator can switch the detector to. The pose
    weight is excluded: it is the tracker's own dependency, never a
    detection model to select."""
    out: list[str] = []
    for base in (_models_dir(), "/models", "models"):
        try:
            for name in os.listdir(base):
                if name.endswith(".pt") and "pose" not in name.lower():
                    if name not in out:
                        out.append(name)
        except OSError:
            continue
    return sorted(out)


@router.get("/class-sku-map")
def read_class_sku_map(
    organization_id: str = Query(..., min_length=1),
) -> dict[str, object]:
    return {
        "organization_id": organization_id,
        "mapping": get_class_map(organization_id),
        "coco_classes": list_coco_classes(),
    }


@router.put("/class-sku-map")
def update_class_sku_map(payload: ClassSkuUpdate) -> dict[str, object]:
    if not payload.organization_id.strip():
        raise HTTPException(status_code=400, detail="organization_id is required")
    try:
        saved = save_class_map(payload.organization_id, payload.mapping)
    except OSError as exc:
        logger.exception("Could not persist class-sku map")
        raise HTTPException(
            status_code=500, detail=f"Could not persist mapping: {exc}"
        ) from exc
    logger.info(
        "class-sku map updated org=%s entries=%d",
        payload.organization_id,
        len(saved),
    )
    return {"organization_id": payload.organization_id, "mapping": saved}


@router.get("/models")
def list_models() -> dict[str, object]:
    """Weights available to select, and which one is active right now."""
    from app.services.model_path import resolve_detection_weight
    from app.vision.config import get_vision_config

    return {
        "models": _list_weights(),
        "active": (get_vision_config().yolo_model_path or "").strip(),
        "resolved": resolve_detection_weight(),
        "models_dir": _models_dir(),
    }
