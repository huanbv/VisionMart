"""Ingest side of AI pipeline telemetry: turning engine reports into rows.

Why the engine pushes instead of writing directly
-------------------------------------------------
The ai-engine has no database credentials and no ORM — deliberately. Giving
an inference service write access to the business database would make every
model deployment a database-schema risk, and would mean the engine could not
be scaled or restarted independently. So it posts a compact JSON report per
frame to the backend, which owns all persistence.

Batching
--------
One HTTP call per frame at 30 fps per camera would be 30 round-trips/sec of
pure overhead. :meth:`ingest_frame` therefore accepts a frame *plus all its
detections and their classifications* in a single payload, written in one
transaction. The engine may also send several frames per call.

Failure policy
--------------
Telemetry is diagnostic. If a report is malformed, the offending frame is
skipped and the rest of the batch is still written — losing one frame's
telemetry is strictly better than losing the batch, and far better than
returning an error that makes the engine retry (and thus fall behind on
actual inference). Errors are counted in the response so the engine can log
them without having to interpret HTTP status codes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
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

logger = logging.getLogger(__name__)


class TelemetryError(Exception):
    """Raised only for problems the caller must fix (bad tenant, missing session)."""


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class TelemetryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------ sessions
    async def open_session(
        self,
        *,
        organization_id: uuid.UUID,
        camera_key: str,
        branch_id: uuid.UUID | None = None,
        camera_id: uuid.UUID | None = None,
        detector_version: str | None = None,
        classifier_version: str | None = None,
        config_snapshot: dict | None = None,
    ) -> AiSession:
        row = AiSession(
            organization_id=organization_id,
            branch_id=branch_id,
            camera_id=camera_id,
            camera_key=camera_key,
            started_at=datetime.now(timezone.utc),
            status="active",
            detector_version=detector_version,
            classifier_version=classifier_version,
            # Snapshotted at open, not read live at render time: a frame from
            # last week must stay explainable after the flags are changed.
            config_snapshot=config_snapshot,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def close_session(self, session_id: uuid.UUID) -> None:
        await self.session.execute(
            update(AiSession)
            .where(AiSession.id == session_id)
            .values(ended_at=datetime.now(timezone.utc), status="closed")
        )

    # -------------------------------------------------------------- frames
    async def ingest_frame(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> AiFrame:
        """Persist one frame and everything it produced, in one transaction."""
        frame = AiFrame(
            session_id=session_id,
            organization_id=organization_id,
            seq=int(payload.get("seq") or 0),
            captured_at=_parse_dt(payload.get("captured_at")),
            width=payload.get("width"),
            height=payload.get("height"),
            storage_prefix=payload.get("storage_prefix"),
            brightness=payload.get("brightness"),
            contrast=payload.get("contrast"),
            blur_score=payload.get("blur_score"),
            quality_score=payload.get("quality_score"),
            gate_passed=bool(payload.get("gate_passed", True)),
            reject_reason=payload.get("reject_reason"),
            preprocess_ms=payload.get("preprocess_ms"),
            detect_ms=payload.get("detect_ms"),
            classify_ms=payload.get("classify_ms"),
            ocr_ms=payload.get("ocr_ms"),
            total_ms=payload.get("total_ms"),
            steps_applied=payload.get("steps_applied"),
        )
        self.session.add(frame)
        await self.session.flush()

        detections = payload.get("detections") or []
        for det in detections:
            track_pk = None
            if det.get("track_id") is not None:
                track = await self._upsert_track(
                    organization_id=organization_id,
                    session_id=session_id,
                    track_id=int(det["track_id"]),
                    class_name=det.get("class_name"),
                    seen_at=frame.captured_at,
                    resolved_sku=det.get("sku"),
                    resolved_confidence=det.get("combined_confidence"),
                    resolved_source=det.get("source"),
                )
                track_pk = track.id

            row = AiDetection(
                frame_id=frame.id,
                organization_id=organization_id,
                track_pk=track_pk,
                track_id=det.get("track_id"),
                class_name=str(det.get("class_name") or "unknown"),
                confidence=float(det.get("confidence") or 0.0),
                x1=float(det.get("x1") or 0.0),
                y1=float(det.get("y1") or 0.0),
                x2=float(det.get("x2") or 0.0),
                y2=float(det.get("y2") or 0.0),
                crop_key=det.get("crop_key"),
                combined_confidence=det.get("combined_confidence"),
            )
            self.session.add(row)
            await self.session.flush()

            clf = det.get("classification")
            if clf and clf.get("sku"):
                self.session.add(
                    AiClassification(
                        detection_id=row.id,
                        organization_id=organization_id,
                        sku=str(clf["sku"]),
                        confidence=float(clf.get("confidence") or 0.0),
                        label_index=clf.get("label_index"),
                        runner_up_sku=clf.get("runner_up_sku"),
                        runner_up_confidence=clf.get("runner_up_confidence"),
                        margin=clf.get("margin"),
                        model_version=clf.get("model_version"),
                        inference_ms=clf.get("inference_ms"),
                    )
                )

        for entry in payload.get("logs") or []:
            self.session.add(
                AiLog(
                    organization_id=organization_id,
                    session_id=session_id,
                    frame_id=frame.id,
                    stage=str(entry.get("stage") or "unknown"),
                    level=str(entry.get("level") or "INFO"),
                    message=str(entry.get("message") or ""),
                    elapsed_ms=entry.get("elapsed_ms"),
                    payload=entry.get("payload"),
                )
            )

        for entry in payload.get("events") or []:
            self.session.add(
                AiEvent(
                    organization_id=organization_id,
                    session_id=session_id,
                    frame_id=frame.id,
                    event_type=str(entry.get("event_type") or "unknown"),
                    confidence=entry.get("confidence"),
                    payload=entry.get("payload"),
                )
            )

        # Counters kept on the session so the session list never needs a
        # COUNT(*) over ai_frames.
        await self.session.execute(
            update(AiSession)
            .where(AiSession.id == session_id)
            .values(
                frame_count=AiSession.frame_count + 1,
                detection_count=AiSession.detection_count + len(detections),
            )
        )
        return frame

    async def _upsert_track(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        track_id: int,
        class_name: str | None,
        seen_at: datetime,
        resolved_sku: str | None,
        resolved_confidence: float | None,
        resolved_source: str | None,
    ) -> AiTrack:
        """Find-or-create the track, extending its lifetime.

        A track's resolved SKU is only *upgraded*, never overwritten with a
        weaker answer: once the classifier has confidently named an object,
        a later low-confidence frame (motion blur, partial occlusion) must
        not be allowed to downgrade it. Without this rule the dashboard —
        and the cart — would flicker between identities for one physical
        product.
        """
        existing = (
            await self.session.execute(
                select(AiTrack).where(
                    AiTrack.session_id == session_id, AiTrack.track_id == track_id
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            row = AiTrack(
                session_id=session_id,
                organization_id=organization_id,
                track_id=track_id,
                class_name=class_name,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                frame_count=1,
                resolved_sku=resolved_sku,
                resolved_confidence=resolved_confidence,
                resolved_source=resolved_source,
            )
            self.session.add(row)
            await self.session.flush()
            return row

        existing.last_seen_at = seen_at
        existing.frame_count += 1
        if resolved_sku and (
            existing.resolved_sku is None
            or (resolved_confidence or 0.0) > (existing.resolved_confidence or 0.0)
        ):
            existing.resolved_sku = resolved_sku
            existing.resolved_confidence = resolved_confidence
            existing.resolved_source = resolved_source
        return existing

    async def ingest_batch(
        self,
        *,
        organization_id: uuid.UUID,
        session_id: uuid.UUID,
        frames: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Write many frames, skipping (not aborting on) bad ones.

        Each frame gets its own SAVEPOINT. This is not stylistic: once a
        ``flush()`` fails, the AsyncSession is poisoned and every later
        statement raises ``PendingRollbackError`` until someone rolls back.
        Catching the exception without a savepoint would therefore turn one
        malformed frame into a failure of the whole remaining batch — the
        exact opposite of the intent. ``begin_nested()`` rolls back only the
        offending frame and leaves the ones already written intact.
        """
        written = failed = 0
        for payload in frames:
            try:
                async with self.session.begin_nested():
                    await self.ingest_frame(
                        organization_id=organization_id,
                        session_id=session_id,
                        payload=payload,
                    )
                written += 1
            except Exception:
                failed += 1
                logger.exception(
                    "telemetry: skipped malformed frame in session %s", session_id
                )
        return {"written": written, "failed": failed}
