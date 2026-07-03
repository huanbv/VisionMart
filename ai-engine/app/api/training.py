"""AI Engine training HTTP endpoints."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import require_api_key
from app.services import object_storage as storage
from app.services import trainer

router = APIRouter(prefix="/ai", tags=["ai-training"], dependencies=[Depends(require_api_key)])
logger = logging.getLogger("ai-engine.api.training")


class TrainRequest(BaseModel):
    job_id: str
    organization_id: str
    branch_id: str | None = None
    class_map: dict[str, list[str]] = Field(min_length=1)
    class_to_sku: dict[str, str]
    epochs: int = 30
    image_size: int = 640


class TrainStartResponse(BaseModel):
    job_id: str
    status: str


class TrainStatusResponse(BaseModel):
    job_id: str
    status: str
    metrics: dict[str, Any] | None = None
    weight_key: str | None = None
    error: str | None = None
    progress: str | None = None


class DeployRequest(BaseModel):
    weight_key: str
    organization_id: str
    branch_id: str | None = None


class DeployResponse(BaseModel):
    weight_key: str
    local_path: str


_DEPLOY_LOCK = threading.Lock()


@router.post("/train", response_model=TrainStartResponse)
async def start_training(body: TrainRequest) -> TrainStartResponse:
    if len(body.class_map) < 2:
        raise HTTPException(
            status_code=400, detail="Need at least 2 classes to train"
        )
    state = trainer.start(
        job_id=body.job_id,
        organization_id=body.organization_id,
        branch_id=body.branch_id,
        class_map=body.class_map,
        class_to_sku=body.class_to_sku,
        epochs=body.epochs,
        image_size=body.image_size,
    )
    return TrainStartResponse(job_id=state.job_id, status=state.status)


@router.get("/train/{job_id}", response_model=TrainStatusResponse)
async def training_status(job_id: str) -> TrainStatusResponse:
    state = trainer.get_state(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Job not found")
    snap = state.snapshot()
    return TrainStatusResponse(**snap)


@router.post("/config/model", response_model=DeployResponse)
async def deploy_model(body: DeployRequest) -> DeployResponse:
    """Download a trained weight from MinIO and swap it into the running detector."""
    local_dir = os.getenv("MODELS_DIR", "/app/models")
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, os.path.basename(body.weight_key))
    with _DEPLOY_LOCK:
        try:
            storage.download(body.weight_key, local_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502, detail=f"Weight download failed: {exc}"
            ) from exc

        try:
            from app.services.yolo_detector import YoloDetector

            YoloDetector.reset(local_path)
        except AttributeError:
            YoloDetector._instance = None  # type: ignore[attr-defined]
            os.environ["YOLO_MODEL"] = local_path

        try:
            from app.services.person_tracker import reset_trackers

            reset_trackers()
        except ImportError:
            pass

    return DeployResponse(weight_key=body.weight_key, local_path=local_path)
