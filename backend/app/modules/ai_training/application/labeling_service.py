"""Application service for multi-object bbox labeling."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import datetime, timezone
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
_TYPE_BY_EXT = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MIN_LABELED_IMAGES = 10
_MIN_BOXES_PER_CLASS = 5
_MIN_CROP_NORM = 0.02
_MIN_CROP_PX = 16


def _normalize_rect(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float, float]:
    ax, bx = sorted((x1, x2))
    ay, by = sorted((y1, y2))
    return ax, ay, bx, by


def _transform_box_after_crop(
    box: LabelBox,
    *,
    img_w: int,
    img_h: int,
    crop_left: int,
    crop_top: int,
    crop_w: int,
    crop_h: int,
) -> tuple[float, float, float, float] | None:
    """Map a YOLO box through a pixel crop; return new normalized coords or None if clipped away."""
    bx1 = (box.cx - box.w / 2) * img_w
    by1 = (box.cy - box.h / 2) * img_h
    bx2 = (box.cx + box.w / 2) * img_w
    by2 = (box.cy + box.h / 2) * img_h
    ix1 = max(bx1, float(crop_left))
    iy1 = max(by1, float(crop_top))
    ix2 = min(bx2, float(crop_left + crop_w))
    iy2 = min(by2, float(crop_top + crop_h))
    if ix2 - ix1 < 2 or iy2 - iy1 < 2:
        return None
    cx = ((ix1 + ix2) / 2 - crop_left) / crop_w
    cy = ((iy1 + iy2) / 2 - crop_top) / crop_h
    w = (ix2 - ix1) / crop_w
    h = (iy2 - iy1) / crop_h
    return (
        max(0.0, min(1.0, cx)),
        max(0.0, min(1.0, cy)),
        max(1e-6, min(1.0, w)),
        max(1e-6, min(1.0, h)),
    )


def _transform_polygon_after_crop(
    polygon: list | None,
    *,
    img_w: int,
    img_h: int,
    crop_left: int,
    crop_top: int,
    crop_w: int,
    crop_h: int,
) -> list[dict[str, float]] | None:
    if not polygon or len(polygon) < 3:
        return None
    out: list[dict[str, float]] = []
    for pt in polygon:
        px = float(pt["x"]) * img_w
        py = float(pt["y"]) * img_h
        nx = (px - crop_left) / crop_w
        ny = (py - crop_top) / crop_h
        out.append(
            {
                "x": max(0.0, min(1.0, nx)),
                "y": max(0.0, min(1.0, ny)),
            }
        )
    return out if len(out) >= 3 else None


def _polygon_to_db(polygon: list | None) -> list[dict[str, float]] | None:
    if not polygon or len(polygon) < 3:
        return None
    return [{"x": float(p["x"]), "y": float(p["y"])} for p in polygon]


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
        cropped: bool | None = None,
    ) -> tuple[list[tuple[LabelImage, int]], int, int, int, int]:
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
        if cropped is True:
            stmt = stmt.where(LabelImage.cropped_at.is_not(None))
        elif cropped is False:
            stmt = stmt.where(LabelImage.cropped_at.is_(None))
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
        pending_crop = int(
            (
                await self._session.execute(
                    select(func.count(LabelImage.id)).where(
                        LabelImage.organization_id == organization_id,
                        LabelImage.deleted_at.is_(None),
                        LabelImage.cropped_at.is_(None),
                    )
                )
            ).scalar()
            or 0
        )
        return rows, total, labeled_count, pending_count, pending_crop

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
        if image.cropped_at is None:
            raise TrainingError("Cần cắt ảnh (hoặc bỏ qua cắt) trước khi gán nhãn bbox")

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
                polygon=_polygon_to_db(b.get("polygon")),
            )
            self._session.add(row)
            created.append(row)
        await self._session.commit()
        for row in created:
            await self._session.refresh(row)
        return created

    async def crop_image(
        self,
        *,
        organization_id: uuid.UUID,
        image_id: uuid.UUID,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> tuple[LabelImage, list[tuple[LabelBox, Product]]]:
        """Crop the stored scene image in-place and remap existing bbox labels."""
        image, box_rows = await self.get_image(
            organization_id=organization_id,
            image_id=image_id,
        )
        nx1, ny1, nx2, ny2 = _normalize_rect(x1, y1, x2, y2)
        if nx2 - nx1 < _MIN_CROP_NORM or ny2 - ny1 < _MIN_CROP_NORM:
            raise TrainingError("Vùng cắt quá nhỏ")

        try:
            raw = await self._storage.get_bytes(image.storage_key)
        except ObjectStorageError as exc:
            raise TrainingError("Không đọc được ảnh gốc") from exc

        try:
            from PIL import Image

            img = Image.open(io.BytesIO(raw))
        except ImportError as exc:
            raise TrainingError(
                "Thiếu Pillow trên backend — chạy: pip install Pillow==10.4.0"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise TrainingError("Ảnh không hợp lệ") from exc

        img_w, img_h = img.size
        left = int(round(nx1 * img_w))
        top = int(round(ny1 * img_h))
        right = int(round(nx2 * img_w))
        bottom = int(round(ny2 * img_h))
        left = max(0, min(left, img_w - 1))
        top = max(0, min(top, img_h - 1))
        right = max(left + 1, min(right, img_w))
        bottom = max(top + 1, min(bottom, img_h))
        crop_w = right - left
        crop_h = bottom - top
        if crop_w < _MIN_CROP_PX or crop_h < _MIN_CROP_PX:
            raise TrainingError("Vùng cắt quá nhỏ")

        cropped = img.crop((left, top, right, bottom))
        ext = (image.image_format or "jpg").lower()
        pil_fmt = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}.get(
            ext, "JPEG"
        )
        buf = io.BytesIO()
        save_kwargs: dict = {}
        if pil_fmt == "JPEG":
            if cropped.mode not in ("RGB", "L"):
                cropped = cropped.convert("RGB")
            save_kwargs["quality"] = 92
        elif pil_fmt == "WEBP":
            save_kwargs["quality"] = 92
        cropped.save(buf, format=pil_fmt, **save_kwargs)
        content = buf.getvalue()
        if len(content) > _MAX_IMAGE_BYTES:
            raise TrainingError("Ảnh sau cắt vượt giới hạn kích thước")

        content_type = _TYPE_BY_EXT.get(ext, "image/jpeg")
        try:
            await self._storage.put(image.storage_key, content, content_type=content_type)
        except ObjectStorageError as exc:
            raise TrainingError("Không lưu được ảnh đã cắt") from exc

        image.image_width = crop_w
        image.image_height = crop_h
        image.image_size_bytes = len(content)
        image.cropped_at = datetime.now(timezone.utc)

        kept: list[tuple[LabelBox, Product]] = []
        for box, product in box_rows:
            mapped = _transform_box_after_crop(
                box,
                img_w=img_w,
                img_h=img_h,
                crop_left=left,
                crop_top=top,
                crop_w=crop_w,
                crop_h=crop_h,
            )
            if mapped is None:
                await self._session.delete(box)
                continue
            box.cx, box.cy, box.w, box.h = mapped
            box.polygon = _transform_polygon_after_crop(
                box.polygon,
                img_w=img_w,
                img_h=img_h,
                crop_left=left,
                crop_top=top,
                crop_w=crop_w,
                crop_h=crop_h,
            )
            kept.append((box, product))

        await self._session.commit()
        await self._session.refresh(image)
        return image, kept

    async def mark_cropped(
        self, *, organization_id: uuid.UUID, image_id: uuid.UUID
    ) -> LabelImage:
        """Mark image as cropped without changing pixels (already tight frame)."""
        image = await self._session.get(LabelImage, image_id)
        if image is None or image.organization_id != organization_id:
            raise TrainingError("Image not found")
        if image.cropped_at is None:
            image.cropped_at = datetime.now(timezone.utc)
            await self._session.commit()
            await self._session.refresh(image)
        return image

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
        pending_crop = int(
            (
                await self._session.execute(
                    select(func.count(LabelImage.id)).where(
                        LabelImage.organization_id == organization_id,
                        LabelImage.deleted_at.is_(None),
                        LabelImage.cropped_at.is_(None),
                    )
                )
            ).scalar()
            or 0
        )
        ready, msg = await self._training_readiness(
            labeled_images=labeled_images,
            distinct_skus=distinct_skus,
            pending_crop=pending_crop,
            organization_id=organization_id,
        )
        return {
            "total_images": total_images,
            "labeled_images": labeled_images,
            "pending_images": max(0, total_images - labeled_images),
            "pending_crop": pending_crop,
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
        pending_crop: int,
        organization_id: uuid.UUID,
    ) -> tuple[bool, str | None]:
        if pending_crop > 0:
            return False, f"Còn {pending_crop} ảnh chưa cắt — cắt hoặc bỏ qua cắt trước khi train"
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
                LabelImage.cropped_at.is_not(None),
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
