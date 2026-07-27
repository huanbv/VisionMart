"""Application service for freezing, confirming, and paying out a cart —
the "Pending Checkout -> Confirmation -> Payment -> Receipt" half of the
flow. Deliberately separate from `CartService` (shopping lifecycle): this
class is the only one that ever calls a `PaymentGateway` or creates an
`Order`, which keeps "can this code charge a customer" auditable to a
single, small file.

AI never reaches this service directly — `AiCartEventService` calls
`request_checkout()` on its behalf when it sees `checkout_initiated`, but
every method that actually moves money (`_finalize_checkout`, reached via
`confirm_checkout_by_token` / `confirm_checkout_staff` / instant `checkout`)
requires a human action to have already happened: a customer confirming via
the QR/token page, or a staff member confirming or checking out in person.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.config.settings import get_settings
from app.core.events import EventBus
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.application.services import InventoryService
from app.modules.inventory.infrastructure.models import StockMovementType
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
)
from app.modules.sales.application import cart_lookup, inventory_reservation
from app.modules.sales.application.payment import PaymentGateway, SimulatedPaymentGateway
from app.modules.sales.domain import events as sales_events
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CheckoutService:
    def __init__(
        self,
        carts: SqlAlchemyCartRepository,
        inventories: SqlAlchemyInventoryRepository,
        inventory_service: InventoryService,
        orders: SqlAlchemyOrderRepository,
        order_items: SqlAlchemyOrderItemRepository,
        event_bus: EventBus,
        payment_gateway: PaymentGateway | None = None,
    ) -> None:
        self._carts = carts
        self._inventories = inventories
        self._inventory_service = inventory_service
        self._orders = orders
        self._order_items = order_items
        self._events = event_bus
        self._settings = get_settings()
        self._payment = payment_gateway or SimulatedPaymentGateway()

    async def get(self, organization_id: uuid.UUID, cart_id: uuid.UUID) -> ShoppingCart:
        return await cart_lookup.get_cart(self._carts, organization_id, cart_id)

    async def get_for_update(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart:
        """Locked read for callers about to transition the cart's status
        (staff confirm, cancel). See ``cart_lookup.get_cart_for_update``."""
        return await cart_lookup.get_cart_for_update(self._carts, organization_id, cart_id)

    def build_confirm_url(self, checkout_token: str) -> str:
        base = self._settings.PUBLIC_APP_BASE_URL.rstrip("/")
        return f"{base}/shop/{checkout_token}"

    # ------------------------------------------------------------------
    # Instant staff checkout (manual/POS-style carts — staff presence IS
    # the confirmation, so no freeze/confirm round-trip is needed).
    # ------------------------------------------------------------------
    async def checkout(
        self,
        organization_id: uuid.UUID,
        cart_id: uuid.UUID,
        *,
        performed_by: uuid.UUID | None,
    ) -> tuple[ShoppingCart, Order]:
        # Locked read: an instant staff checkout is itself a full
        # read-check-write on the cart row (see request_checkout below for
        # why this matters even though this path has no separate confirm
        # step of its own).
        cart = await cart_lookup.get_cart_for_update(
            self._carts, organization_id, cart_id
        )
        if cart.status not in (CartStatus.ACTIVE, CartStatus.PENDING_CHECKOUT):
            raise ConflictError(f"Cart cannot be checked out (status={cart.status.value})")
        if not (cart.items or []):
            raise ValidationError("Cart is empty")
        return await self._finalize_checkout(cart, performed_by=performed_by)

    # ------------------------------------------------------------------
    # Two-step checkout: request (freeze bill) -> confirm (charge)
    # ------------------------------------------------------------------
    async def request_checkout(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart:
        """Freeze an ACTIVE cart into PENDING_CHECKOUT: drafts the bill and
        mints a confirm token, but does NOT charge. Called by
        AiCartEventService when AI proposes checkout_initiated — this is as
        far as AI's involvement goes."""
        # Locked read: two near-simultaneous checkout_initiated events for
        # the same cart (duplicate AI trigger, or AI racing a staff-side
        # checkout) must not both freeze it and mint two different tokens.
        cart = await cart_lookup.require_active_for_update(
            self._carts, organization_id, cart_id
        )
        if not (cart.items or []):
            raise ValidationError("Cart is empty")

        cart.checkout_token = secrets.token_urlsafe(24)
        cart.checkout_requested_at = _now()
        cart.status = CartStatus.PENDING_CHECKOUT
        # Cart AI cho cửa sổ xác nhận dài hơn (15') và khi hết hạn sẽ bị DỌN
        # hẳn (xem cart_sweeper), không resume — vì đơn AI chưa ai xác nhận
        # thì nên biến mất khỏi màn hình, không quay lại trạng thái mua tiếp.
        # Cart nhân viên tạo tay vẫn giữ cửa sổ ngắn và resume như cũ.
        confirm_minutes = (
            self._settings.AI_CART_EXPIRATION_MINUTES
            if cart.source == CartSource.AI_VISION
            else self._settings.CART_CHECKOUT_CONFIRM_TIMEOUT_MINUTES
        )
        cart.expires_at = _now() + timedelta(minutes=confirm_minutes)
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._events.publish(sales_events.checkout_pending(cart, cart.checkout_token))
        await self._events.publish(
            sales_events.qr_code_generated(
                cart, cart.checkout_token, self.build_confirm_url(cart.checkout_token)
            )
        )
        return cart

    async def get_order_for_cart(self, cart_id: uuid.UUID) -> Order | None:
        return await self._orders.get_by_cart_id(cart_id)

    async def get_bill_by_token(self, token: str) -> ShoppingCart:
        cart = await self._carts.get_by_checkout_token(token)
        if cart is None:
            raise NotFoundError("Invalid or expired checkout link")
        return cart

    async def confirm_checkout_by_token(self, token: str) -> tuple[ShoppingCart, Order]:
        """Customer-facing confirmation via the QR/link token — no login,
        the unguessable token itself is the credential for this one bill."""
        # Locked read: this is the public endpoint most likely to receive a
        # genuine double-submit (double-tap on a phone, or a flaky mobile
        # network causing the client to retry a request that already went
        # through) — without the lock, both requests would read the cart as
        # still PENDING_CHECKOUT and both would charge + create an Order.
        cart = await self._carts.get_by_checkout_token_for_update(token)
        if cart is None:
            raise NotFoundError("Invalid or expired checkout link")
        return await self._confirm_pending(cart, performed_by=None, confirmed_by="customer")

    async def confirm_checkout_staff(
        self,
        organization_id: uuid.UUID,
        cart_id: uuid.UUID,
        *,
        performed_by: uuid.UUID | None,
    ) -> tuple[ShoppingCart, Order]:
        """Staff confirms on behalf of a walk-in with no phone/QR — the
        "Cashier Confirmation (optional)" step in the checkout flow."""
        cart = await self.get_for_update(organization_id, cart_id)
        return await self._confirm_pending(cart, performed_by=performed_by, confirmed_by="staff")

    async def _confirm_pending(
        self,
        cart: ShoppingCart,
        *,
        performed_by: uuid.UUID | None,
        confirmed_by: str,
    ) -> tuple[ShoppingCart, Order]:
        if cart.status == CartStatus.CONVERTED:
            # Idempotent replay — double-tapped "confirm" after it already
            # went through; don't charge twice.
            order = await self._orders.get_by_cart_id(cart.id)
            if order is not None:
                return cart, order
            raise ConflictError("Cart already converted but its order is missing")
        if cart.status != CartStatus.PENDING_CHECKOUT:
            raise ConflictError(
                f"Cart is not awaiting confirmation (status={cart.status.value})"
            )
        await self._events.publish(sales_events.customer_confirmed(cart, confirmed_by))
        return await self._finalize_checkout(cart, performed_by=performed_by)

    async def cancel_pending_checkout(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart:
        """Confirmation declined, or the window lapsed (see cart_sweeper) —
        cart resumes shopping instead of being billed."""
        # Locked read: a cancel racing a confirm on the same cart (customer
        # taps "keep shopping" on their phone at the same moment staff
        # confirms in person) must not both succeed — whichever one wins the
        # lock decides the cart's fate, the loser sees a fresh status and
        # its ConflictError/idempotent-replay branch below handles it
        # cleanly instead of corrupting state.
        cart = await self.get_for_update(organization_id, cart_id)
        if cart.status != CartStatus.PENDING_CHECKOUT:
            raise ConflictError(
                f"Cart is not awaiting confirmation (status={cart.status.value})"
            )
        cart.status = CartStatus.ACTIVE
        cart.checkout_token = None
        cart.checkout_requested_at = None
        cart.expires_at = _now() + timedelta(minutes=self._settings.CART_EXPIRATION_MINUTES)
        await self._carts.commit()
        await self._carts.refresh(cart)
        await self._events.publish(sales_events.checkout_cancelled(cart))
        return cart

    async def _finalize_checkout(
        self, cart: ShoppingCart, *, performed_by: uuid.UUID | None
    ) -> tuple[ShoppingCart, Order]:
        """Shared charge + Order-creation body for both the instant staff
        path and the confirm-then-charge path. By the time this runs, a
        human confirmation (staff presence, or an explicit customer tap)
        has already happened — this method itself never decides *whether*
        to charge, only *how*."""
        lines = list(cart.items or [])
        if not lines:
            raise ValidationError("Cart is empty")
        organization_id = cart.organization_id

        payment = await self._payment.charge(
            cart_id=cart.id,
            amount=cart.total_amount,
            currency=cart.currency,
            customer_id=cart.customer_id,
        )
        if not payment.success:
            await self._events.publish(
                sales_events.payment_failed(cart, payment.error or "unknown")
            )
            raise ConflictError(
                f"Payment declined by {payment.gateway}: {payment.error or 'unknown'}"
            )

        now = _now()

        def _build_order(code: str) -> Order:
            return Order(
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
                notes="AI-assisted checkout, confirmed by a human"
                if cart.source == CartSource.AI_VISION
                else None,
                payment_gateway=payment.gateway,
                payment_reference=payment.reference,
                payment_status=payment.status,
            )

        # Retries internally (fresh code + fresh attempt) if this code
        # collides with one a concurrent checkout just committed — see
        # SqlAlchemyOrderRepository.add_with_unique_code / next_code
        # docstrings for why that collision is possible at all.
        order = await self._orders.add_with_unique_code(organization_id, _build_order)
        code = order.code

        # Flip the cart to CONVERTED and commit *now*, before touching
        # inventory below. This is what actually makes the row lock taken
        # by our caller (get_by_id_for_update / get_by_checkout_token_for_
        # update) effective end-to-end: inventory_reservation.release() and
        # InventoryService.adjust(), called per line in the loop below, each
        # commit the shared session internally. If the cart's CONVERTED
        # status weren't committed until after that loop, the first of
        # those inner commits would release our row lock while the cart
        # still reads as PENDING_CHECKOUT in the database — letting a
        # concurrent request that was blocked on the lock sail through and
        # double-charge/double-order. Committing the status flip here,
        # before any inner commit can fire, guarantees whoever was blocked
        # on the lock sees CONVERTED the instant they acquire the row and
        # takes the idempotent-replay branch in _confirm_pending instead.
        cart.status = CartStatus.CONVERTED
        cart.converted_at = now
        cart.checkout_token = None
        await self._carts.commit()
        await self._carts.refresh(cart)

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
            await inventory_reservation.release(
                self._inventories, organization_id, cart.branch_id, product_id, quantity
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

        order = await self._orders.refresh_with_items(order)

        await self._events.publish(sales_events.payment_succeeded(cart, order))
        await self._events.publish(sales_events.receipt_generated(cart, order))
        try:
            from app.services.ai_engine_client import AIEngineClient
            await AIEngineClient().reset_session()
        except Exception:
            pass
        return cart, order
