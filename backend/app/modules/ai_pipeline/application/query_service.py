"""Read side of the AI pipeline dashboard: session -> frame -> steps.

Kept separate from ``telemetry_service`` because the two have opposite
shapes and opposite risks. Ingest is write-heavy, runs unattended, and must
never block the engine. Queries are read-only, run interactively, and must
never scan a table that grows by millions of rows a day — so every method
here is bounded by a limit and hits one of the composite indexes declared
on the models.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_pipeline.infrastructure.models import (
    AiClassification,
    AiDetection,
    AiEvent,
    AiFrame,
    AiLog,
    AiSession,
    AiTrack,
)

# Hard ceiling on any list endpoint. A dashboard that accidentally asks for
# a million frames would take the database down with it; refusing to return
# more than this is a cheaper failure than an unbounded scan.
MAX_LIMIT = 200


def _clamp(limit: int) -> int:
    return max(1, min(int(limit or 50), MAX_LIMIT))


class PipelineQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_sessions(
        self,
        *,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(AiSession).where(AiSession.organization_id == organization_id)
        count_stmt = select(func.count()).select_from(AiSession).where(
            AiSession.organization_id == organization_id
        )
        if camera_id is not None:
            stmt = stmt.where(AiSession.camera_id == camera_id)
            count_stmt = count_stmt.where(AiSession.camera_id == camera_id)

        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(
                stmt.order_by(AiSession.started_at.desc())
                .limit(_clamp(limit))
                .offset(max(0, offset))
            )
        ).scalars().all()
        return {"items": rows, "total": total}

    async def list_frames(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
        only_rejected: bool = False,
    ) -> dict[str, Any]:
        """Frames of one session, oldest first.

        Ascending because this feeds a timeline the operator steps through
        with Previous/Next; a reversed list would make "next" mean "earlier",
        which reads backwards for a debugging tool.

        ``only_rejected`` is the shortcut for the common question "which
        frames did the quality gate throw away, and why" — otherwise you
        page through hundreds of healthy frames to find them.
        """
        stmt = select(AiFrame).where(
            AiFrame.organization_id == organization_id,
            AiFrame.session_id == session_id,
        )
        count_stmt = select(func.count()).select_from(AiFrame).where(
            AiFrame.organization_id == organization_id,
            AiFrame.session_id == session_id,
        )
        if only_rejected:
            stmt = stmt.where(AiFrame.gate_passed.is_(False))
            count_stmt = count_stmt.where(AiFrame.gate_passed.is_(False))

        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(
                stmt.order_by(AiFrame.seq.asc())
                .limit(_clamp(limit))
                .offset(max(0, offset))
            )
        ).scalars().all()
        return {"items": rows, "total": total}

    async def get_frame_detail(
        self, *, organization_id: uuid.UUID, frame_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """One frame with its detections, classifications and log lines.

        Assembled in three queries rather than one join: a join would
        multiply the frame's columns across every detection row and every
        log line, and the log lines would multiply the detections again.
        Three small indexed queries move less data than one cartesian one.
        """
        frame = (
            await self.session.execute(
                select(AiFrame).where(
                    AiFrame.id == frame_id,
                    AiFrame.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if frame is None:
            return None

        detections = (
            await self.session.execute(
                select(AiDetection)
                .where(AiDetection.frame_id == frame_id)
                .order_by(AiDetection.confidence.desc())
            )
        ).scalars().all()

        det_ids = [d.id for d in detections]
        classifications: dict[uuid.UUID, AiClassification] = {}
        if det_ids:
            for row in (
                await self.session.execute(
                    select(AiClassification).where(
                        AiClassification.detection_id.in_(det_ids)
                    )
                )
            ).scalars().all():
                classifications[row.detection_id] = row

        logs = (
            await self.session.execute(
                select(AiLog)
                .where(AiLog.frame_id == frame_id)
                .order_by(AiLog.created_at.asc())
                .limit(MAX_LIMIT)
            )
        ).scalars().all()

        return {
            "frame": frame,
            "detections": [
                {"detection": d, "classification": classifications.get(d.id)}
                for d in detections
            ],
            "logs": logs,
        }

    async def neighbour_frames(
        self, *, organization_id: uuid.UUID, frame: AiFrame
    ) -> dict[str, uuid.UUID | None]:
        """Ids of the previous/next frame in the same session.

        Resolved server-side so the UI's Previous/Next work even when the
        operator arrived by deep link and never loaded the frame list.
        """
        prev_id = (
            await self.session.execute(
                select(AiFrame.id)
                .where(
                    AiFrame.session_id == frame.session_id,
                    AiFrame.organization_id == organization_id,
                    AiFrame.seq < frame.seq,
                )
                .order_by(AiFrame.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        next_id = (
            await self.session.execute(
                select(AiFrame.id)
                .where(
                    AiFrame.session_id == frame.session_id,
                    AiFrame.organization_id == organization_id,
                    AiFrame.seq > frame.seq,
                )
                .order_by(AiFrame.seq.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return {"previous_frame_id": prev_id, "next_frame_id": next_id}

    async def list_tracks(
        self, *, organization_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[AiTrack]:
        return list(
            (
                await self.session.execute(
                    select(AiTrack)
                    .where(
                        AiTrack.organization_id == organization_id,
                        AiTrack.session_id == session_id,
                    )
                    .order_by(AiTrack.first_seen_at.asc())
                    .limit(MAX_LIMIT)
                )
            ).scalars().all()
        )

    async def session_stats(
        self, *, organization_id: uuid.UUID, session_id: uuid.UUID
    ) -> dict[str, Any]:
        """Aggregates for the session header.

        These are the numbers that tell an operator whether the pipeline is
        healthy without opening a single frame: how much the quality gate
        rejected, what the latency looks like, and how confident the model
        was on average.
        """
        agg = (
            await self.session.execute(
                select(
                    func.count(AiFrame.id),
                    func.avg(AiFrame.total_ms),
                    func.max(AiFrame.total_ms),
                    func.avg(AiFrame.quality_score),
                    func.count(AiFrame.id).filter(AiFrame.gate_passed.is_(False)),
                ).where(
                    AiFrame.organization_id == organization_id,
                    AiFrame.session_id == session_id,
                )
            )
        ).one()

        det_agg = (
            await self.session.execute(
                select(func.count(AiDetection.id), func.avg(AiDetection.confidence))
                .select_from(AiDetection)
                .join(AiFrame, AiFrame.id == AiDetection.frame_id)
                .where(AiFrame.session_id == session_id)
            )
        ).one()

        event_count = (
            await self.session.execute(
                select(func.count(AiEvent.id)).where(AiEvent.session_id == session_id)
            )
        ).scalar_one()

        frames, avg_ms, max_ms, avg_q, rejected = agg
        det_count, avg_conf = det_agg
        return {
            "frame_count": int(frames or 0),
            "rejected_count": int(rejected or 0),
            "reject_rate": round((rejected or 0) / frames, 4) if frames else 0.0,
            "avg_total_ms": round(float(avg_ms), 2) if avg_ms is not None else None,
            "max_total_ms": round(float(max_ms), 2) if max_ms is not None else None,
            "avg_quality_score": round(float(avg_q), 3) if avg_q is not None else None,
            "detection_count": int(det_count or 0),
            "avg_confidence": round(float(avg_conf), 4) if avg_conf is not None else None,
            "event_count": int(event_count or 0),
        }
