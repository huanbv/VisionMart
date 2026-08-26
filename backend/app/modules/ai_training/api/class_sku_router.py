"""Admin endpoints for the detector-class -> SKU mapping and model select.

Proxies the ai-engine so the browser never holds the engine's shared key,
and so role checks live here beside every other admin action. The mapping is
always scoped to the caller's own organization (taken from the auth token,
never from the request body) so one tenant can't edit another's rules.

Reads are open to any authenticated user; writes and model switching change
what every camera feeds the detector, so they need an admin/AI-engineer role
— the same policy as the vision-config screen.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.services.ai_engine_client import AIEngineClient, AIEngineError

router = APIRouter(prefix="/ai", tags=["ai-class-sku"])
logger = logging.getLogger(__name__)

_TUNER_ROLES = ("super_admin", "org_admin", "ai_engineer")


class ClassSkuUpdate(BaseModel):
    """class_name -> SKU. The editor sends the full table each save."""

    mapping: dict[str, str] = Field(default_factory=dict)


@router.get("/class-sku-map")
async def read_class_sku_map(
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await AIEngineClient().get_class_sku_map(str(current.organization_id))
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc


@router.put("/class-sku-map", dependencies=[Depends(require_roles(*_TUNER_ROLES))])
async def update_class_sku_map(
    payload: ClassSkuUpdate,
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        result = await AIEngineClient().update_class_sku_map(
            str(current.organization_id), payload.mapping
        )
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc
    logger.info(
        "class-sku map updated by user=%s org=%s entries=%d",
        current.user_id,
        current.organization_id,
        len(payload.mapping),
    )
    return result


@router.get("/models")
async def list_models(
    current: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return await AIEngineClient().list_models()
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc
