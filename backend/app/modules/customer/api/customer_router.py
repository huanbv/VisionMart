"""Customer router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.customer.application.services import CustomerService
from app.modules.customer.infrastructure.repositories import (
    SqlAlchemyCustomerRepository,
)
from app.modules.customer.schemas.customer import (
    CustomerCreate,
    CustomerListResponse,
    CustomerResponse,
    CustomerStats,
    CustomerUpdate,
)

router = APIRouter(prefix="/customers", tags=["customer"])


def _service(session: AsyncSession) -> CustomerService:
    return CustomerService(SqlAlchemyCustomerRepository(session))


def _resolve(value: object, unset: bool) -> object:
    if unset:
        return None
    if value is None:
        from app.modules.customer.application.services import _UNSET

        return _UNSET
    return value


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = None,
    branch_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CustomerListResponse:
    items, total = await _service(session).list(
        current.organization_id,
        skip=skip,
        limit=limit,
        search=search,
        branch_id=branch_id,
        is_active=is_active,
    )
    return CustomerListResponse(
        items=[CustomerResponse.model_validate(c) for c in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> CustomerResponse:
    try:
        c = await _service(session).create(
            current.organization_id,
            full_name=payload.full_name,
            email=payload.email,
            phone=payload.phone,
            branch_id=payload.branch_id,
            attributes=payload.attributes,
            is_active=payload.is_active,
        )
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CustomerResponse.model_validate(c)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CustomerResponse:
    try:
        c = await _service(session).get(current.organization_id, customer_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CustomerResponse.model_validate(c)


@router.get("/{customer_id}/stats", response_model=CustomerStats)
async def get_customer_stats(
    customer_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CustomerStats:
    try:
        count, total = await _service(session).stats(
            current.organization_id, customer_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return CustomerStats(
        customer_id=customer_id, order_count=count, total_spent=total
    )


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: uuid.UUID,
    payload: CustomerUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> CustomerResponse:
    try:
        c = await _service(session).update(
            current.organization_id,
            customer_id,
            full_name=_resolve(payload.full_name, payload.full_name_unset),
            email=_resolve(payload.email, payload.email_unset),
            phone=_resolve(payload.phone, payload.phone_unset),
            branch_id=_resolve(payload.branch_id, payload.branch_unset),
            attributes=_resolve(payload.attributes, payload.attributes_unset),
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CustomerResponse.model_validate(c)


@router.delete(
    "/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_customer(
    customer_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await _service(session).delete(current.organization_id, customer_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
