"""Active-learning review queue.

The retraining loop this supports is deliberately *human-in-the-loop*:

    capture uncertain / corrected frames
        -> human confirms or fixes the label
            -> approved frames become TrainingImages
                -> next training job trains on them

The alternative — feeding the model's own predictions back in as labels —
looks like "the AI learns by itself", but it makes the model train on its
own mistakes, so systematic errors get reinforced a little more with every
round. That failure is slow and quiet, which is exactly what makes it
dangerous, so approval is a hard requirement here rather than a setting.

Where candidates come from (``source``):

* ``low_confidence``    — the detector was unsure; these are the frames new
  labels are worth the most on, which is the whole idea behind active
  learning (label where the model is weak, not where it is already right).
* ``checkout_mismatch`` — a human corrected the AI during checkout. The
  correction is a gold-standard label that cost nothing extra to collect.
* ``manual``            — an operator flagged the frame from the UI.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_training.infrastructure.models import (
    ReviewCandidate,
    TrainingImage,
)
from app.modules.catalog.infrastructure.models import Product
from app.services.object_storage import MinioStorage, ObjectStorageError

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EXT_BY_TYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024

VALID_SOURCES = {"low_confidence", "checkout_mismatch", "manual"}
VALID_STATUSES = {"pending", "approved", "rejected"}


class ReviewError(RuntimeError):
    pass


class ReviewService:
    def __init__(self, session: AsyncSession, storage: MinioStorage) -> None:
        self._session = session
        self._storage = storage

    # ------------------------------------------------------------------ capture

    async def capture(
        self,
        *,
        organization_id: uuid.UUID,
        content: bytes,
        content_type: str,
        source: str = "low_confidence",
        camera_id: uuid.UUID | None = None,
        predicted_product_id: uuid.UUID | None = None,
        predicted_class: str | None = None,
        confidence: float | None = None,
    ) -> ReviewCandidate:
        """Store a frame in the review queue.

        Called by the detection path when confidence is low, and by the
        checkout flow when a human corrects the AI.
        """
        if source not in VALID_SOURCES:
            raise ReviewError(f"Unknown source: {source}")
        if content_type not in _ALLOWED_TYPES:
            raise ReviewError(f"Unsupported content type: {content_type}")
        if len(content) > _MAX_IMAGE_BYTES:
            raise ReviewError("Image exceeds 12MB limit")

        ext = _EXT_BY_TYPE[content_type]
        key = f"review/{organization_id}/{uuid.uuid4()}.{ext}"
        try:
            await self._storage.put(key, content, content_type=content_type)
        except ObjectStorageError as exc:
            raise ReviewError(f"Storage error: {exc}") from exc

        candidate = ReviewCandidate(
            organization_id=organization_id,
            camera_id=camera_id,
            storage_key=key,
            image_size_bytes=len(content),
            source=source,
            status="pending",
            predicted_product_id=predicted_product_id,
            predicted_class=predicted_class,
            confidence=confidence,
        )
        self._session.add(candidate)
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    # ------------------------------------------------------------------- query

    async def list_candidates(
        self,
        *,
        organization_id: uuid.UUID,
        status: str | None = "pending",
        source: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[ReviewCandidate], int]:
        stmt = select(ReviewCandidate).where(
            ReviewCandidate.organization_id == organization_id,
            ReviewCandidate.is_deleted.is_(False),
        )
        if status:
            if status not in VALID_STATUSES:
                raise ReviewError(f"Unknown status: {status}")
            stmt = stmt.where(ReviewCandidate.status == status)
        if source:
            if source not in VALID_SOURCES:
                raise ReviewError(f"Unknown source: {source}")
            stmt = stmt.where(ReviewCandidate.source == source)

        total = await self._session.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        # Lowest-confidence first: the most informative labels to collect.
        rows = await self._session.scalars(
            stmt.order_by(
                ReviewCandidate.confidence.asc().nullsfirst(),
                ReviewCandidate.created_at.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
        return list(rows), int(total or 0)

    async def stats(self, *, organization_id: uuid.UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(ReviewCandidate.status, func.count())
            .where(
                ReviewCandidate.organization_id == organization_id,
                ReviewCandidate.is_deleted.is_(False),
            )
            .group_by(ReviewCandidate.status)
        )
        counts = {status: int(n) for status, n in rows.all()}
        return {s: counts.get(s, 0) for s in sorted(VALID_STATUSES)}

    async def presign(self, key: str) -> str | None:
        try:
            return await self._storage.presigned_get(key)
        except ObjectStorageError:
            logger.warning("presign failed for %s", key)
            return None

    # ------------------------------------------------------------------ review

    async def approve(
        self,
        *,
        organization_id: uuid.UUID,
        candidate_id: uuid.UUID,
        confirmed_product_id: uuid.UUID,
        reviewed_by: uuid.UUID | None,
        note: str | None = None,
    ) -> ReviewCandidate:
        """Confirm the label and promote the frame into the training set.

        The stored object is *reused* rather than re-uploaded: the same
        bytes are already in object storage, so the TrainingImage points at
        the same key. ``training_image_id`` then makes a second approval a
        no-op instead of creating duplicate training data.
        """
        candidate = await self._get(organization_id, candidate_id)
        if candidate.status == "approved" and candidate.training_image_id:
            return candidate  # idempotent

        product = await self._session.get(Product, confirmed_product_id)
        if product is None or product.organization_id != organization_id:
            raise ReviewError("Product not found")

        image = TrainingImage(
            organization_id=organization_id,
            product_id=confirmed_product_id,
            storage_key=candidate.storage_key,
            # Recorded at capture time — the object store has no cheap
            # size lookup in this codebase's wrapper, and re-downloading
            # the frame just to measure it would be wasteful.
            image_size_bytes=candidate.image_size_bytes or 0,
            image_format=candidate.storage_key.rsplit(".", 1)[-1][:16],
        )
        self._session.add(image)
        await self._session.flush()

        candidate.status = "approved"
        candidate.confirmed_product_id = confirmed_product_id
        candidate.reviewed_by = reviewed_by
        candidate.reviewed_at = datetime.now(timezone.utc)
        candidate.review_note = note
        candidate.training_image_id = image.id

        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def reject(
        self,
        *,
        organization_id: uuid.UUID,
        candidate_id: uuid.UUID,
        reviewed_by: uuid.UUID | None,
        note: str | None = None,
    ) -> ReviewCandidate:
        """Discard the frame — unusable (occluded, motion-blurred, empty).

        Rejections are kept rather than deleted: a queue that is mostly
        rejects is itself a signal that the capture threshold is wrong.
        """
        candidate = await self._get(organization_id, candidate_id)
        candidate.status = "rejected"
        candidate.reviewed_by = reviewed_by
        candidate.reviewed_at = datetime.now(timezone.utc)
        candidate.review_note = note
        await self._session.commit()
        await self._session.refresh(candidate)
        return candidate

    async def _get(
        self, organization_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> ReviewCandidate:
        candidate = await self._session.get(ReviewCandidate, candidate_id)
        if (
            candidate is None
            or candidate.is_deleted
            or candidate.organization_id != organization_id
        ):
            raise ReviewError("Review candidate not found")
        return candidate
