"""REST router for shopping carts (manual + auto-checkout by AI)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.inventory.application.services import InventoryService
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
    SqlAlchemyStockMovementRepository,
)
from app.modules.sales.application.cart_service import CartService
from app.modules.sales.infrastructure.models import CartStatus, ShoppingCart
from app.modules.sales.infrastructure.repositories import (
    SqlAlchemyCartRepository,
    SqlAlchemyOrderItemRepository,
    SqlAlchemyOrderRepository,
)
from app.modules.sales.schemas.cart import (
    CartAddLineRequest,
    CartCheckoutResponse,
    CartCreateRequest,
    CartLine,
    CartListResponse,
    CartResponse,
)
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)

router = APIRouter(prefix="/carts", tags=["sales"])


def build_cart_service(session: AsyncSession) -> CartService:
    inventory_service = InventoryService(
        SqlAlchemyInventoryRepository(session),
        SqlAlchemyStockMovementRepository(session),
        SqlAlchemyProductRepository(session),
        SqlAlchemyBranchRepository(session),
    )
    return CartService(
        carts=SqlAlchemyCartRepository(session),
        inventories=SqlAlchemyInventoryRepository(session),
        inventory_service=inventory_service,
        products=SqlAlchemyProductRepository(session),
        branches=SqlAlchemyBranchRepository(session),
        orders=SqlAlchemyOrderRepository(session),
        order_items=SqlAlchemyOrderItemRepository(session),
    )


def _cart_to_response(cart: ShoppingCart) -> CartResponse:
    lines: list[CartLine] = []
    for raw in cart.items or []:
        lines.append(CartLine.model_validate(raw))
    return CartResponse(
        id=cart.id,
        organization_id=cart.organization_id,
        branch_id=cart.branch_id,
        customer_id=cart.customer_id,
        session_id=cart.session_id,
        status=cart.status,
        source=cart.source,
        total_amount=cart.total_amount,
        currency=cart.currency,
        lines=lines,
        expires_at=cart.expires_at,
        converted_at=cart.converted_at,
        created_at=cart.created_at,
        updated_at=cart.updated_at,
    )


@router.get("", response_model=CartListResponse)
async def list_carts(
    branch_id: uuid.UUID | None = None,
    cart_status: CartStatus | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartListResponse:
    rows, total = await build_cart_service(session).list(
        current.organization_id,
        branch_id=branch_id,
        status=cart_status,
        skip=skip,
        limit=limit,
    )
    return CartListResponse(
        items=[_cart_to_response(c) for c in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=CartResponse, status_code=status.HTTP_201_CREATED)
async def create_cart(
    payload: CartCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).create(
            current.organization_id,
            branch_id=payload.branch_id,
            customer_id=payload.customer_id,
            session_id=payload.session_id,
            source=payload.source,
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return _cart_to_response(cart)


@router.get("/{cart_id}", response_model=CartResponse)
async def get_cart(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).get(current.organization_id, cart_id)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return _cart_to_response(cart)


@router.post("/{cart_id}/lines", response_model=CartResponse)
async def add_cart_line(
    cart_id: uuid.UUID,
    payload: CartAddLineRequest,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).add_line(
            current.organization_id,
            cart_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            unit_price=payload.unit_price,
            added_via=payload.added_via,
            source_event_id=payload.source_event_id,
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except (ValidationError, ConflictError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _cart_to_response(cart)


@router.delete("/{cart_id}/lines/{line_id}", response_model=CartResponse)
async def remove_cart_line(
    cart_id: uuid.UUID,
    line_id: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).remove_line(
            current.organization_id, cart_id, line_id
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ConflictError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _cart_to_response(cart)


@router.post("/{cart_id}/checkout", response_model=CartCheckoutResponse)
async def checkout_cart(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartCheckoutResponse:
    try:
        cart, order = await build_cart_service(session).checkout(
            current.organization_id, cart_id, performed_by=current.user_id
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except (ValidationError, ConflictError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return CartCheckoutResponse(
        cart_id=cart.id,
        order_id=order.id,
        order_code=order.code,
        total_amount=order.total_amount,
        currency=order.currency,
    )


@router.post("/{cart_id}/abandon", response_model=CartResponse)
async def abandon_cart(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).abandon(
            current.organization_id, cart_id
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ConflictError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _cart_to_response(cart)
