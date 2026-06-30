"""Camera router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.camera.application.services import CameraService
from app.modules.camera.infrastructure.models import Camera
from app.modules.camera.infrastructure.repositories import (
    SqlAlchemyCameraRepository,
)
from app.modules.camera.schemas.camera import (
    CameraCreate,
    CameraHeartbeat,
    CameraListResponse,
    CameraResponse,
    CameraStats,
    CameraUpdate,
)
from app.modules.tenancy.infrastructure.models import Branch
from app.modules.detection.application.detection_service import DetectionService
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)
from app.services.ai_engine_client import AIEngineClient, AIEngineError

router = APIRouter(prefix="/cameras", tags=["camera"])


def _service(session: AsyncSession) -> CameraService:
    return CameraService(SqlAlchemyCameraRepository(session))


def _resolve(value: object, unset: bool) -> object:
    if unset:
        return None
    if value is None:
        from app.modules.camera.application.services import _UNSET

        return _UNSET
    return value


def _to_response(camera: Camera, branch: Branch | None) -> CameraResponse:
    return CameraResponse(
        id=camera.id,
        organization_id=camera.organization_id,
        branch_id=camera.branch_id,
        branch_name=branch.name if branch else None,
        code=camera.code,
        name=camera.name,
        stream_url=camera.stream_url,
        location=camera.location,
        resolution=camera.resolution,
        fps=camera.fps,
        config=camera.config,
        is_online=camera.is_online,
        is_active=camera.is_active,
        last_seen_at=camera.last_seen_at,
        created_at=camera.created_at,
        updated_at=camera.updated_at,
    )


async def _load_response(
    repo: SqlAlchemyCameraRepository,
    service: CameraService,
    organization_id: uuid.UUID,
    camera_id: uuid.UUID,
) -> CameraResponse:
    c = await service.get(organization_id, camera_id)
    branch = await repo.get_branch_in_org(organization_id, c.branch_id)
    return _to_response(c, branch)


@router.get("", response_model=CameraListResponse)
async def list_cameras(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = None,
    branch_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    is_online: bool | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CameraListResponse:
    items, total = await _service(session).list(
        current.organization_id,
        skip=skip,
        limit=limit,
        search=search,
        branch_id=branch_id,
        is_active=is_active,
        is_online=is_online,
    )
    return CameraListResponse(
        items=[_to_response(c, b) for c, b in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/stats", response_model=CameraStats)
async def camera_stats(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CameraStats:
    total, online, active = await _service(session).stats(current.organization_id)
    return CameraStats(total=total, online=online, active=active)


@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(
    payload: CameraCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> CameraResponse:
    repo = SqlAlchemyCameraRepository(session)
    service = CameraService(repo)
    try:
        c = await service.create(
            current.organization_id,
            code=payload.code,
            name=payload.name,
            branch_id=payload.branch_id,
            stream_url=payload.stream_url,
            location=payload.location,
            resolution=payload.resolution,
            fps=payload.fps,
            config=payload.config,
            is_active=payload.is_active,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _load_response(repo, service, current.organization_id, c.id)


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CameraResponse:
    repo = SqlAlchemyCameraRepository(session)
    service = CameraService(repo)
    try:
        return await _load_response(
            repo, service, current.organization_id, camera_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: uuid.UUID,
    payload: CameraUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> CameraResponse:
    repo = SqlAlchemyCameraRepository(session)
    service = CameraService(repo)
    try:
        await service.update(
            current.organization_id,
            camera_id,
            code=payload.code,
            name=payload.name,
            branch_id=payload.branch_id,
            stream_url=payload.stream_url,
            location=_resolve(payload.location, payload.location_unset),
            resolution=_resolve(payload.resolution, payload.resolution_unset),
            fps=_resolve(payload.fps, payload.fps_unset),
            config=_resolve(payload.config, payload.config_unset),
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _load_response(repo, service, current.organization_id, camera_id)


@router.post("/{camera_id}/heartbeat", response_model=CameraResponse)
async def heartbeat_camera(
    camera_id: uuid.UUID,
    payload: CameraHeartbeat,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CameraResponse:
    repo = SqlAlchemyCameraRepository(session)
    service = CameraService(repo)
    try:
        await service.heartbeat(
            current.organization_id, camera_id, online=payload.online
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await _load_response(repo, service, current.organization_id, camera_id)


@router.delete(
    "/{camera_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_camera(
    camera_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await _service(session).delete(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{camera_id}/analyze")
async def analyze_camera_frame(
    camera_id: uuid.UUID,
    image: UploadFile = File(...),
    model: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = _service(session)
    try:
        await service.get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    content = await image.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty image upload")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image exceeds 10 MB",
        )

    client = AIEngineClient()
    try:
        result = await client.detect(
            content=content,
            filename=image.filename or "frame.jpg",
            content_type=image.content_type or "image/jpeg",
            model=model,
        )
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc

    detection_service = DetectionService(SqlAlchemyDetectionRepository(session))
    event = await detection_service.record(
        organization_id=current.organization_id,
        camera_id=camera_id,
        user_id=current.id,
        result=result,
    )

    return {
        "camera_id": str(camera_id),
        "detection_event_id": str(event.id),
        **result,
    }
