"""Router for browsing persisted detection events."""

from __future__ import annotations

import asyncio
import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user
from app.modules.detection.application.detection_service import DetectionService
from app.modules.detection.infrastructure.repositories import (
    SqlAlchemyDetectionRepository,
)
from app.modules.detection.schemas.detection import (
    DetectionCameraCount,
    DetectionClassCount,
    DetectionEventListResponse,
    DetectionEventResponse,
    DetectionEventSummary,
    DetectionSeriesPoint,
    DetectionStatsResponse,
)
from app.services.object_storage import MinioStorage, ObjectStorageError

router = APIRouter(prefix="/detections", tags=["detection"])


def _service(session: AsyncSession) -> DetectionService:
    return DetectionService(SqlAlchemyDetectionRepository(session))


@router.get("/stats", response_model=DetectionStatsResponse)
async def detection_stats(
    camera_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DetectionStatsResponse:
    repo = SqlAlchemyDetectionRepository(session)
    summary = await repo.summary(
        organization_id=current.organization_id,
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
    )
    series = await repo.series_by_day(
        organization_id=current.organization_id,
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
    )
    top_cams = await repo.top_cameras(
        organization_id=current.organization_id,
        date_from=date_from,
        date_to=date_to,
        limit=5,
    )
    top_cls = await repo.top_classes(
        organization_id=current.organization_id,
        camera_id=camera_id,
        date_from=date_from,
        date_to=date_to,
        limit=10,
    )
    return DetectionStatsResponse(
        total_events=summary["total_events"],
        total_detections=summary["total_detections"],
        avg_max_confidence=summary["avg_max_confidence"],
        series=[
            DetectionSeriesPoint(date=d, events=e, detections=n)
            for d, e, n in series
        ],
        top_classes=[
            DetectionClassCount(class_name=cn, count=c) for cn, c in top_cls
        ],
        top_cameras=[
            DetectionCameraCount(camera_id=cid, events=e, detections=n)
            for cid, e, n in top_cams
        ],
    )


@router.get("/export.csv")
async def export_detections_csv(
    camera_id: uuid.UUID | None = None,
    model: str | None = None,
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    max_rows: int = Query(10000, ge=1, le=100000),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    repo = SqlAlchemyDetectionRepository(session)
    batch_size = 500

    async def _row_batches():
        offset = 0
        remaining = max_rows
        while remaining > 0:
            page_size = min(batch_size, remaining)
            events = await repo.list(
                organization_id=current.organization_id,
                camera_id=camera_id,
                model=model,
                min_confidence=min_confidence,
                date_from=date_from,
                date_to=date_to,
                skip=offset,
                limit=page_size,
            )
            if not events:
                return
            for ev in events:
                yield ev
            offset += len(events)
            remaining -= len(events)
            if len(events) < page_size:
                return

    async def _generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "created_at",
                "camera_id",
                "model",
                "detection_count",
                "max_confidence",
                "elapsed_ms",
                "image_width",
                "image_height",
                "image_key",
                "classes",
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        async for ev in _row_batches():
            classes = ",".join(
                sorted(
                    {
                        str(d.get("class_name", ""))
                        for d in (ev.detections or [])
                        if isinstance(d, dict) and d.get("class_name")
                    }
                )
            )
            writer.writerow(
                [
                    str(ev.id),
                    ev.created_at.isoformat() if ev.created_at else "",
                    str(ev.camera_id),
                    ev.model,
                    ev.detection_count,
                    f"{ev.max_confidence:.4f}",
                    ev.elapsed_ms,
                    ev.image_width,
                    ev.image_height,
                    ev.image_key or "",
                    classes,
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"detections_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        _generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("", response_model=DetectionEventListResponse)
async def list_detections(
    camera_id: uuid.UUID | None = None,
    model: str | None = None,
    min_confidence: float | None = Query(None, ge=0.0, le=1.0),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DetectionEventListResponse:
    items, total = await _service(session).list(
        organization_id=current.organization_id,
        camera_id=camera_id,
        model=model,
        min_confidence=min_confidence,
        date_from=date_from,
        date_to=date_to,
        skip=skip,
        limit=limit,
    )
    return DetectionEventListResponse(
        items=[DetectionEventSummary.model_validate(it) for it in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{event_id}", response_model=DetectionEventResponse)
async def get_detection(
    event_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DetectionEventResponse:
    event = await _service(session).get(current.organization_id, event_id)
    if event is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Detection event not found"
        )
    return DetectionEventResponse.model_validate(event)


@router.get("/{event_id}/image")
async def get_detection_image(
    event_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    event = await _service(session).get(current.organization_id, event_id)
    if event is None or not event.image_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")

    storage = MinioStorage()

    def _fetch() -> tuple[bytes, str]:
        client = storage._get_client()
        obj = client.get_object(storage._settings.MINIO_BUCKET, event.image_key)
        try:
            data = obj.read()
            content_type = obj.headers.get(
                "Content-Type", "application/octet-stream"
            )
            return data, content_type
        finally:
            obj.close()
            obj.release_conn()

    try:
        data, content_type = await asyncio.to_thread(_fetch)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Storage error: {exc}"
        ) from exc

    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )
