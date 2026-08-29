"""Reports admin router (super_admin / org_admin) with JSON or CSV output."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Iterable, Sequence

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import CurrentUser, require_roles
from app.modules.reports.application.reports_service import ReportsService
from app.modules.reports.schemas.reports import (
    InventoryValuationRow,
    SalesByBranchRow,
    SalesByDayRow,
    TopCustomerRow,
    TopProductRow,
)

router = APIRouter(prefix="/reports", tags=["reports"])

_ADMIN = require_roles("super_admin", "org_admin")


def _csv_response(filename: str, header: Sequence[str], rows: Iterable[Sequence]) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _service(session: AsyncSession) -> ReportsService:
    return ReportsService(session)


@router.get("/sales/by-day")
async def sales_by_day(
    date_from: datetime,
    date_to: datetime,
    branch_id: uuid.UUID | None = None,
    format: str = Query("json", pattern="^(json|csv)$"),
    current: CurrentUser = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
):
    rows = await _service(session).sales_by_day(
        current.organization_id,
        date_from=date_from,
        date_to=date_to,
        branch_id=branch_id,
    )
    if format == "csv":
        return _csv_response(
            "sales-by-day.csv",
            ["day", "orders", "revenue"],
            [(d.isoformat(), o, str(r)) for d, o, r in rows],
        )
    return [
        SalesByDayRow(day=d, orders=o, revenue=r) for d, o, r in rows
    ]


@router.get("/sales/by-branch")
async def sales_by_branch(
    date_from: datetime,
    date_to: datetime,
    format: str = Query("json", pattern="^(json|csv)$"),
    current: CurrentUser = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
):
    rows = await _service(session).sales_by_branch(
        current.organization_id, date_from=date_from, date_to=date_to
    )
    if format == "csv":
        return _csv_response(
            "sales-by-branch.csv",
            ["branch_id", "branch_name", "orders", "revenue"],
            [(str(bid), name, o, str(r)) for bid, name, o, r in rows],
        )
    return [
        SalesByBranchRow(branch_id=bid, branch_name=name, orders=o, revenue=r)
        for bid, name, o, r in rows
    ]


@router.get("/sales/top-products")
async def sales_top_products(
    date_from: datetime,
    date_to: datetime,
    limit: int = Query(50, ge=1, le=500),
    branch_id: uuid.UUID | None = None,
    format: str = Query("json", pattern="^(json|csv)$"),
    current: CurrentUser = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
):
    rows = await _service(session).top_products(
        current.organization_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        branch_id=branch_id,
    )
    if format == "csv":
        return _csv_response(
            "top-products.csv",
            ["product_id", "sku", "name", "quantity", "revenue"],
            [
                (str(pid), sku, name, q, str(rev))
                for pid, sku, name, q, rev in rows
            ],
        )
    return [
        TopProductRow(
            product_id=pid, sku=sku, name=name, quantity=q, revenue=rev
        )
        for pid, sku, name, q, rev in rows
    ]


@router.get("/inventory/valuation")
async def inventory_valuation(
    branch_id: uuid.UUID | None = None,
    format: str = Query("json", pattern="^(json|csv)$"),
    current: CurrentUser = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
):
    rows = await _service(session).inventory_valuation(
        current.organization_id, branch_id=branch_id
    )
    if format == "csv":
        return _csv_response(
            "inventory-valuation.csv",
            ["sku", "product_name", "branch_name", "quantity", "unit_price", "total_value"],
            [
                (sku, pname, bname, q, str(up), str(tv))
                for sku, pname, bname, q, up, tv in rows
            ],
        )
    return [
        InventoryValuationRow(
            sku=sku,
            product_name=pname,
            branch_name=bname,
            quantity=q,
            unit_price=up,
            total_value=tv,
        )
        for sku, pname, bname, q, up, tv in rows
    ]


@router.get("/customers/top")
async def customers_top(
    date_from: datetime,
    date_to: datetime,
    limit: int = Query(50, ge=1, le=500),
    format: str = Query("json", pattern="^(json|csv)$"),
    current: CurrentUser = Depends(_ADMIN),
    session: AsyncSession = Depends(get_session),
):
    rows = await _service(session).top_customers(
        current.organization_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    if format == "csv":
        return _csv_response(
            "top-customers.csv",
            ["customer_id", "full_name", "phone", "orders", "revenue"],
            [
                (str(cid), name or "", phone or "", o, str(rev))
                for cid, name, phone, o, rev in rows
            ],
        )
    return [
        TopCustomerRow(
            customer_id=cid,
            full_name=name,
            phone=phone,
            orders=o,
            revenue=rev,
        )
        for cid, name, phone, o, rev in rows
    ]
