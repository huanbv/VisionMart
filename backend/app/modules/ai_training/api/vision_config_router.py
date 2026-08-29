"""Admin endpoints for tuning the OpenCV preprocessing chain at runtime.

Proxies the ai-engine's ``/ai/vision-config`` so the browser never needs
the engine's shared secret, and so role checks happen here alongside every
other admin action.

Changing these settings changes what every camera feeds the detector, so
writes are restricted to admin/AI-engineer roles while reads are open to
any authenticated user (the pipeline-trace screen shows them for context).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.services.ai_engine_client import AIEngineClient, AIEngineError

router = APIRouter(prefix="/ai/vision-config", tags=["ai-vision-config"])
logger = logging.getLogger(__name__)

_TUNER_ROLES = ("super_admin", "org_admin", "ai_engineer")


class VisionConfigUpdate(BaseModel):
    """Keys are env-var names (``ENABLE_CLAHE``, ``GAMMA_VALUE``, …).
    A null value clears that override."""

    settings: dict[str, Any] = Field(default_factory=dict)


@router.get("")
async def read_vision_config(
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await AIEngineClient().get_vision_config()
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc


@router.put("", dependencies=[Depends(require_roles(*_TUNER_ROLES))])
async def update_vision_config(
    payload: VisionConfigUpdate,
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if not payload.settings:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="No settings supplied."
        )
    try:
        result = await AIEngineClient().update_vision_config(payload.settings)
    except AIEngineError as exc:
        # Unknown-key errors from the engine are the operator's mistake,
        # not an outage — report them as 400 rather than 502.
        text = str(exc)
        if "Unknown vision setting" in text:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=text) from exc
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc
    logger.info(
        "vision config updated by user=%s keys=%s",
        current.user_id,
        sorted(payload.settings),
    )
    return result


@router.delete("", dependencies=[Depends(require_roles(*_TUNER_ROLES))])
async def reset_vision_config(
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Clear all runtime overrides, reverting to the deployment defaults."""
    try:
        result = await AIEngineClient().reset_vision_config()
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc
    logger.info("vision config reset by user=%s", current.user_id)
    return result
