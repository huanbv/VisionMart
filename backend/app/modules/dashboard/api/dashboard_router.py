"""Dashboard router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user
from app.modules.dashboard.infrastructure.repository import (
    DashboardRepository,
    utc_days_ago,
    utc_start_of_day,
)
from app.modules.dashboard.schemas.dashboard import (
    CameraSummary,
    DashboardSummary,
    LowStockItem,
    LowStockResponse,
    RecentOrder,
    RecentOrdersResponse,
    SalesBucket,
    SalesTrendPoint,
    SalesTrendResponse,
    TopProduct,
    TopProductsResponse,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _repo(session: AsyncSession) -> DashboardRepository:
    return DashboardRepository(session)


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(
    branch_id: uuid.UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardSummary:
    repo = _repo(session)
    org = current.organization_id

    today_start = utc_start_of_day()
    week_start = utc_days_ago(6)
    month_start = utc_days_ago(29)

    today_n, today_v = await repo.sales_total(org, since=today_start, branch_id=branch_id)
    week_n, week_v = await repo.sales_total(org, since=week_start, branch_id=branch_id)
    month_n, month_v = await repo.sales_total(org, since=month_start, branch_id=branch_id)

    customers_total = await repo.customers_total(org)
    customers_new = await repo.customers_total(org, since=week_start)
    products_total = await repo.products_total(org)
    low_stock = await repo.low_stock_count(org, branch_id=branch_id)
    cam_total, cam_online, cam_active = await repo.cameras_summary(org)
    employees_active = await repo.employees_active(org)
    branches_count = await repo.branches_count(org)

    return DashboardSummary(
        today=SalesBucket(orders=today_n, revenue=today_v),
        last_7_days=SalesBucket(orders=week_n, revenue=week_v),
        last_30_days=SalesBucket(orders=month_n, revenue=month_v),
        customers_total=customers_total,
        customers_new_7d=customers_new,
        products_total=products_total,
        low_stock_count=low_stock,
        cameras=CameraSummary(
            total=cam_total, online=cam_online, active=cam_active
        ),
        employees_active=employees_active,
        branches_count=branches_count,
    )


@router.get("/sales-trend", response_model=SalesTrendResponse)
async def get_sales_trend(
    days: int = Query(14, ge=1, le=90),
    branch_id: uuid.UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SalesTrendResponse:
    since = utc_days_ago(days - 1)
    rows = await _repo(session).sales_trend(
        current.organization_id, since=since, branch_id=branch_id
    )
    return SalesTrendResponse(
        days=days,
        points=[
            SalesTrendPoint(date=d, orders=n, revenue=v) for d, n, v in rows
        ],
    )


@router.get("/top-products", response_model=TopProductsResponse)
async def get_top_products(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=50),
    branch_id: uuid.UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TopProductsResponse:
    since = utc_days_ago(days - 1)
    rows = await _repo(session).top_products(
        current.organization_id,
        since=since,
        limit=limit,
        branch_id=branch_id,
    )
    return TopProductsResponse(
        days=days,
        items=[
            TopProduct(
                product_id=pid, sku=sku, name=name, quantity=q, revenue=r
            )
            for pid, sku, name, q, r in rows
        ],
    )


@router.get("/low-stock", response_model=LowStockResponse)
async def get_low_stock(
    limit: int = Query(20, ge=1, le=200),
    branch_id: uuid.UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LowStockResponse:
    rows = await _repo(session).low_stock_items(
        current.organization_id, limit=limit, branch_id=branch_id
    )
    return LowStockResponse(
        items=[
            LowStockItem(
                inventory_id=iid,
                sku=sku,
                product_name=name,
                branch_name=bname,
                quantity=q,
                reserved_quantity=rsv,
                reorder_level=rl,
            )
            for iid, sku, name, bname, q, rsv, rl in rows
        ]
    )


@router.get("/recent-orders", response_model=RecentOrdersResponse)
async def get_recent_orders(
    limit: int = Query(10, ge=1, le=50),
    branch_id: uuid.UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecentOrdersResponse:
    rows = await _repo(session).recent_orders(
        current.organization_id, limit=limit, branch_id=branch_id
    )
    return RecentOrdersResponse(
        items=[
            RecentOrder(
                id=order.id,
                code=order.code,
                branch_name=branch.name,
                status=order.status.value,
                total_amount=order.total_amount,
                created_at=order.created_at,
            )
            for order, branch in rows
        ]
    )
