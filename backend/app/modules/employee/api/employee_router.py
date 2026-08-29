"""Employee router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.employee.application.services import EmployeeService
from app.modules.employee.infrastructure.models import Employee
from app.modules.employee.infrastructure.repositories import (
    SqlAlchemyEmployeeRepository,
)
from app.modules.employee.schemas.employee import (
    EmployeeCreate,
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeTerminate,
    EmployeeUpdate,
    EmployeeUserRef,
)
from app.modules.identity.infrastructure.models import User
from app.modules.tenancy.infrastructure.models import Branch

router = APIRouter(prefix="/employees", tags=["employee"])


def _service(session: AsyncSession) -> EmployeeService:
    return EmployeeService(SqlAlchemyEmployeeRepository(session))


def _resolve(value: object, unset: bool) -> object:
    if unset:
        return None
    if value is None:
        from app.modules.employee.application.services import _UNSET

        return _UNSET
    return value


def _to_response(
    employee: Employee, branch: Branch, user: User | None
) -> EmployeeResponse:
    return EmployeeResponse(
        id=employee.id,
        organization_id=employee.organization_id,
        branch_id=employee.branch_id,
        branch_name=branch.name if branch else None,
        user_id=employee.user_id,
        user=EmployeeUserRef.model_validate(user) if user else None,
        code=employee.code,
        full_name=employee.full_name,
        position=employee.position,
        hired_at=employee.hired_at,
        terminated_at=employee.terminated_at,
        is_active=employee.is_active,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


@router.get("", response_model=EmployeeListResponse)
async def list_employees(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = None,
    branch_id: uuid.UUID | None = None,
    position: str | None = None,
    is_active: bool | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EmployeeListResponse:
    items, total = await _service(session).list(
        current.organization_id,
        skip=skip,
        limit=limit,
        search=search,
        branch_id=branch_id,
        position=position,
        is_active=is_active,
    )
    return EmployeeListResponse(
        items=[_to_response(e, b, u) for e, b, u in items],
        total=total,
        skip=skip,
        limit=limit,
    )


async def _load_response(
    service: EmployeeService,
    repo: SqlAlchemyEmployeeRepository,
    organization_id: uuid.UUID,
    employee_id: uuid.UUID,
) -> EmployeeResponse:
    e = await service.get(organization_id, employee_id)
    branch = await repo.get_branch_in_org(organization_id, e.branch_id)
    user = (
        await repo.get_user_in_org(organization_id, e.user_id)
        if e.user_id is not None
        else None
    )
    assert branch is not None
    return _to_response(e, branch, user)


@router.post("", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    payload: EmployeeCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResponse:
    repo = SqlAlchemyEmployeeRepository(session)
    service = EmployeeService(repo)
    try:
        e = await service.create(
            current.organization_id,
            code=payload.code,
            full_name=payload.full_name,
            branch_id=payload.branch_id,
            position=payload.position,
            user_id=payload.user_id,
            hired_at=payload.hired_at,
            is_active=payload.is_active,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _load_response(service, repo, current.organization_id, e.id)


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResponse:
    repo = SqlAlchemyEmployeeRepository(session)
    service = EmployeeService(repo)
    try:
        return await _load_response(
            service, repo, current.organization_id, employee_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: uuid.UUID,
    payload: EmployeeUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResponse:
    repo = SqlAlchemyEmployeeRepository(session)
    service = EmployeeService(repo)
    try:
        await service.update(
            current.organization_id,
            employee_id,
            code=payload.code,
            full_name=payload.full_name,
            branch_id=payload.branch_id,
            position=_resolve(payload.position, payload.position_unset),
            user_id=_resolve(payload.user_id, payload.user_unset),
            hired_at=_resolve(payload.hired_at, payload.hired_at_unset),
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await _load_response(
        service, repo, current.organization_id, employee_id
    )


@router.post("/{employee_id}/terminate", response_model=EmployeeResponse)
async def terminate_employee(
    employee_id: uuid.UUID,
    payload: EmployeeTerminate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> EmployeeResponse:
    repo = SqlAlchemyEmployeeRepository(session)
    service = EmployeeService(repo)
    try:
        await service.terminate(
            current.organization_id,
            employee_id,
            terminated_at=payload.terminated_at,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await _load_response(
        service, repo, current.organization_id, employee_id
    )


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_employee(
    employee_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await _service(session).delete(current.organization_id, employee_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
