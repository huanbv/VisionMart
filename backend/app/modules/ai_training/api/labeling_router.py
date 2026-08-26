"""HTTP router for multi-object bbox labeling."""

from __future__ import annotations

import logging
import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import require_roles
from app.modules.ai_training.application.labeling_service import LabelingService
from app.modules.ai_training.application.service import TrainingError
from app.modules.ai_training.schemas.labeling import (
    BulkUploadResponse,
    CropLabelImageRequest,
    LabelBoxOut,
    LabelImageDetail,
    LabelImageListResponse,
    LabelImageSummary,
    LabelingStatsResponse,
    LabelPoint,
    SaveLabelBoxesRequest,
)
from app.modules.ai_training.schemas.training import LabeledJobCreate, TrainingJobRead
from app.services.ai_engine_client import AIEngineClient
from app.services.object_storage import MinioStorage

router = APIRouter(prefix="/ai/training/labels", tags=["ai-labeling"])

_TRAINER_ROLES = ("super_admin", "org_admin", "ai_engineer")
logger = logging.getLogger(__name__)
_MIGRATION_HINT = (
    "Database chưa migrate — trên VPS chạy: "
    "sudo docker compose exec backend alembic upgrade head"
)


def _raise_db_error(exc: BaseException) -> None:
    raw = str(getattr(exc, "orig", exc))
    logger.exception("labeling database error: %s", raw)
    if "cropped_at" in raw or "polygon" in raw or "does not exist" in raw or "UndefinedColumn" in raw:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_MIGRATION_HINT,
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Lỗi database khi truy vấn ảnh gán nhãn",
    ) from exc


def _service(session: AsyncSession) -> LabelingService:
    return LabelingService(session, MinioStorage(), AIEngineClient(timeout=120.0))


def _summary(row, box_count: int) -> LabelImageSummary:
    return LabelImageSummary(
        id=row.id,
        storage_key=row.storage_key,
        original_filename=row.original_filename,
        image_width=row.image_width,
        image_height=row.image_height,
        box_count=box_count,
        labeled=box_count > 0,
        is_cropped=row.cropped_at is not None,
        created_at=row.created_at,
    )


def _box_out(box, product) -> LabelBoxOut:
    polygon = None
    if box.polygon and len(box.polygon) >= 3:
        polygon = [LabelPoint(x=float(p["x"]), y=float(p["y"])) for p in box.polygon]
    return LabelBoxOut(
        id=box.id,
        product_id=box.product_id,
        product_name=product.name,
        sku=product.sku,
        cx=box.cx,
        cy=box.cy,
        w=box.w,
        h=box.h,
        polygon=polygon,
    )


@router.post("/images", response_model=BulkUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_label_images(
    images: list[UploadFile] = File(...),
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> BulkUploadResponse:
    service = _service(session)
    batch: list[tuple[str, bytes, str]] = []
    for f in images:
        content = await f.read()
        batch.append(
            (
                f.filename or "image.jpg",
                content,
                f.content_type or "application/octet-stream",
            )
        )
    try:
        created, failed = await service.upload_images(
            organization_id=current.organization_id,
            files=batch,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    items = [_summary(row, 0) for row in created]
    return BulkUploadResponse(uploaded=len(created), failed=failed, items=items)


@router.get("/images", response_model=LabelImageListResponse)
async def list_label_images(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    labeled: bool | None = Query(None),
    cropped: bool | None = Query(None),
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> LabelImageListResponse:
    service = _service(session)
    try:
        rows, total, labeled_count, pending_count, pending_crop = await service.list_images(
            organization_id=current.organization_id,
            skip=skip,
            limit=limit,
            labeled=labeled,
            cropped=cropped,
        )
        items = []
        for record in rows:
            try:
                image = record[0]
                box_count = int(record[1] or 0)
                base = _summary(image, box_count)
                preview = await service.presign(image.storage_key)
                payload = base.model_dump()
                payload["preview_url"] = preview or None
                items.append(LabelImageSummary(**payload))
            except Exception:  # noqa: BLE001
                logger.exception(
                    "skip broken label image row id=%s",
                    getattr(record[0], "id", record),
                )
        return LabelImageListResponse(
            items=items,
            total=total,
            labeled_count=labeled_count,
            pending_count=pending_count,
        )
    except HTTPException:
        raise
    except (DBAPIError, SQLAlchemyError) as exc:
        _raise_db_error(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_label_images failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không tải được danh sách ảnh: {exc}",
        ) from exc


@router.get("/images/{image_id}", response_model=LabelImageDetail)
async def get_label_image(
    image_id: uuid.UUID,
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> LabelImageDetail:
    service = _service(session)
    try:
        image, box_rows = await service.get_image(
            organization_id=current.organization_id,
            image_id=image_id,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    preview = await service.presign(image.storage_key)
    boxes = [_box_out(box, product) for box, product in box_rows]
    base = _summary(image, len(boxes))
    payload = base.model_dump()
    payload["preview_url"] = preview or ""
    return LabelImageDetail(**payload, boxes=boxes)


@router.post("/images/{image_id}/crop", response_model=LabelImageDetail)
async def crop_label_image(
    image_id: uuid.UUID,
    body: CropLabelImageRequest,
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> LabelImageDetail:
    service = _service(session)
    try:
        image, box_rows = await service.crop_image(
            organization_id=current.organization_id,
            image_id=image_id,
            x1=body.x1,
            y1=body.y1,
            x2=body.x2,
            y2=body.y2,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    preview = await service.presign(image.storage_key)
    boxes = [_box_out(box, product) for box, product in box_rows]
    base = _summary(image, len(boxes))
    payload = base.model_dump()
    payload["preview_url"] = preview or ""
    return LabelImageDetail(**payload, boxes=boxes)


@router.get("/export")
async def export_label_images(
    mode: str = Query("crops", pattern="^(crops|scenes)$"),
    product_id: uuid.UUID | None = Query(None),
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    service = _service(session)
    try:
        data, filename = await service.export_labels_zip(
            organization_id=current.organization_id,
            mode=mode,
            product_id=product_id,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/images/{image_id}/mark-cropped", response_model=LabelImageSummary)
async def mark_label_image_cropped(
    image_id: uuid.UUID,
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> LabelImageSummary:
    service = _service(session)
    try:
        image = await service.mark_cropped(
            organization_id=current.organization_id,
            image_id=image_id,
        )
        _, box_rows = await service.get_image(
            organization_id=current.organization_id,
            image_id=image_id,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _summary(image, len(box_rows))


@router.put("/images/{image_id}/boxes", response_model=list[LabelBoxOut])
async def save_label_boxes(
    image_id: uuid.UUID,
    body: SaveLabelBoxesRequest,
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> list[LabelBoxOut]:
    service = _service(session)
    try:
        await service.save_boxes(
            organization_id=current.organization_id,
            image_id=image_id,
            boxes=[b.model_dump() for b in body.boxes],
        )
        _, box_rows = await service.get_image(
            organization_id=current.organization_id,
            image_id=image_id,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [_box_out(box, product) for box, product in box_rows]


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_label_image(
    image_id: uuid.UUID,
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> Response:
    service = _service(session)
    try:
        await service.delete_image(
            organization_id=current.organization_id,
            image_id=image_id,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stats", response_model=LabelingStatsResponse)
async def labeling_stats(
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> LabelingStatsResponse:
    service = _service(session)
    try:
        data = await service.stats(organization_id=current.organization_id)
        return LabelingStatsResponse(**data)
    except HTTPException:
        raise
    except (DBAPIError, SQLAlchemyError) as exc:
        _raise_db_error(exc)
    except Exception as exc:  # noqa: BLE001
        logger.exception("labeling_stats failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Không tải thống kê gán nhãn: {exc}",
        ) from exc


@router.post("/jobs", response_model=TrainingJobRead, status_code=status.HTTP_201_CREATED)
async def create_labeled_training_job(
    body: LabeledJobCreate,
    current=Depends(require_roles(*_TRAINER_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TrainingJobRead:
    service = _service(session)
    try:
        job = await service.create_labeled_job(
            organization_id=current.organization_id,
            name=body.name,
            branch_id=body.branch_id,
            epochs=body.epochs,
            image_size=body.image_size,
        )
    except TrainingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return TrainingJobRead.model_validate(job)
