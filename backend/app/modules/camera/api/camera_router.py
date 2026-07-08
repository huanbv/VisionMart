"""Camera router."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.camera.application.camera_sim import CameraSimError, CameraSimStorage
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
from app.modules.detection.application.alert_dispatcher import (
    DetectionAlertDispatcher,
)
from app.modules.detection.application.detection_service import DetectionService
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)
from app.modules.notification.application.services import NotificationService
from app.modules.notification.infrastructure.repositories import (
    SqlAlchemyNotificationRepository,
)
from app.config.settings import get_settings
from app.services.ai_engine_client import AIEngineClient, AIEngineError
from app.services.object_storage import MinioStorage, ObjectStorageError

router = APIRouter(prefix="/cameras", tags=["camera"])
logger = logging.getLogger(__name__)


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
        auto_capture_enabled=camera.auto_capture_enabled,
        alert_classes=camera.alert_classes,
        alert_min_confidence=camera.alert_min_confidence,
        is_checkout_zone=camera.is_checkout_zone,
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
            auto_capture_enabled=payload.auto_capture_enabled,
            alert_classes=payload.alert_classes,
            alert_min_confidence=payload.alert_min_confidence,
            is_checkout_zone=payload.is_checkout_zone,
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
            auto_capture_enabled=payload.auto_capture_enabled,
            alert_classes=_resolve(
                payload.alert_classes, payload.alert_classes_unset
            ),
            alert_min_confidence=_resolve(
                payload.alert_min_confidence, payload.alert_min_confidence_unset
            ),
            is_checkout_zone=payload.is_checkout_zone,
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
        camera = await service.get(current.organization_id, camera_id)
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

    image_key: str | None = None
    try:
        storage = MinioStorage(get_settings())
        ext = (image.filename or "frame").rsplit(".", 1)
        suffix = ext[1].lower() if len(ext) == 2 and len(ext[1]) <= 8 else "bin"
        image_key = (
            f"detections/{current.organization_id}/{camera_id}/"
            f"{uuid.uuid4()}.{suffix}"
        )
        await storage.put(
            image_key,
            content,
            content_type=image.content_type or "application/octet-stream",
        )
    except ObjectStorageError:
        image_key = None

    detection_service = DetectionService(SqlAlchemyDetectionRepository(session))
    event = await detection_service.record(
        organization_id=current.organization_id,
        camera_id=camera_id,
        user_id=current.user_id,
        result=result,
        image_key=image_key,
    )

    notification_service = NotificationService(
        SqlAlchemyNotificationRepository(session)
    )
    dispatcher = DetectionAlertDispatcher(notification_service, get_settings())
    alerts_sent = await dispatcher.dispatch(event, camera, session=session)

    frame_pipeline: dict[str, Any] | None = None
    frame_error: str | None = None
    try:
        frame_pipeline = await client.frame(
            content=content,
            filename=image.filename or "frame.jpg",
            content_type=image.content_type or "image/jpeg",
            organization_id=str(current.organization_id),
            branch_id=str(camera.branch_id),
            camera_id=str(camera_id),
            recognize_face=False,
        )
    except AIEngineError as exc:
        frame_error = str(exc)
        logger.warning("ai-engine frame pipeline failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        frame_error = f"{type(exc).__name__}: {exc}"
        logger.exception("ai-engine frame pipeline crashed")

    return {
        "camera_id": str(camera_id),
        "detection_event_id": str(event.id),
        "image_key": image_key,
        "alerts_sent": alerts_sent,
        "frame_pipeline": frame_pipeline,
        "frame_pipeline_error": frame_error,
        **result,
    }


@router.post("/{camera_id}/preview")
async def preview_camera_stream(
    camera_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = _service(session)
    try:
        camera = await service.get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if not camera.stream_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Camera has no stream_url configured",
        )

    client = AIEngineClient()
    try:
        result = await client.capture(
            stream_url=camera.stream_url,
            open_timeout_ms=get_settings().RTSP_CAPTURE_OPEN_TIMEOUT_MS,
        )
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc

    return {
        "camera_id": str(camera_id),
        "camera_name": camera.name,
        "model": result.get("model"),
        "image": result.get("image"),
        "elapsed_ms": result.get("elapsed_ms"),
        "detections": result.get("detections", []),
        "frame_base64": result.get("frame_base64"),
    }


@router.get("/{camera_id}/live")
async def live_camera_stream(
    camera_id: uuid.UUID,
    detect: bool = Query(default=True),
    detect_every_n: int = Query(default=3, ge=1, le=15),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Continuous MJPEG live view — unlike /preview (one frame, then
    closed), this keeps the connection open and streams frames until the
    browser tab closes or the request is cancelled. Same JWT bearer auth
    as every other route here; the frontend can't use a plain <img src>
    (no way to attach the Authorization header to an <img> request), so
    it fetches this manually and parses the multipart frames itself — see
    frontend/src/utils/mjpegStream.ts.

    ``detect`` (default on) asks ai-engine to burn YOLO boxes + a small
    HUD into the frames before they reach us — see live.py. Purely a
    pass-through param; the backend never decodes a single frame here.
    """
    service = _service(session)
    try:
        camera = await service.get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if not camera.stream_url:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Camera has no stream_url configured",
        )

    client = AIEngineClient()
    return StreamingResponse(
        client.live_stream(
            stream_url=camera.stream_url,
            open_timeout_ms=get_settings().RTSP_CAPTURE_OPEN_TIMEOUT_MS,
            detect=detect,
            detect_every_n=detect_every_n,
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/{camera_id}/simulated-stream", response_model=CameraResponse)
async def upload_simulated_stream(
    camera_id: uuid.UUID,
    video: UploadFile = File(...),
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> CameraResponse:
    """Course-project camera simulation (no physical cameras yet): uploads
    a demo video, stores it in a public-read MinIO bucket, and points this
    camera's stream_url at the standalone camera-sim-runner's RTSP loop
    for it — same code path a real RTSP camera would use later. See
    docs/21_CAMERA_MANAGER.md and docker-compose.yml's "camera-sim" block.
    """
    repo = SqlAlchemyCameraRepository(session)
    service = CameraService(repo)
    try:
        await service.get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    content = await video.read()

    storage = CameraSimStorage(get_settings())
    try:
        stream_url = await storage.upload_video(
            str(camera_id),
            filename=video.filename or "video.mp4",
            content=content,
            content_type=video.content_type or "video/mp4",
        )
    except CameraSimError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        await service.update(current.organization_id, camera_id, stream_url=stream_url)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return await _load_response(repo, service, current.organization_id, camera_id)
