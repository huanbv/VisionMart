"""Application service for AI training uploads and jobs."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_training.application.regression_gate import GateResult, evaluate
from app.modules.ai_training.infrastructure.models import (
    TrainingImage,
    TrainingJob,
)
from app.modules.catalog.infrastructure.models import Product
from app.services.ai_engine_client import (
    AIEngineClient,
    AIEngineError,
    AIEngineNotFoundError,
)
from app.services.object_storage import MinioStorage, ObjectStorageError

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EXT_BY_TYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024


class TrainingError(RuntimeError):
    pass


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "class"


class TrainingService:
    def __init__(
        self,
        session: AsyncSession,
        storage: MinioStorage,
        engine: AIEngineClient,
    ) -> None:
        self._session = session
        self._storage = storage
        self._engine = engine

    async def upload_image(
        self,
        *,
        organization_id: uuid.UUID,
        product_id: uuid.UUID,
        content: bytes,
        content_type: str,
    ) -> TrainingImage:
        if content_type not in _ALLOWED_TYPES:
            raise TrainingError(f"Unsupported content type: {content_type}")
        if len(content) > _MAX_IMAGE_BYTES:
            raise TrainingError("Image exceeds 12MB limit")

        product = await self._session.get(Product, product_id)
        if product is None or product.organization_id != organization_id:
            raise TrainingError("Product not found")

        ext = _EXT_BY_TYPE[content_type]
        key = (
            f"training/{organization_id}/{product_id}/{uuid.uuid4()}.{ext}"
        )
        try:
            await self._storage.put(key, content, content_type=content_type)
        except ObjectStorageError as exc:
            raise TrainingError(f"Storage error: {exc}") from exc

        image = TrainingImage(
            organization_id=organization_id,
            product_id=product_id,
            storage_key=key,
            image_size_bytes=len(content),
            image_format=ext,
        )
        self._session.add(image)
        await self._session.commit()
        await self._session.refresh(image)
        return image

    async def list_images(
        self,
        *,
        organization_id: uuid.UUID,
        product_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> tuple[list[TrainingImage], int]:
        stmt = select(TrainingImage).where(
            TrainingImage.organization_id == organization_id,
            TrainingImage.deleted_at.is_(None),
        )
        if product_id is not None:
            stmt = stmt.where(TrainingImage.product_id == product_id)
        stmt = stmt.order_by(TrainingImage.created_at.desc()).limit(limit)
        rows = list((await self._session.execute(stmt)).scalars().all())

        count_stmt = select(func.count(TrainingImage.id)).where(
            TrainingImage.organization_id == organization_id,
            TrainingImage.deleted_at.is_(None),
        )
        if product_id is not None:
            count_stmt = count_stmt.where(TrainingImage.product_id == product_id)
        total = int((await self._session.execute(count_stmt)).scalar() or 0)
        return rows, total

    async def delete_image(
        self, *, organization_id: uuid.UUID, image_id: uuid.UUID
    ) -> None:
        image = await self._session.get(TrainingImage, image_id)
        if image is None or image.organization_id != organization_id:
            raise TrainingError("Image not found")
        await self._storage.delete(image.storage_key)
        await self._session.delete(image)
        await self._session.commit()

    async def presign(self, key: str) -> str | None:
        try:
            return await self._storage.presigned_get(key)
        except ObjectStorageError:
            logger.warning("presign failed for %s", key)
            return None

    async def create_job(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        product_ids: list[uuid.UUID],
        branch_id: uuid.UUID | None,
        epochs: int,
        image_size: int,
    ) -> TrainingJob:
        products = await self._load_products(organization_id, product_ids)
        if len(products) < 2:
            raise TrainingError("Need at least 2 products (classes) to train")

        class_map: dict[str, list[str]] = {}
        product_class_names: dict[str, str] = {}
        class_to_sku: dict[str, str] = {}
        for product in products:
            class_name = _slug(product.sku)
            keys = await self._list_keys(organization_id, product.id)
            if len(keys) < 5:
                raise TrainingError(
                    f"Product {product.sku} needs >=5 images (has {len(keys)})"
                )
            class_map[class_name] = keys
            product_class_names[class_name] = str(product.id)
            class_to_sku[class_name] = product.sku

        job = TrainingJob(
            organization_id=organization_id,
            branch_id=branch_id,
            name=name,
            status="pending",
            epochs=epochs,
            image_size=image_size,
            class_map={
                "classes": class_map,
                "product_by_class": product_class_names,
                "class_to_sku": class_to_sku,
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
                class_map=class_map,
                class_to_sku=class_to_sku,
                epochs=epochs,
                image_size=image_size,
            )
            job.status = "running"
        except AIEngineError as exc:
            job.status = "failed"
            job.error_message = f"ai-engine unreachable: {exc}"
        await self._session.commit()
        await self._session.refresh(job)
        return job

    async def get_job(
        self, *, organization_id: uuid.UUID, job_id: uuid.UUID
    ) -> TrainingJob:
        job = await self._session.get(TrainingJob, job_id)
        if job is None or job.organization_id != organization_id:
            raise TrainingError("Job not found")

        if job.status in {"pending", "running"}:
            try:
                status = await self._engine.training_status(str(job_id))
                new_status = status.get("status")
                if new_status and new_status != job.status:
                    job.status = new_status
                if status.get("metrics"):
                    job.metrics = status["metrics"]
                if status.get("weight_key"):
                    job.weight_key = status["weight_key"]
                if status.get("error"):
                    job.error_message = status["error"]
                await self._session.commit()
                await self._session.refresh(job)
                # Gán sau commit/refresh một cách có chủ ý: đây là các
                # thuộc tính tạm, KHÔNG phải cột trong bảng. Tiến độ chỉ
                # có ý nghĩa khi job đang chạy và ai-engine mới là nguồn
                # sự thật; lưu vào DB sẽ tạo ra một bản sao lỗi thời mà
                # sau khi ai-engine restart thì không ai cập nhật nữa.
                job.progress = status.get("progress")
                job.current_epoch = status.get("current_epoch")
                job.total_epochs = status.get("total_epochs")
                job.started_at_ts = status.get("started_at")
                job.finished_at_ts = status.get("finished_at")
                job.stage = status.get("stage")
                job.images_total = status.get("images_total")
                job.images_done = status.get("images_done")
                job.class_counts = status.get("class_counts")
                job.train_count = status.get("train_count")
                job.val_count = status.get("val_count")
            except AIEngineNotFoundError:
                logger.warning(
                    "training job %s missing in ai-engine, marking failed",
                    job_id,
                )
                job.status = "failed"
                job.error_message = (
                    "AI Engine không còn giữ job này (có thể đã restart). "
                    "Vui lòng tạo job mới."
                )
                await self._session.commit()
                await self._session.refresh(job)
            except AIEngineError as exc:
                logger.warning("training status poll failed: %s", exc)
        return job

    async def list_jobs(
        self, *, organization_id: uuid.UUID, limit: int = 50
    ) -> tuple[list[TrainingJob], int]:
        stmt = (
            select(TrainingJob)
            .where(
                TrainingJob.organization_id == organization_id,
                TrainingJob.deleted_at.is_(None),
            )
            .order_by(TrainingJob.created_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        count = int(
            (
                await self._session.execute(
                    select(func.count(TrainingJob.id)).where(
                        TrainingJob.organization_id == organization_id,
                        TrainingJob.deleted_at.is_(None),
                    )
                )
            ).scalar()
            or 0
        )
        return rows, count

    async def _last_deployed_job(
        self, organization_id: uuid.UUID, branch_id: uuid.UUID | None
    ) -> TrainingJob | None:
        """Baseline for the regression gate: the weight currently live for
        this org/branch."""
        stmt = (
            select(TrainingJob)
            .where(
                TrainingJob.organization_id == organization_id,
                TrainingJob.deployed_at.is_not(None),
                TrainingJob.is_deleted.is_(False),
            )
            .order_by(TrainingJob.deployed_at.desc())
            .limit(1)
        )
        if branch_id is not None:
            stmt = stmt.where(TrainingJob.branch_id == branch_id)
        return await self._session.scalar(stmt)

    async def check_deploy(
        self, *, organization_id: uuid.UUID, job_id: uuid.UUID
    ) -> GateResult:
        """Run the regression gate without deploying — lets the UI warn
        before the operator commits."""
        job = await self._session.get(TrainingJob, job_id)
        if job is None or job.organization_id != organization_id:
            raise TrainingError("Job not found")
        baseline = await self._last_deployed_job(organization_id, job.branch_id)
        return evaluate(
            candidate_metrics=job.metrics,
            baseline_metrics=baseline.metrics if baseline else None,
        )

    async def deploy_job(
        self, *, organization_id: uuid.UUID, job_id: uuid.UUID, force: bool = False
    ) -> TrainingJob:
        job = await self._session.get(TrainingJob, job_id)
        if job is None or job.organization_id != organization_id:
            raise TrainingError("Job not found")
        if job.status != "succeeded" or not job.weight_key:
            raise TrainingError("Job is not ready for deploy")

        # Regression gate: a retrained model that scores worse than the one
        # already live would degrade detection silently, so it is blocked
        # unless the operator explicitly overrides.
        baseline = await self._last_deployed_job(organization_id, job.branch_id)
        gate = evaluate(
            candidate_metrics=job.metrics,
            baseline_metrics=baseline.metrics if baseline else None,
            force=force,
        )
        if not gate.allowed:
            raise TrainingError(gate.reason)

        try:
            await self._engine.deploy_weight(
                weight_key=job.weight_key,
                organization_id=str(organization_id),
                branch_id=str(job.branch_id) if job.branch_id else None,
            )
        except AIEngineError as exc:
            raise TrainingError(f"Deploy failed: {exc}") from exc

        # Recorded only after the engine accepted the weight, so a failed
        # deploy can't become the baseline for the next comparison.
        job.deployed_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(job)
        logger.info(
            "deployed job=%s org=%s gate=%s", job_id, organization_id, gate.reason
        )
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

    async def _list_keys(
        self, organization_id: uuid.UUID, product_id: uuid.UUID
    ) -> list[str]:
        stmt = select(TrainingImage.storage_key).where(
            TrainingImage.organization_id == organization_id,
            TrainingImage.product_id == product_id,
            TrainingImage.deleted_at.is_(None),
        )
        return [row for row in (await self._session.execute(stmt)).scalars().all()]
