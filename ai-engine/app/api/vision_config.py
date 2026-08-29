"""Runtime vision-configuration endpoints.

Lets an operator tune the OpenCV preprocessing chain from the admin UI
instead of editing ``.env`` and restarting the container. Overrides are
persisted to the runtime config file (see ``app/vision/config.py``) and
picked up by the frame pipeline within a second.

The response deliberately reports, per setting, whether the value came
from a runtime override or from the environment — otherwise an operator
cannot tell why a toggle looks "on" when they never set it here.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import require_api_key
from app.vision.config import (
    ENV_TO_FIELD,
    get_runtime_overrides,
    get_vision_config,
    runtime_config_path,
    save_runtime_overrides,
)

router = APIRouter(prefix="/ai/vision-config", tags=["ai-vision-config"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger("ai-engine.api.vision_config")


class VisionConfigUpdate(BaseModel):
    """Partial update. Keys are env-var names (e.g. ``ENABLE_CLAHE``);
    a null value clears that override and reverts to the deployment
    default."""

    settings: dict[str, Any] = Field(default_factory=dict)


def _payload() -> dict[str, Any]:
    cfg = get_vision_config()
    overrides = get_runtime_overrides()
    effective = asdict(cfg)
    return {
        "config_path": runtime_config_path(),
        # Effective values, keyed by env-var name so the UI and the .env
        # file speak the same language.
        "effective": {
            env_name: effective[field_name]
            for env_name, field_name in ENV_TO_FIELD.items()
        },
        "overrides": overrides,
        "overridden_keys": sorted(overrides.keys()),
    }


@router.get("")
def read_vision_config() -> dict[str, Any]:
    return _payload()


@router.put("")
def update_vision_config(payload: VisionConfigUpdate) -> dict[str, Any]:
    try:
        save_runtime_overrides(payload.settings)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc).strip("'")) from exc
    except OSError as exc:
        logger.exception("Could not persist vision config")
        raise HTTPException(
            status_code=500, detail=f"Could not persist config: {exc}"
        ) from exc
    return _payload()


@router.delete("")
def reset_vision_config() -> dict[str, Any]:
    """Clear every runtime override, reverting to the deployment defaults."""
    try:
        save_runtime_overrides({k: None for k in get_runtime_overrides()})
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _payload()
