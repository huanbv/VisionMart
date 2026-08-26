"""Application service for multi-object bbox labeling."""

from __future__ import annotations

import logging
import uuid
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_training.application.service import TrainingError, _slug
from app.modules.ai_training.infrastructure.models import LabelBox, LabelImage, TrainingJob
from app.modules.catalog.infrastructure.models import Product
from app.services.ai_engine_client import AIEngineClient, AIEngineError
from app.services.object_storage import MinioStorage, ObjectStorageError

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EXT_BY_TYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_EXT_BY_NAME = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "webp": "webp"}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MIN_LABELED_IMAGES = 10
_MIN_BOXES_PER_CLASS = 5


class LabelingService:
    def __init__(
        self,
        session: AsyncSession,
        storage: MinioStorage,
        engine: AIEngineClient,
    ) -> None:
        self._session = session
        self._storage = storage
        self._engine = engine

    async def presign(self, key: str) -> str | None:
        try:
            return await self._storage.presigned_get(key)
        except ObjectStorageError:
            logger.warning("presign failed for %s", key)
            return None

    async def upload_images(
        self,
        *,
        organization_id: uuid.UUID,
        files: list[tuple[str, bytes, str]],
    ) -> tuple[list[LabelImage], int]:
        """Upload many scene images. Returns (created rows, failed count)."""
        created: list[LabelImage] = []
        failed = 0
        for filename, content, content_type in files:
            ext = _EXT_BY_TYPE.get(content_type)
            if ext is None and filename:
                ext = _EXT_BY_NAME.get(filename.rsplit(".", 1)[-1].lower())
            if ext is None:
                failed += 1
                continue
            if len(content) > _MAX_IMAGE_BYTES:
                failed += 1
                continue
            put_type = content_type if content_type in _ALLOWED_TYPES else f"image/{ext}"
            key = f"labeling/{organization_id}/{uuid.uuid4()}.{ext}"
            try:
                await self._storage.put(key, content, content_type=put_type)
            except ObjectStorageError:
                failed += 1
                continue
            row = LabelImage(
                organization_id=organization_id,
                storage_key=key,
                image_size_bytes=len(content),
                image_format=ext,
                original_filename=filename[:255] if filename else None,
            )
            self._session.add(row)
            created.append(row)
        if created:
            await self._session.commit()
            for row in created:
                await self._session.refresh(row)
        return created, failed

    async def list_images(
        self,
        *,
        organization_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        labeled: bool | None = None,
    ) -> tuple[list[tuple[LabelImage, int]], int, int, int]:
        total = int(
            (
                await self._session.execute(
                    select(func.count(LabelImage.id)).where(
                        LabelImage.organization_id == organization_id,
                        LabelImage.deleted_at.is_(None),
                    )
                )
            ).scalar()
            or 0
        )

        box_count_sq = (
            select(func.count(LabelBox.id))
            .where(
                LabelBox.label_image_id == LabelImage.id,
                LabelBox.deleted_at.is_(None),
            )
            .correlate(LabelImage)
            .scalar_subquery()
        )
        stmt = select(LabelImage, box_count_sq.label("box_count")).where(
            LabelImage.organization_id == organization_id,
            LabelImage.deleted_at.is_(None),
        )
        if labeled is True:
            stmt = stmt.where(box_count_sq > 0)
        elif labeled is False:
            stmt = stmt.where(box_count_sq == 0)
        stmt = stmt.order_by(LabelImage.created_at.asc()).offset(skip).limit(limit)
        rows = list((await self._session.execute(stmt)).all())

        labeled_count = int(
            (
                await self._session.execute(
                    select(func.count(func.distinct(LabelBox.label_image_id))).where(
                        LabelBox.deleted_at.is_(None),
                        LabelBox.label_image_id.in_(
                            select(LabelImage.id).where(
                                LabelImage.organization_id == organization_id,
                                LabelImage.deleted_at.is_(None),
                            )
                        ),
                    )
                )
            ).scalar()
            or 0
        )
        pending_count = max(0, total - labeled_count)
        return rows, total, labeled_count, pending_count

    async def get_image(
        self, *, organization_id: uuid.UUID, image_id: uuid.UUID
    ) -> tuple[LabelImage, list[tuple[LabelBox, Product]]]:
        image = await self._session.get(LabelImage, image_id)
        if image is None or image.organization_id != organization_id:
            raise TrainingError("Image not found")
        box_stmt = (
            select(LabelBox, Product)
            .join(Product, Product.id == LabelBox.product_id)
            .where(
                LabelBox.label_image_id == image_id,
                LabelBox.deleted_at.is_(None),
            )
        )
        box_rows = list((await self._session.execute(box_stmt)).all())
        return image, box_rows

    async def save_boxes(
        self,
        *,
        organization_id: uuid.UUID,
        image_id: uuid.UUID,
        boxes: list[dict],
    ) -> list[LabelBox]:
        image = await self._session.get(LabelImage, image_id)
        if image is None or image.organization_id != organization_id:
            raise TrainingError("Image not found")

        product_ids = {b["product_id"] for b in boxes}
        if product_ids:
            products = await self._load_products(organization_id, product_ids)
            if len(products) != len(product_ids):
                raise TrainingError("One or more products not found")

        existing = await self._session.execute(
            select(LabelBox).where(LabelBox.label_image_id == image_id)
        )
        for old in existing.scalars():
            await self._session.delete(old)

        created: list[LabelBox] = []
        for b in boxes:
            row = LabelBox(
                label_image_id=image_id,
                product_id=b["product_id"],
                cx=b["cx"],
                cy=b["cy"],
                w=b["w"],
                h=b["h"],
            )
            self._session.add(row)
            created.append(row)
        await self._session.commit()
        for row in created:
            await self._session.refresh(row)
        return created

    async def delete_image(
        self, *, organization_id: uuid.UUID, image_id: uuid.UUID
    ) -> None:
        image = await self._session.get(LabelImage, image_id)
        if image is None or image.organization_id != organization_id:
            raise TrainingError("Image not found")
        await self._storage.delete(image.storage_key)
        await self._session.delete(image)
        await self._session.commit()

    async def stats(self, *, organization_id: uuid.UUID) -> dict:
        total_images = int(
            (
                await self._session.execute(
                    select(func.count(LabelImage.id)).where(
                        LabelImage.organization_id == organization_id,
                        LabelImage.deleted_at.is_(None),
                    )
                )
            ).scalar()
            or 0
        )
        labeled_images = int(
            (
                await self._session.execute(
                    select(func.count(func.distinct(LabelBox.label_image_id))).where(
                        LabelBox.deleted_at.is_(None),
                        LabelBox.label_image_id.in_(
                            select(LabelImage.id).where(
                                LabelImage.organization_id == organization_id,
                                LabelImage.deleted_at.is_(None),
                            )
                        ),
                    )
                )
            ).scalar()
            or 0
        )
        total_boxes = int(
            (
                await self._session.execute(
                    select(func.count(LabelBox.id))
                    .join(LabelImage, LabelImage.id == LabelBox.label_image_id)
                    .where(
                        LabelImage.organization_id == organization_id,
                        LabelImage.deleted_at.is_(None),
                        LabelBox.deleted_at.is_(None),
                    )
                )
            ).scalar()
            or 0
        )
        distinct_skus = int(
            (
                await self._session.execute(
                    select(func.count(func.distinct(LabelBox.product_id)))
                    .join(LabelImage, LabelImage.id == LabelBox.label_image_id)
                    .where(
                        LabelImage.organization_id == organization_id,
                        LabelImage.deleted_at.is_(None),
                        LabelBox.deleted_at.is_(None),
                    )
                )
            ).scalar()
            or 0
        )
        ready, msg = await self._training_readiness(
            labeled_images=labeled_images,
            distinct_skus=distinct_skus,
            organization_id=organization_id,
        )
        return {
            "total_images": total_images,
            "labeled_images": labeled_images,
            "pending_images": max(0, total_images - labeled_images),
            "total_boxes": total_boxes,
            "distinct_skus": distinct_skus,
            "ready_for_training": ready,
            "training_message": msg,
        }

    async def _training_readiness(
        self,
        *,
        labeled_images: int,
        distinct_skus: int,
        organization_id: uuid.UUID,
    ) -> tuple[bool, str | None]:
        if distinct_skus < 2:
            return False, "Cần gán nhãn ít nhất 2 SKU khác nhau"
        if labeled_images < _MIN_LABELED_IMAGES:
            return False, f"Cần ít nhất {_MIN_LABELED_IMAGES} ảnh đã gán nhãn (hiện {labeled_images})"
        # Per-class box counts
        rows = await self._session.execute(
            select(Product.sku, func.count(LabelBox.id))
            .join(LabelBox, LabelBox.product_id == Product.id)
            .join(LabelImage, LabelImage.id == LabelBox.label_image_id)
            .where(
                LabelImage.organization_id == organization_id,
                LabelImage.deleted_at.is_(None),
                LabelBox.deleted_at.is_(None),
            )
            .group_by(Product.sku)
        )
        low = [(sku, cnt) for sku, cnt in rows.all() if int(cnt) < _MIN_BOXES_PER_CLASS]
        if low:
            parts = ", ".join(f"{sku} ({cnt})" for sku, cnt in low[:5])
            return False, f"Mỗi SKU cần ≥{_MIN_BOXES_PER_CLASS} bbox — thiếu: {parts}"
        return True, None

    async def create_labeled_job(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        branch_id: uuid.UUID | None,
        epochs: int,
        image_size: int,
    ) -> TrainingJob:
        stat = await self.stats(organization_id=organization_id)
        if not stat["ready_for_training"]:
            raise TrainingError(stat["training_message"] or "Chưa đủ dữ liệu gán nhãn")

        stmt = (
            select(LabelImage)
            .join(LabelBox, LabelBox.label_image_id == LabelImage.id)
            .where(
                LabelImage.organization_id == organization_id,
                LabelImage.deleted_at.is_(None),
                LabelBox.deleted_at.is_(None),
            )
            .distinct()
        )
        images = list((await self._session.execute(stmt)).scalars().all())
        if not images:
            raise TrainingError("Không có ảnh đã gán nhãn")

        image_ids = [img.id for img in images]
        box_stmt = (
            select(LabelBox, Product)
            .join(Product, Product.id == LabelBox.product_id)
            .where(
                LabelBox.label_image_id.in_(image_ids),
                LabelBox.deleted_at.is_(None),
            )
        )
        box_rows = list((await self._session.execute(box_stmt)).all())
        boxes_by_image: dict[uuid.UUID, list[tuple[LabelBox, Product]]] = {}
        for box, product in box_rows:
            boxes_by_image.setdefault(box.label_image_id, []).append((box, product))

        class_to_sku: dict[str, str] = {}
        product_by_class: dict[str, str] = {}
        labeled_dataset: list[dict] = []

        for img in images:
            labels = []
            for box, product in boxes_by_image.get(img.id, []):
                class_name = _slug(product.sku)
                class_to_sku[class_name] = product.sku
                product_by_class[class_name] = str(product.id)
                labels.append(
                    {
                        "class_name": class_name,
                        "cx": box.cx,
                        "cy": box.cy,
                        "w": box.w,
                        "h": box.h,
                    }
                )
            if labels:
                labeled_dataset.append(
                    {"storage_key": img.storage_key, "labels": labels}
                )

        job = TrainingJob(
            organization_id=organization_id,
            branch_id=branch_id,
            name=name,
            status="pending",
            epochs=epochs,
            image_size=image_size,
            class_map={
                "mode": "labeled_scenes",
                "classes": class_to_sku,
                "product_by_class": product_by_class,
                "labeled_image_count": len(labeled_dataset),
            },
        )
        self._session.add(job)
        await self._session.commit()
        await self._session.refresh(job)

        try:
            await self._engine.start_training(
                job_id=str(job.id),
                organization_id=str(organization_id),
                branch_id=str(branch_id) if branch_id else None,
                class_map={},
                class_to_sku=class_to_sku,
                epochs=epochs,
                image_size=image_size,
                labeled_dataset=labeled_dataset,
            )
            job.status = "running"
        except AIEngineError as exc:
            job.status = "failed"
            job.error_message = f"ai-engine unreachable: {exc}"
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def _load_products(
        self, organization_id: uuid.UUID, product_ids: Iterable[uuid.UUID]
    ) -> list[Product]:
        stmt = select(Product).where(
            Product.organization_id == organization_id,
            Product.id.in_(list(product_ids)),
            Product.deleted_at.is_(None),
        )
        return list((await self._session.execute(stmt)).scalars().all())
