"""Inventory router: stock levels, adjustments, transfers."""

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
from app.modules.catalog.infrastructure.models import Product
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.inventory.application.services import InventoryService
from app.modules.inventory.infrastructure.models import Inventory, StockMovementType
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
    SqlAlchemyStockMovementRepository,
)
from app.modules.inventory.schemas.inventory import (
    AdjustRequest,
    InventoryListResponse,
    InventoryResponse,
    ReorderLevelUpdate,
    StockMovementListResponse,
    StockMovementResponse,
    TransferRequest,
)
from app.modules.tenancy.infrastructure.models import Branch
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _service(session: AsyncSession) -> InventoryService:
    return InventoryService(
        SqlAlchemyInventoryRepository(session),
        SqlAlchemyStockMovementRepository(session),
        SqlAlchemyProductRepository(session),
        SqlAlchemyBranchRepository(session),
    )


def _to_response(inv: Inventory, product: Product, branch: Branch) -> InventoryResponse:
    available = inv.quantity - inv.reserved_quantity
    low = inv.reorder_level > 0 and inv.quantity <= inv.reorder_level
    return InventoryResponse(
        id=inv.id,
        product_id=inv.product_id,
        product_sku=product.sku,
        product_name=product.name,
        branch_id=inv.branch_id,
        branch_name=branch.name,
        quantity=inv.quantity,
        reserved_quantity=inv.reserved_quantity,
        available_quantity=available,
        reorder_level=inv.reorder_level,
        low_stock=low,
        last_stock_check_at=inv.last_stock_check_at,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
    )


@router.get("", response_model=InventoryListResponse)
async def list_inventory(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = None,
    branch_id: uuid.UUID | None = None,
    low_stock: bool = False,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> InventoryListResponse:
    rows, total = await _service(session).list(
        current.organization_id,
        skip=skip,
        limit=limit,
        search=search,
        branch_id=branch_id,
        low_stock=low_stock,
    )
    return InventoryListResponse(
        items=[_to_response(inv, p, b) for inv, p, b in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{inventory_id}", response_model=InventoryResponse)
async def get_inventory(
    inventory_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> InventoryResponse:
    try:
        inv, product, branch = await _service(session).get(
            current.organization_id, inventory_id
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(inv, product, branch)


@router.post("/adjust", response_model=InventoryResponse)
async def adjust_inventory(
    payload: AdjustRequest,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> InventoryResponse:
    try:
        await _service(session).adjust(
            current.organization_id,
            product_id=payload.product_id,
            branch_id=payload.branch_id,
            delta=payload.delta,
            movement_type=payload.movement_type,
            reason=payload.reason,
            reference=payload.reference,
            performed_by=current.user_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    inventories = SqlAlchemyInventoryRepository(session)
    inv = await inventories.get_by_product_branch(
        current.organization_id, payload.product_id, payload.branch_id
    )
    assert inv is not None
    row = await inventories.get_by_id(current.organization_id, inv.id)
    assert row is not None
    return _to_response(*row)


@router.post("/transfer", response_model=list[InventoryResponse])
async def transfer_inventory(
    payload: TransferRequest,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> list[InventoryResponse]:
    try:
        await _service(session).transfer(
            current.organization_id,
            product_id=payload.product_id,
            from_branch_id=payload.from_branch_id,
            to_branch_id=payload.to_branch_id,
            quantity=payload.quantity,
            reason=payload.reason,
            reference=payload.reference,
            performed_by=current.user_id,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    inventories = SqlAlchemyInventoryRepository(session)
    src = await inventories.get_by_product_branch(
        current.organization_id, payload.product_id, payload.from_branch_id
    )
    dst = await inventories.get_by_product_branch(
        current.organization_id, payload.product_id, payload.to_branch_id
    )
    assert src is not None and dst is not None
    src_row = await inventories.get_by_id(current.organization_id, src.id)
    dst_row = await inventories.get_by_id(current.organization_id, dst.id)
    assert src_row is not None and dst_row is not None
    return [_to_response(*src_row), _to_response(*dst_row)]


@router.patch("/{inventory_id}", response_model=InventoryResponse)
async def update_reorder_level(
    inventory_id: uuid.UUID,
    payload: ReorderLevelUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> InventoryResponse:
    try:
        await _service(session).set_reorder_level(
            current.organization_id, inventory_id, payload.reorder_level
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    inventories = SqlAlchemyInventoryRepository(session)
    row = await inventories.get_by_id(current.organization_id, inventory_id)
    assert row is not None
    return _to_response(*row)


@router.get(
    "/{inventory_id}/movements", response_model=StockMovementListResponse
)
async def list_movements(
    inventory_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StockMovementListResponse:
    try:
        items, total = await _service(session).list_movements(
            current.organization_id, inventory_id, skip=skip, limit=limit
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return StockMovementListResponse(
        items=[StockMovementResponse.model_validate(m) for m in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/movements/export.csv")
async def export_movements_csv(
    branch_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    movement_type: StockMovementType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    max_rows: int = Query(10000, ge=1, le=100000),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    movements = SqlAlchemyStockMovementRepository(session)
    batch_size = 500

    async def _row_batches():
        offset = 0
        remaining = max_rows
        while remaining > 0:
            page_size = min(batch_size, remaining)
            rows = await movements.list_for_org(
                current.organization_id,
                skip=offset,
                limit=page_size,
                branch_id=branch_id,
                product_id=product_id,
                movement_type=movement_type,
                date_from=date_from,
                date_to=date_to,
            )
            if not rows:
                return
            for row in rows:
                yield row
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
                "created_at",
                "branch_code",
                "branch_name",
                "product_sku",
                "product_name",
                "movement_type",
                "delta",
                "quantity_after",
                "reason",
                "reference",
                "performed_by",
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        async for movement, product, branch in _row_batches():
            writer.writerow(
                [
                    str(movement.id),
                    movement.created_at.isoformat() if movement.created_at else "",
                    branch.code,
                    branch.name,
                    product.sku,
                    product.name,
                    movement.movement_type.value
                    if hasattr(movement.movement_type, "value")
                    else str(movement.movement_type),
                    movement.delta,
                    movement.quantity_after,
                    movement.reason or "",
                    movement.reference or "",
                    str(movement.performed_by) if movement.performed_by else "",
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"stock_movements_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        _generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
