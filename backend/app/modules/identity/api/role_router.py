"""Role router (read-only for MVP)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user
from app.modules.identity.infrastructure.repositories import SqlAlchemyRoleRepository
from app.modules.identity.schemas.role import RoleResponse

router = APIRouter(prefix="/roles", tags=["identity"])


@router.get("", response_model=list[RoleResponse])
async def list_roles(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[RoleResponse]:
    repo = SqlAlchemyRoleRepository(session)
    roles = await repo.list_for_org(current.organization_id)
    return [RoleResponse.model_validate(r) for r in roles]
