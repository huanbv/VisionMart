"""HTTP router for the AI training module."""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.ai_training.application.service import (
    TrainingError,
    TrainingService,
)
from app.modules.ai_training.schemas.training import (
    TrainingImageList,
    TrainingImageRead,
    TrainingJobCreate,
    TrainingJobList,
    TrainingJobRead,
)
from app.services.ai_engine_client import AIEngineClient
from app.services.object_storage import MinioStorage

router = APIRouter(prefix="/ai/training", tags=["ai-training"])

_TRAINER_ROLES = ("super_admin", "org_admin", "ai_engineer")


def _service(session: AsyncSession) -> TrainingService:
    return TrainingService(session, MinioStorage(), AIEngineClient(timeout=60.0))


async def _attach_preview(
    service: TrainingService, image
) -> TrainingImageRead:
    payload = TrainingImageRead.model_validate(image)
    payload.preview_url = await service.presign(image.storage_key)
    return payload


@router.post(
    "/images",
    response_model=TrainingImageRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_image(
    product_id: uuid.UUID = Form(...),
    image: UploadFile = File(...),
    current: CurrentUser = Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TrainingImageRead:
    content = await image.read()
    service = _service(session)
    try:
        row = await service.upload_image(
            organization_id=current.organization_id,
            product_id=product_id,
            content=content,
            content_type=image.content_type or "application/octet-stream",
        )
    except TrainingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return await _attach_preview(service, row)


@router.get("/images", response_model=TrainingImageList)
async def list_images(
    product_id: uuid.UUID | None = Query(None),
    current: CurrentUser = Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TrainingImageList:
    service = _service(session)
    rows, total = await service.list_images(
        organization_id=current.organization_id, product_id=product_id
    )
    items = [await _attach_preview(service, row) for row in rows]
    return TrainingImageList(items=items, total=total)


@router.get("/images/export")
async def export_training_images(
    product_id: uuid.UUID | None = Query(None),
    current: CurrentUser = Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    service = _service(session)
    try:
        data, filename = await service.export_images_zip(
            organization_id=current.organization_id,
            product_id=product_id,
        )
    except TrainingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_image(
    image_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    service = _service(session)
    try:
        await service.delete_image(
            organization_id=current.organization_id, image_id=image_id
        )
    except TrainingError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/jobs",
    response_model=TrainingJobRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_job(
    body: TrainingJobCreate,
    current: CurrentUser = Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TrainingJobRead:
    service = _service(session)
    try:
        job = await service.create_job(
            organization_id=current.organization_id,
            name=body.name,
            product_ids=body.product_ids,
            branch_id=body.branch_id,
            epochs=body.epochs,
            image_size=body.image_size,
        )
    except TrainingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return TrainingJobRead.model_validate(job)


@router.get("/jobs", response_model=TrainingJobList)
async def list_jobs(
    current: CurrentUser = Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TrainingJobList:
    service = _service(session)
    rows, total = await service.list_jobs(
        organization_id=current.organization_id
    )
    return TrainingJobList(
        items=[TrainingJobRead.model_validate(r) for r in rows], total=total
    )


@router.get("/jobs/{job_id}", response_model=TrainingJobRead)
async def get_job(
    job_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TrainingJobRead:
    service = _service(session)
    try:
        job = await service.get_job(
            organization_id=current.organization_id, job_id=job_id
        )
    except TrainingError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return TrainingJobRead.model_validate(job)


@router.get("/jobs/{job_id}/deploy-check")
async def check_deploy(
    job_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Dry-run the regression gate so the UI can warn *before* deploying.

    Returns the comparison against the currently live weight rather than a
    bare yes/no, so the operator can see how much the metric moved and
    decide whether an override is justified.
    """
    service = _service(session)
    try:
        gate = await service.check_deploy(
            organization_id=current.organization_id, job_id=job_id
        )
    except TrainingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return asdict(gate)


@router.post("/jobs/{job_id}/deploy", response_model=TrainingJobRead)
async def deploy_job(
    job_id: uuid.UUID,
    force: bool = Query(
        False,
        description=(
            "Deploy even if the regression gate blocks it. Use when a metric "
            "trade-off is intentional."
        ),
    ),
    current: CurrentUser = Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TrainingJobRead:
    service = _service(session)
    try:
        job = await service.deploy_job(
            organization_id=current.organization_id, job_id=job_id, force=force
        )
    except TrainingError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return TrainingJobRead.model_validate(job)
