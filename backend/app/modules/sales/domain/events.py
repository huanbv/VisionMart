"""Domain event names + payload builders for the Sales bounded context
(cart + checkout).

Uses the project's existing event bus (`app/core/events/`, wired via
`app/dependencies/providers.get_event_bus`) rather than introducing a
second, parallel event system — an earlier session added a colliding
`app/core/events.py` module that shadowed nothing (the pre-existing
package always wins on import) and broke application startup; see the
pre-production audit report for the full account. This module now builds
plain `DomainEvent(name, payload, ...)` instances matching that package's
actual shape (`name: str`, `payload: dict`, `event_id`, `occurred_at`,
`aggregate_id`), instead of subclassing it with incompatible fields.

Naming follows the project's checkout-flow vocabulary:

    Shopping -> CheckoutPending -> QRCodeGenerated -> CustomerConfirmed
             -> PaymentSucceeded/PaymentFailed -> ReceiptGenerated

AI's own detections (product_picked_up / product_returned / checkout
proposals) are *inbound* requests handled by `AiCartEventService`, not
domain events in their own right — they become `sales.cart_line_added`,
`sales.checkout_pending`, etc. once accepted, same as if a human had
triggered the equivalent action manually. AI has no separate/privileged
event path.

Payloads carry the live `ShoppingCart`/`Order` ORM objects directly under
the `"cart"`/`"order"` keys. That's a deliberate simplification: `payload`
is typed `dict[str, Any]` by the event bus itself, these events never leave
the process or the publisher's DB session, and the bus is in-memory/
same-process (see `app/core/events/in_memory.py`) — there is no
serialization boundary to respect here. A future cross-process event would
need a JSON-serializable payload instead.
"""

from __future__ import annotations

from typing import Any

from app.core.events import DomainEvent
from app.modules.sales.infrastructure.models import Order, ShoppingCart

CART_CREATED = "sales.cart_created"
CART_LINE_ADDED = "sales.cart_line_added"
CART_LINE_REMOVED = "sales.cart_line_removed"
CART_ABANDONED = "sales.cart_abandoned"

# Cart froze into PENDING_CHECKOUT — bill drafted, NOTHING charged. This is
# where AI's involvement in the checkout flow ends; everything downstream
# is a human confirmation + payment concern.
CHECKOUT_PENDING = "sales.checkout_pending"

# A confirm token/link now exists for this pending checkout. Published
# alongside CHECKOUT_PENDING (token minted at the same time) so a future
# consumer (e.g. a customer-display panel service) can react to "a QR is
# ready to show" without caring about cart lifecycle details.
QR_CODE_GENERATED = "sales.qr_code_generated"

# Someone confirmed the pending checkout: either the customer via the
# QR/token page, or staff on behalf of a walk-in without a phone ("Cashier
# Confirmation" in the checkout flow — modelled via the `confirmed_by`
# payload field rather than a second event name, since the two paths do the
# exact same thing from every other module's point of view).
CUSTOMER_CONFIRMED = "sales.customer_confirmed"

# Confirmation was declined, or the confirmation window lapsed unconfirmed
# — cart resumes as ACTIVE either way.
CHECKOUT_CANCELLED = "sales.checkout_cancelled"

PAYMENT_SUCCEEDED = "sales.payment_succeeded"
PAYMENT_FAILED = "sales.payment_failed"

# Order persisted with its items — the system's stand-in for a printed
# receipt. Published right after PAYMENT_SUCCEEDED.
RECEIPT_GENERATED = "sales.receipt_generated"

ALL_EVENT_NAMES = (
    CART_CREATED,
    CART_LINE_ADDED,
    CART_LINE_REMOVED,
    CART_ABANDONED,
    CHECKOUT_PENDING,
    QR_CODE_GENERATED,
    CUSTOMER_CONFIRMED,
    CHECKOUT_CANCELLED,
    PAYMENT_SUCCEEDED,
    PAYMENT_FAILED,
    RECEIPT_GENERATED,
)


def _cart_event(name: str, cart: ShoppingCart, **extra: Any) -> DomainEvent:
    payload: dict[str, Any] = {"cart": cart}
    payload.update(extra)
    return DomainEvent(name=name, payload=payload, aggregate_id=str(cart.id))


def cart_created(cart: ShoppingCart) -> DomainEvent:
    return _cart_event(CART_CREATED, cart)


def cart_line_added(cart: ShoppingCart) -> DomainEvent:
    return _cart_event(CART_LINE_ADDED, cart)


def cart_line_removed(cart: ShoppingCart) -> DomainEvent:
    return _cart_event(CART_LINE_REMOVED, cart)


def cart_abandoned(cart: ShoppingCart) -> DomainEvent:
    return _cart_event(CART_ABANDONED, cart)


def checkout_pending(cart: ShoppingCart, checkout_token: str) -> DomainEvent:
    return _cart_event(CHECKOUT_PENDING, cart, checkout_token=checkout_token)


def qr_code_generated(cart: ShoppingCart, checkout_token: str, confirm_url: str) -> DomainEvent:
    return _cart_event(
        QR_CODE_GENERATED, cart, checkout_token=checkout_token, confirm_url=confirm_url
    )


def customer_confirmed(cart: ShoppingCart, confirmed_by: str) -> DomainEvent:
    return _cart_event(CUSTOMER_CONFIRMED, cart, confirmed_by=confirmed_by)


def checkout_cancelled(cart: ShoppingCart) -> DomainEvent:
    return _cart_event(CHECKOUT_CANCELLED, cart)


def payment_succeeded(cart: ShoppingCart, order: Order) -> DomainEvent:
    return _cart_event(PAYMENT_SUCCEEDED, cart, order=order)


def payment_failed(cart: ShoppingCart, reason: str) -> DomainEvent:
    return _cart_event(PAYMENT_FAILED, cart, reason=reason)


def receipt_generated(cart: ShoppingCart, order: Order) -> DomainEvent:
    return _cart_event(RECEIPT_GENERATED, cart, order=order)
