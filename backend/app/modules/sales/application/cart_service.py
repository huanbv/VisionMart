"""Application service for the Shopping Cart aggregate — shopping lifecycle
only (create, add/remove line, abandon).

Freeze/confirm/payment concerns live in `checkout_service.py`; translating
AI-emitted proposals into calls on this service lives in
`ai_cart_event_service.py`. This split keeps each class responsible for one
thing: this one never touches a payment gateway or an Order, and knows
nothing about AI event schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.config.settings import get_settings
from app.core.events import EventBus
from app.core.exceptions import NotFoundError
from app.modules.catalog.infrastructure.models import Product
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
)
from app.modules.sales.application import cart_lookup, inventory_reservation
from app.modules.sales.domain import events as sales_events
from app.modules.sales.infrastructure.models import (
    CartSource,
    CartStatus,
    ShoppingCart,
)
from app.modules.sales.infrastructure.repositories import SqlAlchemyCartRepository
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def compute_overall_confidence(lines: list[dict[str, Any]]) -> float:
    """Value-weighted average confidence across a cart's lines — a
    low-confidence detection on an expensive item should pull the overall
    score down more than the same uncertainty on a cheap one. Manually
    added lines (added_via != "ai") default to 1.0 (staff certainty).
    Returns 1.0 for an empty cart (nothing to be unsure about)."""
    if not lines:
        return 1.0
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")
    for li in lines:
        weight = Decimal(str(li.get("subtotal", "0")))
        confidence = Decimal(str(li.get("confidence", 1.0)))
        weighted_sum += weight * confidence
        total_weight += weight
    if total_weight == 0:
        # All-zero-value lines (shouldn't normally happen) — fall back to a
        # plain average so we don't divide by zero.
        avg = sum(Decimal(str(li.get("confidence", 1.0))) for li in lines) / len(lines)
        return float(avg)
    return float(weighted_sum / total_weight)


class CartService:
    def __init__(
        self,
        carts: SqlAlchemyCartRepository,
        inventories: SqlAlchemyInventoryRepository,
        products: SqlAlchemyProductRepository,
        branches: SqlAlchemyBranchRepository,
        event_bus: EventBus,
    ) -> None:
        self._carts = carts
        self._inventories = inventories
        self._products = products
        self._branches = branches
        self._events = event_bus
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        branch_id: uuid.UUID | None,
        status: CartStatus | None,
        skip: int,
        limit: int,
    ) -> tuple[list[ShoppingCart], int]:
        return await self._carts.list_for_org(
            organization_id,
            branch_id=branch_id,
            status=status,
            skip=skip,
            limit=limit,
        )

    async def get(self, organization_id: uuid.UUID, cart_id: uuid.UUID) -> ShoppingCart:
        return await cart_lookup.get_cart(self._carts, organization_id, cart_id)

    async def get_open_cart_for_session(
        self, organization_id: uuid.UUID, branch_id: uuid.UUID, session_id: str
    ) -> ShoppingCart | None:
        return await self._carts.get_open_for_session(
            organization_id, branch_id, session_id
        )

    def _expiry_minutes(self, source: CartSource) -> int:
        """TTL cart theo nguồn. Cart AI dùng cửa sổ ngắn hơn (15') để đơn
        chưa xác nhận không đọng lâu trên màn hình; cart thủ công giữ 30'."""
        if source == CartSource.AI_VISION:
            return self._settings.AI_CART_EXPIRATION_MINUTES
        return self._settings.CART_EXPIRATION_MINUTES

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    async def create(
        self,
        organization_id: uuid.UUID,
        *,
        branch_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        session_id: str | None,
        source: CartSource,
    ) -> ShoppingCart:
        branch = await self._branches.get_by_id(organization_id, branch_id)
        if branch is None:
            raise NotFoundError("Branch not found")

        if session_id:
            existing = await self._carts.get_open_for_session(
                organization_id, branch_id, session_id
            )
            if existing is not None:
                return existing

        expires_at = _now() + timedelta(minutes=self._expiry_minutes(source))
        cart = ShoppingCart(
            organization_id=organization_id,
            branch_id=branch_id,
            customer_id=customer_id,
            session_id=session_id,
            status=CartStatus.ACTIVE,
            source=source,
            items=[],
            total_amount=Decimal("0"),
            currency="VND",
            expires_at=expires_at,
        )
        cart = await self._carts.add(cart)
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._events.publish(sales_events.cart_created(cart))
        return cart

    async def add_line(
        self,
        organization_id: uuid.UUID,
        cart_id: uuid.UUID,
        *,
        product_id: uuid.UUID,
        quantity: int,
        unit_price: Decimal | None,
        added_via: str,
        source_event_id: str | None,
        global_track_id: str | None = None,
        confidence: float = 1.0,
    ) -> ShoppingCart:
        cart = await cart_lookup.require_active(self._carts, organization_id, cart_id)
        product = await self._products.get_by_id(organization_id, product_id)
        if product is None:
            raise NotFoundError("Product not found")

        await inventory_reservation.reserve(
            self._inventories, organization_id, cart.branch_id, product_id, quantity
        )

        lines = list(cart.items or [])
        price = unit_price if unit_price is not None else product.unit_price
        line = self._build_line(
            product,
            quantity=quantity,
            unit_price=Decimal(str(price)),
            added_via=added_via,
            source_event_id=source_event_id,
            global_track_id=global_track_id,
            confidence=confidence,
        )
        lines.append(line)
        cart.items = lines
        cart.total_amount = self._sum_total(lines)
        cart.expires_at = _now() + timedelta(minutes=self._expiry_minutes(cart.source))
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._events.publish(sales_events.cart_line_added(cart))
        return cart

    async def remove_line(
        self,
        organization_id: uuid.UUID,
        cart_id: uuid.UUID,
        line_id: str,
    ) -> ShoppingCart:
        cart = await cart_lookup.require_active(self._carts, organization_id, cart_id)
        lines = list(cart.items or [])
        target = next((li for li in lines if li.get("line_id") == line_id), None)
        if target is None:
            raise NotFoundError("Cart line not found")

        await inventory_reservation.release(
            self._inventories,
            organization_id,
            cart.branch_id,
            uuid.UUID(target["product_id"]),
            int(target["quantity"]),
        )
        lines = [li for li in lines if li.get("line_id") != line_id]
        cart.items = lines
        cart.total_amount = self._sum_total(lines)
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._events.publish(sales_events.cart_line_removed(cart))
        return cart

    async def abandon(self, organization_id: uuid.UUID, cart_id: uuid.UUID) -> ShoppingCart:
        cart = await cart_lookup.require_active(self._carts, organization_id, cart_id)
        for li in cart.items or []:
            try:
                await inventory_reservation.release(
                    self._inventories,
                    organization_id,
                    cart.branch_id,
                    uuid.UUID(li["product_id"]),
                    int(li["quantity"]),
                )
            except Exception:
                continue
        cart.status = CartStatus.ABANDONED
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._events.publish(sales_events.cart_abandoned(cart))
        return cart

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_line(
        self,
        product: Product,
        *,
        quantity: int,
        unit_price: Decimal,
        added_via: str,
        source_event_id: str | None,
        global_track_id: str | None = None,
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        subtotal = unit_price * quantity
        return {
            "line_id": uuid.uuid4().hex,
            "product_id": str(product.id),
            "sku": product.sku,
            "product_name": product.name,
            "quantity": int(quantity),
            "unit_price": str(unit_price),
            "subtotal": str(subtotal),
            "added_via": added_via,
            "source_event_id": source_event_id,
            # Best-effort anonymous cross-camera visitor id — see
            # visitor_linker.py. Not authoritative for billing (cart
            # identity is scoped per camera-local track), only for
            # reconstructing a shopper's journey across cameras.
            "global_track_id": global_track_id,
            # AI's detection confidence for this pickup (1.0 for
            # manually/staff-added lines, where a human is already the
            # source of truth). Never treated as guaranteed-correct — see
            # compute_overall_confidence() and the confidence warning shown
            # to staff before they confirm a checkout.
            "confidence": float(confidence),
            "added_at": _now().isoformat(),
        }

    def _sum_total(self, lines: list[dict[str, Any]]) -> Decimal:
        total = Decimal("0")
        for li in lines:
            total += Decimal(str(li.get("subtotal", "0")))
        return total
