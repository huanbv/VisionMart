"""HTTP router for the active-learning review queue.

Endpoints deliberately expose *approve/reject* rather than any "auto
accept" bulk action: the whole point of the queue is that a human decides,
and an endpoint that skipped that would quietly reintroduce the
train-on-your-own-mistakes failure the queue exists to prevent. Bulk
approval per product is left out for the same reason.
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.ai_training.application.review_service import (
    ReviewError,
    ReviewService,
)
from app.modules.ai_training.schemas.review import (
    ApproveCandidatePayload,
    RejectCandidatePayload,
    ReviewCandidateList,
    ReviewCandidateRead,
    ReviewStats,
)
from app.services.object_storage import MinioStorage

router = APIRouter(prefix="/ai/review", tags=["ai-review"])

_REVIEWER_ROLES = ("super_admin", "org_admin", "ai_engineer")


def _service(session: AsyncSession) -> ReviewService:
    return ReviewService(session, MinioStorage())


def _require_engine_key(
    x_ai_engine_key: str | None = Header(default=None, alias="X-AI-Engine-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Same shared-secret guard the cart-event inbox uses.

    The AI Engine has no user session, so the operator-facing endpoints
    below (Bearer token + roles) are unusable from it — the ingest route
    authenticates with the engine key instead.
    """
    expected = settings.AI_ENGINE_API_KEY
    if not expected or x_ai_engine_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid AI engine key"
        )


async def _attach_preview(
    service: ReviewService, candidate
) -> ReviewCandidateRead:
    payload = ReviewCandidateRead.model_validate(candidate)
    payload.preview_url = await service.presign(candidate.storage_key)
    if getattr(candidate, "crop_key", None):
        payload.crop_preview_url = await service.presign(candidate.crop_key)
    return payload


@router.get("/candidates", response_model=ReviewCandidateList)
async def list_candidates(
    status_filter: str | None = Query("pending", alias="status"),
    source: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewCandidateList:
    service = _service(session)
    try:
        rows, total = await service.list_candidates(
            organization_id=current.organization_id,
            status=status_filter,
            source=source,
            skip=skip,
            limit=limit,
        )
    except ReviewError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    items = [await _attach_preview(service, c) for c in rows]
    return ReviewCandidateList(items=items, total=total)


@router.get("/stats", response_model=ReviewStats)
async def review_stats(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewStats:
    counts = await _service(session).stats(organization_id=current.organization_id)
    return ReviewStats(**counts)


@router.post(
    "/candidates",
    response_model=ReviewCandidateRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(*_REVIEWER_ROLES))],
)
async def create_candidate(
    file: UploadFile = File(...),
    source: str = Form("manual"),
    camera_id: uuid.UUID | None = Form(None),
    predicted_product_id: uuid.UUID | None = Form(None),
    predicted_class: str | None = Form(None),
    confidence: float | None = Form(None),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewCandidateRead:
    """Add a frame to the review queue (operator-flagged, or pushed by a
    detection/checkout hook)."""
    service = _service(session)
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty upload.")
    try:
        candidate = await service.capture(
            organization_id=current.organization_id,
            content=content,
            content_type=file.content_type or "image/jpeg",
            source=source,
            camera_id=camera_id,
            predicted_product_id=predicted_product_id,
            predicted_class=predicted_class,
            confidence=confidence,
        )
    except ReviewError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _attach_preview(service, candidate)


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_require_engine_key)],
)
async def ingest_candidate(
    file: UploadFile = File(...),
    organization_id: uuid.UUID = Form(...),
    source: str = Form("low_confidence"),
    camera_id: uuid.UUID | None = Form(None),
    predicted_class: str | None = Form(None),
    confidence: float | None = Form(None),
    # Crop + bbox: tuy chon de ban engine cu (khong gui) van ingest duoc.
    crop: UploadFile | None = File(None),
    bbox_x1: float | None = Form(None),
    bbox_y1: float | None = Form(None),
    bbox_x2: float | None = Form(None),
    bbox_y2: float | None = Form(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Inbound queue for the AI Engine — frames the detector was unsure about.

    Returns 202 with a small body rather than the full candidate: the
    engine is fire-and-forgetting this from a background task and has no
    use for the payload, so there's no reason to serialise one.

    Failures here must never surface as detection failures, so the engine
    treats any non-2xx as "skip and move on" (see
    ``ai-engine/app/api/frame.py``).
    """
    service = _service(session)
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty upload.")
    crop_content = await crop.read() if crop is not None else None
    bbox = None
    if None not in (bbox_x1, bbox_y1, bbox_x2, bbox_y2):
        bbox = {"x1": bbox_x1, "y1": bbox_y1, "x2": bbox_x2, "y2": bbox_y2}
    try:
        candidate = await service.capture(
            organization_id=organization_id,
            content=content,
            content_type=file.content_type or "image/jpeg",
            source=source,
            camera_id=camera_id,
            predicted_class=predicted_class,
            confidence=confidence,
            crop_content=crop_content,
            bbox=bbox,
        )
    except ReviewError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"id": str(candidate.id), "status": candidate.status}


@router.post(
    "/candidates/{candidate_id}/approve",
    response_model=ReviewCandidateRead,
    dependencies=[Depends(require_roles(*_REVIEWER_ROLES))],
)
async def approve_candidate(
    candidate_id: uuid.UUID,
    payload: ApproveCandidatePayload,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewCandidateRead:
    """Confirm the label — the frame becomes a TrainingImage for the next
    training job."""
    service = _service(session)
    try:
        candidate = await service.approve(
            organization_id=current.organization_id,
            candidate_id=candidate_id,
            confirmed_product_id=payload.confirmed_product_id,
            reviewed_by=current.user_id,
            note=payload.note,
        )
    except ReviewError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _attach_preview(service, candidate)


@router.post(
    "/candidates/{candidate_id}/reject",
    response_model=ReviewCandidateRead,
    dependencies=[Depends(require_roles(*_REVIEWER_ROLES))],
)
async def reject_candidate(
    candidate_id: uuid.UUID,
    payload: RejectCandidatePayload,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewCandidateRead:
    service = _service(session)
    try:
        candidate = await service.reject(
            organization_id=current.organization_id,
            candidate_id=candidate_id,
            reviewed_by=current.user_id,
            note=payload.note,
        )
    except ReviewError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _attach_preview(service, candidate)


@router.post(
    "/discard-non-product",
    dependencies=[Depends(require_roles(*_REVIEWER_ROLES))],
)
async def discard_non_product(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Reject pending furniture / empty-counter captures (not trainable SKUs)."""
    service = _service(session)
    discarded = await service.discard_non_product_pending(
        organization_id=current.organization_id,
        reviewed_by=current.user_id,
    )
    return {"discarded": discarded}
