"""Order router: cashier-style POS endpoints."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.inventory.application.services import InventoryService
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
    SqlAlchemyStockMovementRepository,
)
from app.modules.sales.application.services import (
    OrderLineInput,
    OrderService,
)
from app.modules.sales.infrastructure.models import Order, OrderStatus
from app.modules.sales.infrastructure.repositories import (
    SqlAlchemyOrderItemRepository,
    SqlAlchemyOrderRepository,
)
from app.modules.sales.schemas.order import (
    OrderCreate,
    OrderDetail,
    OrderItemResponse,
    OrderListResponse,
    OrderSummary,
)
from app.modules.tenancy.infrastructure.models import Branch
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)

router = APIRouter(prefix="/orders", tags=["sales"])


def _service(session: AsyncSession) -> OrderService:
    inventory = InventoryService(
        SqlAlchemyInventoryRepository(session),
        SqlAlchemyStockMovementRepository(session),
        SqlAlchemyProductRepository(session),
        SqlAlchemyBranchRepository(session),
    )
    return OrderService(
        SqlAlchemyOrderRepository(session),
        SqlAlchemyOrderItemRepository(session),
        SqlAlchemyProductRepository(session),
        SqlAlchemyBranchRepository(session),
        inventory,
    )


def _to_summary(order: Order, branch: Branch) -> OrderSummary:
    return OrderSummary(
        id=order.id,
        code=order.code,
        branch_id=order.branch_id,
        branch_name=branch.name,
        customer_id=order.customer_id,
        status=order.status,
        total_amount=order.total_amount,
        currency=order.currency,
        paid_at=order.paid_at,
        created_at=order.created_at,
    )


def _to_detail(order: Order) -> OrderDetail:
    return OrderDetail(
        id=order.id,
        code=order.code,
        organization_id=order.organization_id,
        branch_id=order.branch_id,
        customer_id=order.customer_id,
        employee_id=order.employee_id,
        cart_id=order.cart_id,
        status=order.status,
        total_amount=order.total_amount,
        currency=order.currency,
        paid_at=order.paid_at,
        notes=order.notes,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[OrderItemResponse.model_validate(i) for i in order.items],
    )


@router.get("", response_model=OrderListResponse)
async def list_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    branch_id: uuid.UUID | None = None,
    order_status: OrderStatus | None = Query(None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OrderListResponse:
    rows, total = await _service(session).list(
        current.organization_id,
        skip=skip,
        limit=limit,
        branch_id=branch_id,
        status=order_status,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    return OrderListResponse(
        items=[_to_summary(o, b) for o, b in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/export.csv")
async def export_orders_csv(
    branch_id: uuid.UUID | None = None,
    order_status: OrderStatus | None = Query(None, alias="status"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
    max_rows: int = Query(10000, ge=1, le=100000),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    service = _service(session)
    batch_size = 500

    async def _row_batches():
        offset = 0
        remaining = max_rows
        while remaining > 0:
            page_size = min(batch_size, remaining)
            rows, _ = await service.list(
                current.organization_id,
                skip=offset,
                limit=page_size,
                branch_id=branch_id,
                status=order_status,
                date_from=date_from,
                date_to=date_to,
                search=search,
            )
            if not rows:
                return
            for order, branch in rows:
                yield order, branch
            offset += len(rows)
            if len(rows) < page_size:
                return
            remaining -= len(rows)

    async def _generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "code",
                "created_at",
                "paid_at",
                "branch_code",
                "branch_name",
                "customer_id",
                "status",
                "currency",
                "total_amount",
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        async for order, branch in _row_batches():
            writer.writerow(
                [
                    str(order.id),
                    order.code,
                    order.created_at.isoformat() if order.created_at else "",
                    order.paid_at.isoformat() if order.paid_at else "",
                    branch.code,
                    branch.name,
                    str(order.customer_id) if order.customer_id else "",
                    order.status.value if hasattr(order.status, "value") else str(order.status),
                    order.currency,
                    str(order.total_amount),
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"orders_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        _generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{order_id}", response_model=OrderDetail)
async def get_order(
    order_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> OrderDetail:
    try:
        order = await _service(session).get(current.organization_id, order_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_detail(order)


@router.post("", response_model=OrderDetail, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> OrderDetail:
    lines = [
        OrderLineInput(
            product_id=l.product_id,
            quantity=l.quantity,
            unit_price=l.unit_price,
            discount_amount=l.discount_amount,
        )
        for l in payload.lines
    ]
    try:
        order = await _service(session).create_order(
            current.organization_id,
            branch_id=payload.branch_id,
            lines=lines,
            customer_id=payload.customer_id,
            notes=payload.notes,
            performed_by=current.user_id,
        )
        await session.commit()
    except NotFoundError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_detail(order)


@router.post("/{order_id}/cancel", response_model=OrderDetail)
async def cancel_order(
    order_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> OrderDetail:
    try:
        order = await _service(session).cancel_order(
            current.organization_id, order_id, performed_by=current.user_id
        )
        await session.commit()
    except NotFoundError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_detail(order)


@router.post("/bulk-cancel")
async def bulk_cancel_orders(
    payload: dict,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    order_ids = payload.get("order_ids", [])
    service = _service(session)
    count = 0
    errors = []
    for oid in order_ids:
        try:
            uid = uuid.UUID(str(oid))
            await service.cancel_order(current.organization_id, uid, performed_by=current.user_id)
            count += 1
        except Exception as e:
            errors.append(f"{oid}: {e}")
    await session.commit()
    return {"status": "ok", "cancelled": count, "errors": errors}
