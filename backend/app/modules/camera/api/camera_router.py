"""Camera router."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.camera.application.ai_auto_scan import (
    is_branch_auto_scan_paused,
    set_branch_auto_scan_paused,
)
from app.modules.camera.application.camera_sim import CameraSimError, CameraSimStorage
from app.modules.camera.application.services import CameraService
from app.modules.camera.infrastructure.models import Camera
from app.modules.camera.infrastructure.repositories import (
    SqlAlchemyCameraRepository,
)
from app.modules.camera.schemas.camera import (
    RoiZonesUpdate,
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
from app.modules.detection.application.detection_service import (
    DetectionService,
    archive_product_detections,
)
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)
from app.modules.notification.application.services import NotificationService
from app.modules.notification.infrastructure.repositories import (
    SqlAlchemyNotificationRepository,
)
from app.config.settings import get_settings
from app.services.ai_engine_client import (
    AIEngineClient,
    AIEngineError,
    AIEngineNotFoundError,
)
from app.services.object_storage import MinioStorage, ObjectStorageError

router = APIRouter(prefix="/cameras", tags=["camera"])
logger = logging.getLogger(__name__)


def _service(session: AsyncSession) -> CameraService:
    return CameraService(SqlAlchemyCameraRepository(session))


async def _catalog_sku_names(
    session: AsyncSession, organization_id: uuid.UUID
) -> dict[str, str]:
    try:
        from app.modules.catalog.infrastructure.repositories import (
            SqlAlchemyProductRepository,
        )

        items, _ = await SqlAlchemyProductRepository(session).list_for_org(
            organization_id, skip=0, limit=500, is_active=True
        )
        return {p.sku: p.name for p in items if p.sku}
    except Exception:
        logger.exception("could not load catalog names for detection archive")
        return {}


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
        roi_zones=camera.roi_zones,
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


class AiAutoScanState(BaseModel):
    branch_id: uuid.UUID
    paused: bool


class AiAutoScanUpdate(BaseModel):
    branch_id: uuid.UUID
    paused: bool


async def _require_branch_in_org(
    session: AsyncSession, organization_id: uuid.UUID, branch_id: uuid.UUID
) -> None:
    repo = SqlAlchemyCameraRepository(session)
    branch = await repo.get_branch_in_org(organization_id, branch_id)
    if branch is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Branch not found")


@router.get("/ai-auto-scan", response_model=AiAutoScanState)
async def get_ai_auto_scan(
    branch_id: uuid.UUID = Query(...),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AiAutoScanState:
    """Whether Celery auto-scan is paused for this branch (Live Cart toggle)."""
    await _require_branch_in_org(session, current.organization_id, branch_id)
    paused = await is_branch_auto_scan_paused(branch_id)
    return AiAutoScanState(branch_id=branch_id, paused=paused)


@router.put("/ai-auto-scan", response_model=AiAutoScanState)
async def update_ai_auto_scan(
    payload: AiAutoScanUpdate,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AiAutoScanState:
    """Pause/resume automatic cart-scan. Manual Chụp & Quét / analyze still run."""
    await _require_branch_in_org(session, current.organization_id, payload.branch_id)
    paused = await set_branch_auto_scan_paused(payload.branch_id, payload.paused)
    logger.info(
        "AI auto-scan %s for branch=%s by user=%s",
        "paused" if paused else "resumed",
        payload.branch_id,
        current.user_id,
    )
    return AiAutoScanState(branch_id=payload.branch_id, paused=paused)


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
    result: dict[str, Any] | None = None
    # A caller-selected detector still needs the legacy /detect result.
    # Live Cart does not select one: /ai/frame now returns the same metadata,
    # so avoid running YOLO twice for every uploaded image.
    if model is not None:
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
            # Upload ảnh phân tích = nhập đơn thủ công: bỏ ROI + phiên riêng để
            # luôn tạo một đơn mới trong giỏ AI, không đụng luồng camera live.
            manual_scan=True,
            skip_roi=True,
            min_confidence=0.35,
        )
    except AIEngineError as exc:
        frame_error = str(exc)
        logger.warning("ai-engine frame pipeline failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        frame_error = f"{type(exc).__name__}: {exc}"
        logger.exception("ai-engine frame pipeline crashed")

    if result is None and frame_pipeline is not None:
        result = {
            "model": frame_pipeline.get("model") or "unknown",
            "image": frame_pipeline.get("image") or {},
            "elapsed_ms": frame_pipeline.get("elapsed_ms") or 0,
            "detections": frame_pipeline.get("detections") or [],
        }
    elif result is None:
        # Preserve the old behavior when the cart pipeline is unavailable:
        # archive plain detector output instead of losing the upload entirely.
        try:
            result = await client.detect(
                content=content,
                filename=image.filename or "frame.jpg",
                content_type=image.content_type or "image/jpeg",
            )
        except AIEngineError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
            ) from exc

    sku_names = await _catalog_sku_names(session, current.organization_id)
    image_meta = result.get("image") or {}
    archived = archive_product_detections(
        None if frame_error else (frame_pipeline or {}).get("detections"),
        result.get("detections"),
        sku_names,
        image_width=int(image_meta.get("width") or 0),
        image_height=int(image_meta.get("height") or 0),
        roi_zones=None,
    )
    record_payload = {**result, "detections": archived}

    detection_service = DetectionService(SqlAlchemyDetectionRepository(session))
    event = await detection_service.record(
        organization_id=current.organization_id,
        camera_id=camera_id,
        user_id=current.user_id,
        result=record_payload,
        image_key=image_key,
    )

    notification_service = NotificationService(
        SqlAlchemyNotificationRepository(session)
    )
    dispatcher = DetectionAlertDispatcher(notification_service, get_settings())
    alerts_sent = await dispatcher.dispatch(event, camera, session=session)

    return {
        "camera_id": str(camera_id),
        "detection_event_id": str(event.id),
        "image_key": image_key,
        "alerts_sent": alerts_sent,
        "frame_pipeline": frame_pipeline,
        "frame_pipeline_error": frame_error,
        **result,
        "detections": archived,
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


@router.post("/{camera_id}/pipeline-trace")
async def trace_camera_pipeline(
    camera_id: uuid.UUID,
    file: UploadFile = File(...),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Run the OpenCV preprocessing chain over one frame and return every
    intermediate stage.

    This is the data behind the admin "see every step" view: instead of
    only the final image, the operator gets input → ROI → each enabled
    enhancement → final, with the brightness/contrast/blur measured after
    each stage so it's visible *which* step changed what.

    Detection is not run here — this endpoint is about the preprocessing
    chain only.
    """
    service = _service(session)
    try:
        camera = await service.get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty upload.")

    client = AIEngineClient()
    try:
        result = await client.trace_frame(
            content=content,
            filename=file.filename or "frame.jpg",
            content_type=file.content_type or "image/jpeg",
            camera_key=str(camera_id),
        )
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc

    result["camera_id"] = str(camera_id)
    result["camera_name"] = camera.name
    return result


@router.get("/{camera_id}/pipeline-trace/{trace_id}/{stage_file}")
async def get_pipeline_trace_image(
    camera_id: uuid.UUID,
    trace_id: str,
    stage_file: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Proxy one stage image so the browser never needs object-storage
    credentials (and so tenant isolation is enforced here rather than
    trusting the client)."""
    service = _service(session)
    try:
        await service.get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    client = AIEngineClient()
    try:
        content, media_type = await client.trace_image(
            trace_id=trace_id, stage_file=stage_file, camera_key=str(camera_id)
        )
    except AIEngineNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AIEngineError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}"
        ) from exc

    return Response(content=content, media_type=media_type)


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

    ``detect`` (default on) asks ai-engine to draw the latest cached
    `/ai/frame` results + HUD before frames reach us. The backend never
    decodes a frame and live viewing does not launch another dense YOLO.
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
    # Chuyển vùng ROI xuống ai-engine để lớp phủ live chỉ vẽ box TRONG vùng,
    # khớp với hành vi thêm-vào-giỏ (vốn dựa trên mặt nạ ROI). Không có vùng
    # thì bỏ qua — panel giữ nguyên hành vi vẽ cả khung như trước.
    roi_zones_json = json.dumps(camera.roi_zones) if camera.roi_zones else None
    sku_names_json = None
    try:
        from app.modules.catalog.infrastructure.repositories import (
            SqlAlchemyProductRepository,
        )

        items, _ = await SqlAlchemyProductRepository(session).list_for_org(
            current.organization_id, skip=0, limit=200, is_active=True
        )
        sku_names_json = json.dumps(
            {p.sku: p.name for p in items if p.sku},
            ensure_ascii=False,
        )
    except Exception:
        logger.exception("live stream: could not load product names for overlay")
    return StreamingResponse(
        client.live_stream(
            stream_url=camera.stream_url,
            fps=30.0,
            open_timeout_ms=get_settings().RTSP_CAPTURE_OPEN_TIMEOUT_MS,
            detect=detect,
            detect_every_n=detect_every_n,
            roi_zones=roi_zones_json,
            organization_id=str(current.organization_id),
            branch_id=str(camera.branch_id),
            sku_names=sku_names_json,
            camera_key=str(camera.id),
            # Reuse /ai/frame results instead of running a second dense YOLO
            # beside MJPEG encoding; the latter saturated CPU and held live
            # video near 5 FPS even after inference became asynchronous.
            use_cached_detections=True,
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/{camera_id}/trigger-scan")
async def trigger_camera_scan(
    camera_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Capture 1 frame from the live camera stream right now, run AI Engine analysis,
    update the cart, and return the detection breakdown & frame overlay to the frontend instantly."""
    service = _service(session)
    try:
        camera = await service.get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if not camera.stream_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Camera has no stream_url configured")

    client = AIEngineClient()
    try:
        cap_res = await client.capture(
            stream_url=camera.stream_url,
            open_timeout_ms=get_settings().RTSP_CAPTURE_OPEN_TIMEOUT_MS,
            # The captured JPEG is immediately sent through /ai/frame below.
            # Running detector inference here as well doubled scan latency.
            detect=False,
        )
    except AIEngineError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"AI engine error: {exc}") from exc

    image_b64 = cap_res.get("frame_base64") if isinstance(cap_res, dict) else None
    if not image_b64:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Failed to capture frame from camera stream")

    import base64
    import binascii

    try:
        image_bytes = base64.b64decode(image_b64)
    except (binascii.Error, ValueError, TypeError) as exc:
        # Guard the one unwrapped line in this handler: a malformed/empty
        # frame from a stressed RTSP capture would otherwise surface as a
        # bare 500 ("Không chụp/quét được") with no actionable message.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Bad frame data from camera stream: {exc}",
        ) from exc

    frame_res = {}
    try:
        # AIEngineClient exposes `frame`, not `detect_frame` — the old name
        # never existed, so this call raised AttributeError every time (caught
        # below), meaning the scan captured a frame but NEVER ran the cart
        # pipeline: no product_scanned, nothing added to the cart.
        frame_res = await client.frame(
            content=image_bytes,
            filename="manual_capture.jpg",
            content_type="image/jpeg",
            organization_id=str(current.organization_id),
            branch_id=str(camera.branch_id),
            camera_id=str(camera_id),
            # Nút "Chụp & Quét" = nhập đơn thủ công 1 khung: luôn emit
            # product_scanned ngay, không đi nhánh checkout (grace/người).
            # GIỮ ROI — chỉ sản phẩm trong Vùng Thanh Toán.
            manual_scan=True,
            skip_roi=False,
            min_confidence=0.35,
        )
    except Exception as exc:
        logger.exception("AI engine frame failed during manual trigger scan: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"AI frame pipeline failed: {exc}",
        ) from exc

    image_key: str | None = None
    try:
        storage = MinioStorage(get_settings())
        image_key = (
            f"detections/{current.organization_id}/{camera_id}/"
            f"{uuid.uuid4()}.jpg"
        )
        await storage.put(image_key, image_bytes, content_type="image/jpeg")
    except ObjectStorageError:
        image_key = None

    sku_names = await _catalog_sku_names(session, current.organization_id)
    archived = archive_product_detections(
        frame_res.get("detections"),
        None,
        sku_names,
        image_width=int((cap_res.get("image") or {}).get("width") or 0)
        if isinstance(cap_res, dict)
        else 0,
        image_height=int((cap_res.get("image") or {}).get("height") or 0)
        if isinstance(cap_res, dict)
        else 0,
        roi_zones=camera.roi_zones,
    )
    cap_image = cap_res.get("image") if isinstance(cap_res, dict) else {}
    detection_service = DetectionService(SqlAlchemyDetectionRepository(session))
    event = await detection_service.record(
        organization_id=current.organization_id,
        camera_id=camera_id,
        user_id=current.user_id,
        result={
            "model": frame_res.get("model")
            or (cap_res.get("model") if isinstance(cap_res, dict) else None)
            or "unknown",
            "image": cap_image or {},
            "elapsed_ms": frame_res.get("elapsed_ms")
            or (cap_res.get("elapsed_ms") if isinstance(cap_res, dict) else 0)
            or 0,
            "detections": archived,
        },
        image_key=image_key,
    )

    return {
        "status": "ok",
        "camera_id": str(camera_id),
        "camera_name": camera.name,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "frame_base64": image_b64,
        "detection_event_id": str(event.id),
        "emitted_events": frame_res.get("emitted_events", []),
        "detections": archived,
        "products": frame_res.get("products", 0),
    }


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


# --------------------------------------------------------------------
# Vung nhan dien (ROI)
#
# Luu vao cot cameras.roi_zones. ai-engine doc qua /ai/cameras/{id} — lan
# goi no da thuc hien san cho moi khung hinh va cache 30 giay — nen vung
# ve xong co hieu luc trong vong 30 giay ma khong can restart dich vu hay
# sua file YAML.
#
# Vung rong ([]) co y nghia RO RANG: "khong gioi han vung", tuc tat ROI
# cho camera nay. Khong dung null de phan biet voi "chua bao gio cau
# hinh" — ca hai deu cho ket qua giong nhau o engine, nhung [] the hien
# nguoi dung da chu dong xoa vung.
# --------------------------------------------------------------------
@router.get("/{camera_id}/roi-zones")
async def get_roi_zones(
    camera_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    repo = SqlAlchemyCameraRepository(session)
    try:
        camera = await CameraService(repo).get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"zones": camera.roi_zones or []}


@router.put("/{camera_id}/roi-zones", response_model=CameraResponse)
async def update_roi_zones(
    camera_id: uuid.UUID,
    payload: RoiZonesUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> CameraResponse:
    repo = SqlAlchemyCameraRepository(session)
    service = CameraService(repo)
    try:
        camera = await service.get(current.organization_id, camera_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    camera.roi_zones = [z.model_dump() for z in payload.zones]
    await session.commit()
    await session.refresh(camera)
    return await _load_response(repo, service, current.organization_id, camera_id)
