"""Application services for the Camera bounded context."""

from __future__ import annotations

import uuid

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.camera.infrastructure.models import Camera
from app.modules.camera.infrastructure.repositories import (
    SqlAlchemyCameraRepository,
)
from app.modules.tenancy.infrastructure.models import Branch


_UNSET: object = object()


class CameraService:
    def __init__(self, repository: SqlAlchemyCameraRepository) -> None:
        self._repo = repository

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
        search: str | None,
        branch_id: uuid.UUID | None,
        is_active: bool | None,
        is_online: bool | None,
    ) -> tuple[list[tuple[Camera, Branch]], int]:
        return await self._repo.list_for_org(
            organization_id,
            skip=skip,
            limit=limit,
            search=search,
            branch_id=branch_id,
            is_active=is_active,
            is_online=is_online,
        )

    async def get(
        self, organization_id: uuid.UUID, camera_id: uuid.UUID
    ) -> Camera:
        c = await self._repo.get_by_id(organization_id, camera_id)
        if c is None:
            raise NotFoundError("Camera not found")
        return c

    async def stats(self, organization_id: uuid.UUID) -> tuple[int, int, int]:
        return await self._repo.stats(organization_id)

    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        code: str,
        name: str,
        branch_id: uuid.UUID,
        stream_url: str,
        location: str | None,
        resolution: str | None,
        fps: int | None,
        config: dict | None,
        is_active: bool,
        auto_capture_enabled: bool = False,
    ) -> Camera:
        branch = await self._repo.get_branch_in_org(organization_id, branch_id)
        if branch is None:
            raise ValidationError("Branch does not belong to this organization")
        if await self._repo.code_exists(organization_id, code):
            raise ConflictError(f"Camera code '{code}' already exists")
        c = Camera(
            organization_id=organization_id,
            branch_id=branch_id,
            code=code,
            name=name,
            stream_url=stream_url,
            location=location,
            resolution=resolution,
            fps=fps,
            config=config,
            is_active=is_active,
            auto_capture_enabled=auto_capture_enabled,
        )
        return await self._repo.add(c)

    async def update(
        self,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID,
        *,
        code: str | None = None,
        name: str | None = None,
        branch_id: uuid.UUID | None = None,
        stream_url: str | None = None,
        location: object = _UNSET,
        resolution: object = _UNSET,
        fps: object = _UNSET,
        config: object = _UNSET,
        is_active: bool | None = None,
        auto_capture_enabled: bool | None = None,
    ) -> Camera:
        c = await self.get(organization_id, camera_id)
        if code is not None and code != c.code:
            if await self._repo.code_exists(
                organization_id, code, exclude_id=camera_id
            ):
                raise ConflictError(f"Camera code '{code}' already exists")
            c.code = code
        if name is not None:
            c.name = name
        if branch_id is not None and branch_id != c.branch_id:
            branch = await self._repo.get_branch_in_org(organization_id, branch_id)
            if branch is None:
                raise ValidationError("Branch does not belong to this organization")
            c.branch_id = branch_id
        if stream_url is not None:
            c.stream_url = stream_url
        if location is not _UNSET:
            c.location = location  # type: ignore[assignment]
        if resolution is not _UNSET:
            c.resolution = resolution  # type: ignore[assignment]
        if fps is not _UNSET:
            c.fps = fps  # type: ignore[assignment]
        if config is not _UNSET:
            c.config = config  # type: ignore[assignment]
        if is_active is not None:
            c.is_active = is_active
            if not is_active:
                c.is_online = False
                c.auto_capture_enabled = False
        if auto_capture_enabled is not None:
            c.auto_capture_enabled = auto_capture_enabled and c.is_active
        return await self._repo.save(c)

    async def heartbeat(
        self,
        organization_id: uuid.UUID,
        camera_id: uuid.UUID,
        *,
        online: bool,
    ) -> Camera:
        c = await self.get(organization_id, camera_id)
        return await self._repo.mark_seen(c, online=online)

    async def delete(
        self, organization_id: uuid.UUID, camera_id: uuid.UUID
    ) -> None:
        c = await self.get(organization_id, camera_id)
        await self._repo.soft_delete(c)
