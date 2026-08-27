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


def apply_sku_to_line(line: dict[str, Any], product: Product) -> dict[str, Any]:
    """Keep crop, quantity, and line id; swap catalog fields to the SKU staff chose."""
    quantity = int(line.get("quantity") or 1)
    unit_price = Decimal(str(product.unit_price))
    updated = dict(line)
    updated["product_id"] = str(product.id)
    updated["sku"] = product.sku
    updated["product_name"] = product.name
    updated["unit_price"] = str(unit_price)
    updated["subtotal"] = str(unit_price * quantity)
    updated["confidence"] = 1.0
    updated["added_via"] = "staff_correction"
    return updated


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
        customer_photo_key: str | None = None,
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
            customer_photo_key=customer_photo_key,
        )
        cart = await self._carts.add(cart)
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._events.publish(sales_events.cart_created(cart))
        return cart

    async def set_scan_photo_key(
        self,
        organization_id: uuid.UUID,
        cart_id: uuid.UUID,
        scan_photo_key: str,
    ) -> ShoppingCart:
        cart = await cart_lookup.get_cart(self._carts, organization_id, cart_id)
        cart.scan_photo_key = scan_photo_key
        await self._carts.commit()
        await self._carts.refresh(cart)
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
        photo_key: str | None = None,
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
            photo_key=photo_key,
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

        # Auto-abandon AI carts the moment the last item is removed so that
        # empty carts never show as "active" in the live dashboard.  A fresh
        # cart will be opened the next time the AI detects a product.
        if not lines and cart.source == CartSource.AI_VISION:
            cart.status = CartStatus.ABANDONED
            await self._carts.commit()
            await self._carts.refresh(cart)
            await self._events.publish(sales_events.cart_abandoned(cart))

        return cart

    async def retag_line(
        self,
        organization_id: uuid.UUID,
        cart_id: uuid.UUID,
        line_id: str,
        *,
        product_id: uuid.UUID,
    ) -> tuple[ShoppingCart, dict[str, Any] | None]:
        """Đổi SKU trên đúng dòng — giữ crop, sửa giá/tồn. Trả payload học nếu có ảnh."""
        cart = await cart_lookup.require_active(self._carts, organization_id, cart_id)
        lines = list(cart.items or [])
        target = next((li for li in lines if li.get("line_id") == line_id), None)
        if target is None:
            raise NotFoundError("Cart line not found")

        old_product_id = uuid.UUID(str(target["product_id"]))
        if old_product_id == product_id:
            return cart, None

        product = await self._products.get_by_id(organization_id, product_id)
        if product is None:
            raise NotFoundError("Product not found")

        quantity = int(target.get("quantity") or 1)
        # Reserve the replacement first so a stock miss leaves the original line intact.
        await inventory_reservation.reserve(
            self._inventories, organization_id, cart.branch_id, product_id, quantity
        )
        await inventory_reservation.release(
            self._inventories, organization_id, cart.branch_id, old_product_id, quantity
        )

        old_sku = str(target.get("sku") or "")
        updated = apply_sku_to_line(target, product)
        cart.items = [
            updated if li.get("line_id") == line_id else li for li in lines
        ]
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(cart, "items")
        cart.total_amount = self._sum_total(list(cart.items or []))
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._events.publish(sales_events.cart_line_added(cart))

        photo_key = str(updated.get("photo_key") or "").strip() or None
        correction = {
            "photo_key": photo_key,
            "predicted_product_id": old_product_id,
            "predicted_sku": old_sku,
            "confirmed_product_id": product.id,
            "confirmed_sku": product.sku,
            "confidence": target.get("confidence"),
        }
        return cart, correction

    async def abandon(self, organization_id: uuid.UUID, cart_id: uuid.UUID) -> ShoppingCart:
        cart = await cart_lookup.get_cart(self._carts, organization_id, cart_id)
        if cart.status not in (CartStatus.ACTIVE, CartStatus.PENDING_CHECKOUT):
            raise ConflictError(f"Cart cannot be abandoned (status={cart.status.value})")
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
        try:
            from app.services.ai_engine_client import AIEngineClient
            await AIEngineClient().reset_session()
        except Exception:
            pass
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
        photo_key: str | None = None,
    ) -> dict[str, Any]:
        subtotal = unit_price * quantity
        line: dict[str, Any] = {
            "line_id": uuid.uuid4().hex,
            "product_id": str(product.id),
            "sku": product.sku,
            "product_name": product.name,
            "quantity": int(quantity),
            "unit_price": str(unit_price),
            "subtotal": str(subtotal),
            "added_via": added_via,
            "source_event_id": source_event_id,
            "global_track_id": global_track_id,
            "confidence": float(confidence),
            "added_at": _now().isoformat(),
        }
        if photo_key:
            line["photo_key"] = photo_key
        return line

    def _sum_total(self, lines: list[dict[str, Any]]) -> Decimal:
        total = Decimal("0")
        for li in lines:
            total += Decimal(str(li.get("subtotal", "0")))
        return total
