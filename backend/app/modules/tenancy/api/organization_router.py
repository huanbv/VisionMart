"""Organization router: GET / PATCH the current tenant."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.tenancy.application.services import OrganizationService
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyOrganizationRepository,
)
from app.modules.tenancy.schemas.organization import (
    OrganizationResponse,
    OrganizationUpdate,
)

router = APIRouter(prefix="/organization", tags=["tenancy"])


def _service(session: AsyncSession) -> OrganizationService:
    return OrganizationService(SqlAlchemyOrganizationRepository(session))


@router.get("", response_model=OrganizationResponse)
async def get_current_organization(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OrganizationResponse:
    try:
        org = await _service(session).get(current.organization_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return OrganizationResponse.model_validate(org)


@router.patch("", response_model=OrganizationResponse)
async def update_current_organization(
    payload: OrganizationUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> OrganizationResponse:
    try:
        org = await _service(session).update(
            current.organization_id,
            name=payload.name,
            settings=payload.settings,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return OrganizationResponse.model_validate(org)
