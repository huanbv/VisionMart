"""Application service for the Shopping Cart aggregate.

Responsibilities:
  * Manage the lifecycle of `ShoppingCart` (create, add/remove line, checkout, abandon).
  * Enforce inventory reservation via `reserved_quantity`.
  * Apply AI-emitted events (product picked up / returned / checkout initiated).
  * Convert a cart to an `Order` at checkout, atomically deducting inventory.
  * Publish realtime updates for WebSocket subscribers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.config.settings import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.catalog.infrastructure.models import Product
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.inventory.application.services import InventoryService
from app.modules.inventory.infrastructure.models import (
    Inventory,
    StockMovementType,
)
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
)
from app.modules.sales.application.cart_realtime import publish_cart_update
from app.modules.sales.application.payment import (
    PaymentGateway,
    SimulatedPaymentGateway,
)
from app.modules.sales.infrastructure.models import (
    CartSource,
    CartStatus,
    Order,
    OrderItem,
    OrderStatus,
    ShoppingCart,
)
from app.modules.sales.infrastructure.repositories import (
    SqlAlchemyCartRepository,
    SqlAlchemyOrderItemRepository,
    SqlAlchemyOrderRepository,
)
from app.modules.sales.schemas.ai_events import (
    AICartEventRequest,
    AICartEventType,
)
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CartService:
    def __init__(
        self,
        carts: SqlAlchemyCartRepository,
        inventories: SqlAlchemyInventoryRepository,
        inventory_service: InventoryService,
        products: SqlAlchemyProductRepository,
        branches: SqlAlchemyBranchRepository,
        orders: SqlAlchemyOrderRepository,
        order_items: SqlAlchemyOrderItemRepository,
        payment_gateway: PaymentGateway | None = None,
    ) -> None:
        self._carts = carts
        self._inventories = inventories
        self._inventory_service = inventory_service
        self._products = products
        self._branches = branches
        self._orders = orders
        self._order_items = order_items
        self._settings = get_settings()
        self._payment = payment_gateway or SimulatedPaymentGateway()

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

    async def get(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart:
        cart = await self._carts.get_by_id(organization_id, cart_id)
        if cart is None:
            raise NotFoundError("Cart not found")
        return cart

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

        expires_at = _now() + timedelta(
            minutes=self._settings.CART_EXPIRATION_MINUTES
        )
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
        await self._publish(cart, action="created")
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
    ) -> ShoppingCart:
        cart = await self._require_open_cart(organization_id, cart_id)
        product = await self._products.get_by_id(organization_id, product_id)
        if product is None:
            raise NotFoundError("Product not found")

        await self._reserve(organization_id, cart.branch_id, product_id, quantity)

        lines = list(cart.items or [])
        price = unit_price if unit_price is not None else product.unit_price
        line = self._build_line(
            product,
            quantity=quantity,
            unit_price=Decimal(str(price)),
            added_via=added_via,
            source_event_id=source_event_id,
        )
        lines.append(line)
        cart.items = lines
        cart.total_amount = self._sum_total(lines)
        cart.expires_at = _now() + timedelta(
            minutes=self._settings.CART_EXPIRATION_MINUTES
        )
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._publish(cart, action="line_added")
        return cart

    async def remove_line(
        self,
        organization_id: uuid.UUID,
        cart_id: uuid.UUID,
        line_id: str,
    ) -> ShoppingCart:
        cart = await self._require_open_cart(organization_id, cart_id)
        lines = list(cart.items or [])
        target = next((li for li in lines if li.get("line_id") == line_id), None)
        if target is None:
            raise NotFoundError("Cart line not found")

        await self._release(
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
        await self._publish(cart, action="line_removed")
        return cart

    async def checkout(
        self,
        organization_id: uuid.UUID,
        cart_id: uuid.UUID,
        *,
        performed_by: uuid.UUID | None,
    ) -> tuple[ShoppingCart, Order]:
        cart = await self._require_open_cart(organization_id, cart_id)
        lines = list(cart.items or [])
        if not lines:
            raise ValidationError("Cart is empty")

        payment = await self._payment.charge(
            cart_id=cart.id,
            amount=cart.total_amount,
            currency=cart.currency,
            customer_id=cart.customer_id,
        )
        if not payment.success:
            raise ConflictError(
                f"Payment declined by {payment.gateway}: {payment.error or 'unknown'}"
            )

        code = await self._orders.next_code(organization_id)
        now = _now()
        order = Order(
            organization_id=organization_id,
            branch_id=cart.branch_id,
            customer_id=cart.customer_id,
            employee_id=None,
            cart_id=cart.id,
            code=code,
            status=OrderStatus.PAID,
            total_amount=cart.total_amount,
            currency=cart.currency,
            paid_at=now,
            notes="Auto-checkout via AI cart" if cart.source == CartSource.AI_VISION else None,
            payment_gateway=payment.gateway,
            payment_reference=payment.reference,
            payment_status=payment.status,
        )
        order = await self._orders.add(order)

        for li in lines:
            product_id = uuid.UUID(li["product_id"])
            quantity = int(li["quantity"])
            unit_price = Decimal(str(li["unit_price"]))
            subtotal = Decimal(str(li["subtotal"]))
            item = OrderItem(
                order_id=order.id,
                product_id=product_id,
                quantity=quantity,
                unit_price=unit_price,
                discount_amount=Decimal("0"),
                subtotal=subtotal,
            )
            await self._order_items.add(item)
            await self._release(
                organization_id, cart.branch_id, product_id, quantity
            )
            await self._inventory_service.adjust(
                organization_id,
                product_id=product_id,
                branch_id=cart.branch_id,
                delta=-quantity,
                movement_type=StockMovementType.OUT,
                reason=f"Cart checkout {code}",
                reference=code,
                performed_by=performed_by,
            )

        cart.status = CartStatus.CONVERTED
        cart.converted_at = now
        await self._carts.commit()
        await self._carts.refresh(cart)
        order = await self._orders.refresh_with_items(order)
        await self._publish(cart, action="converted", order_id=str(order.id), order_code=order.code)
        return cart, order

    async def abandon(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart:
        cart = await self._require_open_cart(organization_id, cart_id)
        for li in cart.items or []:
            try:
                await self._release(
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
        await self._publish(cart, action="abandoned")
        return cart

    # ------------------------------------------------------------------
    # AI event application
    # ------------------------------------------------------------------
    async def apply_ai_event(
        self, event: AICartEventRequest
    ) -> tuple[str, ShoppingCart | None, Order | None]:
        if event.confidence < self._settings.CART_AI_MIN_CONFIDENCE:
            return "rejected_low_confidence", None, None

        session_id = f"track:{event.track_id}"

        if event.event_type == AICartEventType.PRODUCT_PICKED_UP:
            product = await self._resolve_product(
                event.organization_id, event.product_id, event.product_sku
            )
            if product is None:
                return "rejected_unknown_product", None, None
            cart = await self._get_or_create_ai_cart(
                event.organization_id,
                event.branch_id,
                session_id,
                event.customer_id,
            )
            try:
                cart = await self.add_line(
                    event.organization_id,
                    cart.id,
                    product_id=product.id,
                    quantity=event.quantity,
                    unit_price=None,
                    added_via="ai",
                    source_event_id=event.event_id,
                )
            except ConflictError:
                return "rejected_insufficient_stock", cart, None
            return "accepted", cart, None

        if event.event_type == AICartEventType.PRODUCT_RETURNED:
            cart = await self._carts.get_open_for_session(
                event.organization_id, event.branch_id, session_id
            )
            if cart is None:
                return "rejected_no_cart", None, None
            product = await self._resolve_product(
                event.organization_id, event.product_id, event.product_sku
            )
            if product is None:
                return "rejected_unknown_product", cart, None
            match = next(
                (
                    li
                    for li in reversed(list(cart.items or []))
                    if li.get("product_id") == str(product.id)
                ),
                None,
            )
            if match is None:
                return "rejected_line_not_found", cart, None
            cart = await self.remove_line(
                event.organization_id, cart.id, match["line_id"]
            )
            return "accepted", cart, None

        if event.event_type == AICartEventType.CHECKOUT_INITIATED:
            cart = await self._carts.get_open_for_session(
                event.organization_id, event.branch_id, session_id
            )
            if cart is None or not (cart.items or []):
                return "rejected_empty_cart", cart, None
            cart, order = await self.checkout(
                event.organization_id, cart.id, performed_by=None
            )
            return "accepted", cart, order

        return "rejected_unknown_event", None, None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _require_open_cart(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart:
        cart = await self.get(organization_id, cart_id)
        if cart.status != CartStatus.ACTIVE:
            raise ConflictError(f"Cart is not active (status={cart.status.value})")
        return cart

    async def _get_or_create_ai_cart(
        self,
        organization_id: uuid.UUID,
        branch_id: uuid.UUID,
        session_id: str,
        customer_id: uuid.UUID | None,
    ) -> ShoppingCart:
        existing = await self._carts.get_open_for_session(
            organization_id, branch_id, session_id
        )
        if existing is not None:
            return existing
        return await self.create(
            organization_id,
            branch_id=branch_id,
            customer_id=customer_id,
            session_id=session_id,
            source=CartSource.AI_VISION,
        )

    async def _resolve_product(
        self,
        organization_id: uuid.UUID,
        product_id: uuid.UUID | None,
        sku: str | None,
    ) -> Product | None:
        if product_id is not None:
            return await self._products.get_by_id(organization_id, product_id)
        if sku:
            items, _ = await self._products.list_for_org(
                organization_id, skip=0, limit=1, search=sku, is_active=True
            )
            for item in items:
                if item.sku.lower() == sku.lower():
                    return item
        return None

    async def _reserve(
        self,
        organization_id: uuid.UUID,
        branch_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: int,
    ) -> None:
        inv = await self._inventories.get_by_product_branch(
            organization_id, product_id, branch_id
        )
        if inv is None:
            raise ConflictError("Product is not stocked at this branch")
        available = inv.quantity - inv.reserved_quantity
        if available < quantity:
            raise ConflictError(
                f"Insufficient stock: need {quantity}, available {available}"
            )
        inv.reserved_quantity = inv.reserved_quantity + quantity
        await self._inventories.commit()
        await self._inventories.refresh(inv)

    async def _release(
        self,
        organization_id: uuid.UUID,
        branch_id: uuid.UUID,
        product_id: uuid.UUID,
        quantity: int,
    ) -> None:
        inv = await self._inventories.get_by_product_branch(
            organization_id, product_id, branch_id
        )
        if inv is None:
            return
        new_reserved = max(0, inv.reserved_quantity - quantity)
        inv.reserved_quantity = new_reserved
        await self._inventories.commit()
        await self._inventories.refresh(inv)

    def _build_line(
        self,
        product: Product,
        *,
        quantity: int,
        unit_price: Decimal,
        added_via: str,
        source_event_id: str | None,
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
            "added_at": _now().isoformat(),
        }

    def _sum_total(self, lines: list[dict[str, Any]]) -> Decimal:
        total = Decimal("0")
        for li in lines:
            total += Decimal(str(li.get("subtotal", "0")))
        return total

    async def _publish(
        self, cart: ShoppingCart, *, action: str, **extra: Any
    ) -> None:
        payload = {
            "type": "cart_update",
            "action": action,
            "cart_id": str(cart.id),
            "branch_id": str(cart.branch_id),
            "status": cart.status.value,
            "source": cart.source.value,
            "total_amount": str(cart.total_amount),
            "currency": cart.currency,
            "line_count": len(cart.items or []),
            "updated_at": (cart.updated_at or _now()).isoformat(),
        }
        payload.update(extra)
        try:
            await publish_cart_update(cart.branch_id, payload)
        except Exception:
            pass
