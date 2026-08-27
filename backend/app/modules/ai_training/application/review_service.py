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

from sqlalchemy import func, select, update
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

# Stock YOLO furniture/scene names that fire on an empty pay-zone (wood +
# black mask). These must never enter the review queue or train set.
_NON_PRODUCT_CLASSES = frozenset(
    {
        "person",
        "dining table",
        "chair",
        "couch",
        "bed",
        "toilet",
        "tv",
        "laptop",
        "mouse",
        "remote",
        "keyboard",
        "cell phone",
        "microwave",
        "oven",
        "toaster",
        "sink",
        "refrigerator",
        "book",
        "clock",
        "vase",
        "potted plant",
        "bench",
        "parking meter",
        "traffic light",
        "stop sign",
        "fire hydrant",
        "teddy bear",
        "hair drier",
        "toothbrush",
        "scissors",
        "umbrella",
        "backpack",
        "handbag",
        "suitcase",
        "tie",
    }
)


def is_non_product_class(name: str | None) -> bool:
    return bool(name) and str(name).strip().lower() in _NON_PRODUCT_CLASSES


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
        crop_content: bytes | None = None,
        bbox: dict | None = None,
    ) -> ReviewCandidate:
        """Store a frame in the review queue.

        Called by the detection path when confidence is low, and by the
        checkout flow when a human corrects the AI.
        """
        if source not in VALID_SOURCES:
            raise ReviewError(f"Unknown source: {source}")
        if is_non_product_class(predicted_class):
            raise ReviewError("skip non-product class")
        if source == "low_confidence" and not crop_content:
            raise ReviewError("product crop required")
        if content_type not in _ALLOWED_TYPES:
            raise ReviewError(f"Unsupported content type: {content_type}")
        if len(content) > _MAX_IMAGE_BYTES:
            raise ReviewError("Image exceeds 12MB limit")

        ext = _EXT_BY_TYPE[content_type]
        stem = uuid.uuid4()
        key = f"review/{organization_id}/{stem}.{ext}"
        try:
            await self._storage.put(key, content, content_type=content_type)
        except ObjectStorageError as exc:
            raise ReviewError(f"Storage error: {exc}") from exc

        # Crop luu canh khung hinh, cung stem de doi chieu bang mat khi can.
        # Loi luu crop KHONG danh hong ca ban ghi: khung hinh (co khung do)
        # van du cho nguoi duyet lam viec, chi mat phan anh hoc.
        crop_key: str | None = None
        if crop_content:
            try:
                crop_key = f"review/{organization_id}/{stem}_crop.{ext}"
                await self._storage.put(
                    crop_key, crop_content, content_type=content_type
                )
            except ObjectStorageError:
                crop_key = None

        candidate = ReviewCandidate(
            organization_id=organization_id,
            camera_id=camera_id,
            storage_key=key,
            crop_key=crop_key,
            bbox=bbox,
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

        # Uu tien CROP lam du lieu huan luyen. storage_key gio la khung hinh
        # co khung do ve chong len — dua no vao tap huan luyen thi classifier
        # se hoc ca ke hang, nen nha va chinh cai khung do do. Crop moi la
        # "mot anh = mot san pham" dung dinh dang ImageFolder can. Fallback
        # ve khung hinh cho ban ghi cu chua co crop (du lieu truoc nang cap).
        training_key = candidate.crop_key or candidate.storage_key
        image = TrainingImage(
            organization_id=organization_id,
            product_id=confirmed_product_id,
            storage_key=training_key,
            # Recorded at capture time — the object store has no cheap
            # size lookup in this codebase's wrapper, and re-downloading
            # the frame just to measure it would be wasteful.
            image_size_bytes=candidate.image_size_bytes or 0,
            image_format=training_key.rsplit(".", 1)[-1][:16],
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

    async def discard_non_product_pending(
        self,
        *,
        organization_id: uuid.UUID,
        reviewed_by: uuid.UUID | None,
    ) -> int:
        """Reject pending furniture/empty-counter captures in one pass.

        These were never trainable SKUs; bulk-reject is safe because it
        does not promote any model guess into training data.
        """
        now = datetime.now(timezone.utc)
        result = await self._session.execute(
            update(ReviewCandidate)
            .where(
                ReviewCandidate.organization_id == organization_id,
                ReviewCandidate.status == "pending",
                ReviewCandidate.is_deleted.is_(False),
                func.lower(ReviewCandidate.predicted_class).in_(
                    list(_NON_PRODUCT_CLASSES)
                ),
            )
            .values(
                status="rejected",
                reviewed_by=reviewed_by,
                reviewed_at=now,
                review_note="auto-discard: empty counter / furniture class",
            )
        )
        await self._session.commit()
        return int(result.rowcount or 0)

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
