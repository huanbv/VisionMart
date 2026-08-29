"""HTTP router for AI pipeline telemetry — ingest + dashboard reads.

Two audiences with two different authentication schemes, which is why they
share a file but not a guard:

* ``/ai/pipeline/sessions`` (open) and ``/ingest`` are called by the
  **ai-engine**, which has no user session — authenticated by the shared
  ``X-AI-Engine-Key``, exactly like the cart-event inbox and the review
  ingest route.
* Everything else is the **admin dashboard**, authenticated by Bearer token
  and restricted to roles that are allowed to see raw model behaviour.

Tenant isolation is applied on every read from the caller's own
``organization_id`` rather than from a query parameter: a dashboard that
took the tenant from the URL would let any authenticated operator read
another organisation's camera footage by editing it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.ai_pipeline.application.query_service import PipelineQueryService
from app.modules.ai_pipeline.application.telemetry_service import TelemetryService
from app.modules.ai_pipeline.schemas.pipeline import (
    FrameDetail,
    FrameList,
    IngestIn,
    IngestResult,
    OpenSessionIn,
    SessionList,
    SessionStats,
    TrackRead,
)

router = APIRouter(prefix="/ai/pipeline", tags=["ai-pipeline"])

_VIEWER_ROLES = ("super_admin", "org_admin", "ai_engineer")


def _require_engine_key(
    x_ai_engine_key: str | None = Header(default=None, alias="X-AI-Engine-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.AI_ENGINE_API_KEY
    if not expected or x_ai_engine_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid AI engine key"
        )


# ------------------------------------------------------------- engine side
@router.post(
    "/sessions/open",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_require_engine_key)],
)
async def open_session(
    payload: OpenSessionIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    service = TelemetryService(session)
    row = await service.open_session(
        organization_id=payload.organization_id,
        branch_id=payload.branch_id,
        camera_id=payload.camera_id,
        camera_key=payload.camera_key,
        detector_version=payload.detector_version,
        classifier_version=payload.classifier_version,
        config_snapshot=payload.config_snapshot,
    )
    await session.commit()
    return {"session_id": str(row.id), "started_at": row.started_at.isoformat()}


@router.post(
    "/sessions/{session_id}/close",
    dependencies=[Depends(_require_engine_key)],
)
async def close_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await TelemetryService(session).close_session(session_id)
    await session.commit()
    return {"status": "closed"}


@router.post(
    "/ingest",
    response_model=IngestResult,
    dependencies=[Depends(_require_engine_key)],
)
async def ingest(
    payload: IngestIn,
    session: AsyncSession = Depends(get_session),
) -> IngestResult:
    """Accept a batch of frame reports.

    Returns counts rather than failing the request when some frames are
    malformed: the engine must not retry (it would fall behind on actual
    inference), and a 200 with ``failed > 0`` gives it something to log
    without needing to interpret a status code.
    """
    result = await TelemetryService(session).ingest_batch(
        organization_id=payload.organization_id,
        session_id=payload.session_id,
        frames=[f.model_dump() for f in payload.frames],
    )
    await session.commit()
    return IngestResult(**result)


# ---------------------------------------------------------- dashboard side
@router.get(
    "/sessions",
    response_model=SessionList,
    dependencies=[Depends(require_roles(*_VIEWER_ROLES))],
)
async def list_sessions(
    camera_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionList:
    data = await PipelineQueryService(session).list_sessions(
        organization_id=user.organization_id,
        camera_id=camera_id,
        limit=limit,
        offset=offset,
    )
    return SessionList(items=data["items"], total=data["total"])


@router.get(
    "/sessions/{session_id}/stats",
    response_model=SessionStats,
    dependencies=[Depends(require_roles(*_VIEWER_ROLES))],
)
async def session_stats(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionStats:
    data = await PipelineQueryService(session).session_stats(
        organization_id=user.organization_id, session_id=session_id
    )
    return SessionStats(**data)


@router.get(
    "/sessions/{session_id}/frames",
    response_model=FrameList,
    dependencies=[Depends(require_roles(*_VIEWER_ROLES))],
)
async def list_frames(
    session_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    only_rejected: bool = Query(False),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FrameList:
    data = await PipelineQueryService(session).list_frames(
        organization_id=user.organization_id,
        session_id=session_id,
        limit=limit,
        offset=offset,
        only_rejected=only_rejected,
    )
    return FrameList(items=data["items"], total=data["total"])


@router.get(
    "/sessions/{session_id}/tracks",
    response_model=list[TrackRead],
    dependencies=[Depends(require_roles(*_VIEWER_ROLES))],
)
async def list_tracks(
    session_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[TrackRead]:
    rows = await PipelineQueryService(session).list_tracks(
        organization_id=user.organization_id, session_id=session_id
    )
    return [TrackRead.model_validate(r) for r in rows]


@router.get(
    "/frames/{frame_id}",
    response_model=FrameDetail,
    dependencies=[Depends(require_roles(*_VIEWER_ROLES))],
)
async def frame_detail(
    frame_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FrameDetail:
    service = PipelineQueryService(session)
    data = await service.get_frame_detail(
        organization_id=user.organization_id, frame_id=frame_id
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Frame not found")
    neighbours = await service.neighbour_frames(
        organization_id=user.organization_id, frame=data["frame"]
    )
    return FrameDetail(
        frame=data["frame"],
        detections=data["detections"],
        logs=data["logs"],
        **neighbours,
    )


@router.get(
    "/frames/{frame_id}/steps",
    dependencies=[Depends(require_roles(*_VIEWER_ROLES))],
)
async def frame_steps(
    frame_id: uuid.UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The per-step debug images for one frame, read from object storage.

    Proxied through the backend rather than handing the browser a MinIO
    URL: the frontend has no storage credentials, and presigning per image
    would leak bucket paths into the client. Returns presigned URLs the
    browser can load directly, which keeps the image bytes off this
    process's event loop.

    A frame whose ``storage_prefix`` is null was processed with DEBUG_AI
    off — that is the normal production case, not an error, so it returns
    an empty list rather than a 404.
    """
    import json

    from app.services.object_storage import MinioStorage

    data = await PipelineQueryService(session).get_frame_detail(
        organization_id=user.organization_id, frame_id=frame_id
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Frame not found")

    prefix = data["frame"].storage_prefix
    if not prefix:
        return {"steps": [], "reason": "DEBUG_AI was off for this frame"}

    storage = MinioStorage()
    try:
        raw = await storage.get_bytes(f"{prefix}/pipeline.json")
        manifest = json.loads(raw.decode("utf-8"))
    except Exception:
        # The manifest is written last, so its absence means the writer was
        # still working (or dropped the job) — not that the frame is bad.
        return {"steps": [], "reason": "Debug artifacts not available yet"}

    steps = []
    for entry in manifest.get("steps", []):
        try:
            url = await storage.presigned_get(entry["key"])
        except Exception:
            # One unsignable step degrades to a missing image, not a failed
            # page — the other seven steps are still worth showing.
            url = None
        steps.append({**entry, "url": url})
    return {"steps": steps, "manifest": manifest}
