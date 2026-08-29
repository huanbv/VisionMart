"""Public, unauthenticated endpoints for the customer-facing checkout
confirmation page.

A customer reaches these by scanning the QR code shown on the checkout-zone
screen (or a staff member reading it out for a walk-in without a phone —
see the staff-side confirm-checkout endpoint on cart_router.py instead).
The URL token itself (unguessable, `secrets.token_urlsafe`) is the only
"credential" here — there is no login, no account, matching this project's
anonymous-shopper design (no biometric/customer identity requirement).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.rate_limit import enforce as enforce_rate_limit
from app.database.session import get_session
from app.modules.sales.api.cart_router import build_checkout_service
from app.modules.sales.schemas.cart import (
    PublicBillLine,
    PublicBillResponse,
    PublicConfirmResponse,
)

router = APIRouter(prefix="/shop", tags=["shop"])


async def _enforce_shop_rate_limit(request: Request, settings: Settings) -> None:
    # Keyed by caller IP, same as /auth/* (see app/core/rate_limit.py). These
    # three endpoints need no login — the checkout token is the only
    # "credential" — so without this, anyone could script requests against
    # them at any rate: brute-forcing tokens, or just hammering the DB with
    # bill lookups/confirm/cancel calls.
    await enforce_rate_limit(
        request,
        bucket="shop:checkout",
        limit=settings.SHOP_CHECKOUT_RATE_LIMIT,
        window_seconds=settings.SHOP_CHECKOUT_RATE_WINDOW_SECONDS,
        settings=settings,
    )


def _bill_from_cart(cart, order=None) -> PublicBillResponse:
    lines = [
        PublicBillLine(
            product_name=li.get("product_name", ""),
            sku=li.get("sku", ""),
            quantity=int(li.get("quantity", 0)),
            unit_price=li.get("unit_price", "0"),
            subtotal=li.get("subtotal", "0"),
        )
        for li in (cart.items or [])
    ]
    return PublicBillResponse(
        status=cart.status,
        lines=lines,
        total_amount=cart.total_amount,
        currency=cart.currency,
        checkout_requested_at=cart.checkout_requested_at,
        expires_at=cart.expires_at,
        order_code=order.code if order else None,
        paid_at=order.paid_at if order else None,
    )


@router.get("/checkout/{token}", response_model=PublicBillResponse)
async def get_checkout_bill(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PublicBillResponse:
    await _enforce_shop_rate_limit(request, settings)
    service = build_checkout_service(session)
    try:
        cart = await service.get_bill_by_token(token)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))

    order = None
    if cart.status.value == "converted":
        order = await service.get_order_for_cart(cart.id)
    return _bill_from_cart(cart, order)


@router.post("/checkout/{token}/confirm", response_model=PublicConfirmResponse)
async def confirm_checkout(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PublicConfirmResponse:
    await _enforce_shop_rate_limit(request, settings)
    service = build_checkout_service(session)
    try:
        _cart, order = await service.confirm_checkout_by_token(token)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except (ValidationError, ConflictError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return PublicConfirmResponse(
        order_code=order.code,
        total_amount=order.total_amount,
        currency=order.currency,
        paid_at=order.paid_at,
    )


@router.post("/checkout/{token}/cancel", response_model=PublicBillResponse)
async def cancel_checkout(
    token: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PublicBillResponse:
    """Customer taps "Chưa xong, tiếp tục mua sắm" instead of confirming."""
    await _enforce_shop_rate_limit(request, settings)
    service = build_checkout_service(session)
    try:
        cart = await service.get_bill_by_token(token)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    try:
        cart = await service.cancel_pending_checkout(cart.organization_id, cart.id)
    except ConflictError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _bill_from_cart(cart)
