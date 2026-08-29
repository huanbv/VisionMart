"""SQLAlchemy repository for the Detection bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.detection.infrastructure.models import DetectionEvent


class SqlAlchemyDetectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _apply_filters(
        self,
        stmt,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None,
        model: str | None,
        min_confidence: float | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ):
        stmt = stmt.where(DetectionEvent.organization_id == organization_id)
        if camera_id is not None:
            stmt = stmt.where(DetectionEvent.camera_id == camera_id)
        if model:
            stmt = stmt.where(DetectionEvent.model == model)
        if min_confidence is not None:
            stmt = stmt.where(DetectionEvent.max_confidence >= min_confidence)
        if date_from is not None:
            stmt = stmt.where(DetectionEvent.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(DetectionEvent.created_at <= date_to)
        return stmt

    async def add(self, event: DetectionEvent) -> DetectionEvent:
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(event)
        return event

    async def get(
        self, organization_id: uuid.UUID, event_id: uuid.UUID
    ) -> DetectionEvent | None:
        stmt = select(DetectionEvent).where(
            DetectionEvent.id == event_id,
            DetectionEvent.organization_id == organization_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        model: str | None = None,
        min_confidence: float | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Sequence[DetectionEvent]:
        stmt = self._apply_filters(
            select(DetectionEvent),
            organization_id=organization_id,
            camera_id=camera_id,
            model=model,
            min_confidence=min_confidence,
            date_from=date_from,
            date_to=date_to,
        ).order_by(DetectionEvent.created_at.desc()).offset(skip).limit(limit)
        return (await self._session.execute(stmt)).scalars().all()

    async def count(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        model: str | None = None,
        min_confidence: float | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        stmt = self._apply_filters(
            select(func.count(DetectionEvent.id)),
            organization_id=organization_id,
            camera_id=camera_id,
            model=model,
            min_confidence=min_confidence,
            date_from=date_from,
            date_to=date_to,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def summary(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> dict:
        stmt = self._apply_filters(
            select(
                func.count(DetectionEvent.id),
                func.coalesce(func.sum(DetectionEvent.detection_count), 0),
                func.coalesce(func.avg(DetectionEvent.max_confidence), 0.0),
            ),
            organization_id=organization_id,
            camera_id=camera_id,
            model=None,
            min_confidence=None,
            date_from=date_from,
            date_to=date_to,
        )
        row = (await self._session.execute(stmt)).one()
        return {
            "total_events": int(row[0] or 0),
            "total_detections": int(row[1] or 0),
            "avg_max_confidence": float(row[2] or 0.0),
        }

    async def series_by_day(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[tuple[str, int, int]]:
        day = func.date_trunc("day", DetectionEvent.created_at).label("day")
        stmt = self._apply_filters(
            select(
                day,
                func.count(DetectionEvent.id),
                func.coalesce(func.sum(DetectionEvent.detection_count), 0),
            ),
            organization_id=organization_id,
            camera_id=camera_id,
            model=None,
            min_confidence=None,
            date_from=date_from,
            date_to=date_to,
        ).group_by(day).order_by(day)
        rows = (await self._session.execute(stmt)).all()
        return [
            (
                r[0].date().isoformat() if r[0] is not None else "",
                int(r[1] or 0),
                int(r[2] or 0),
            )
            for r in rows
        ]

    async def top_cameras(
        self,
        *,
        organization_id: uuid.UUID,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 5,
    ) -> list[tuple[uuid.UUID, int, int]]:
        stmt = self._apply_filters(
            select(
                DetectionEvent.camera_id,
                func.count(DetectionEvent.id),
                func.coalesce(func.sum(DetectionEvent.detection_count), 0),
            ),
            organization_id=organization_id,
            camera_id=None,
            model=None,
            min_confidence=None,
            date_from=date_from,
            date_to=date_to,
        ).group_by(DetectionEvent.camera_id).order_by(
            func.count(DetectionEvent.id).desc()
        ).limit(limit)
        rows = (await self._session.execute(stmt)).all()
        return [(r[0], int(r[1] or 0), int(r[2] or 0)) for r in rows]

    async def top_classes(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 10,
    ) -> list[tuple[str, int]]:
        params: dict = {"org_id": str(organization_id), "lim": limit}
        clauses = ["organization_id = :org_id"]
        if camera_id is not None:
            clauses.append("camera_id = :camera_id")
            params["camera_id"] = str(camera_id)
        if date_from is not None:
            clauses.append("created_at >= :date_from")
            params["date_from"] = date_from
        if date_to is not None:
            clauses.append("created_at <= :date_to")
            params["date_to"] = date_to
        where_sql = " AND ".join(clauses)
        sql = text(
            f"""
            SELECT elem->>'class_name' AS class_name, COUNT(*) AS n
            FROM detection_events,
                 jsonb_array_elements(detections) AS elem
            WHERE {where_sql}
              AND elem->>'class_name' IS NOT NULL
            GROUP BY class_name
            ORDER BY n DESC
            LIMIT :lim
            """
        )
        rows = (await self._session.execute(sql, params)).all()
        return [(str(r[0]), int(r[1] or 0)) for r in rows]

    async def list_older_than(
        self, cutoff: datetime, *, limit: int
    ) -> list[tuple[uuid.UUID, str | None]]:
        stmt = (
            select(DetectionEvent.id, DetectionEvent.image_key)
            .where(DetectionEvent.created_at < cutoff)
            .order_by(DetectionEvent.created_at.asc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]

    async def hard_delete_ids(self, ids: list[uuid.UUID]) -> int:
        if not ids:
            return 0
        from sqlalchemy import delete as sa_delete

        stmt = sa_delete(DetectionEvent).where(DetectionEvent.id.in_(ids))
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount or 0)
