"""Tiny shared cart lookup/validation helpers.

Both `CartService` (shopping lifecycle) and `CheckoutService`
(freeze/confirm/payment) need to fetch a cart by id and, in a few places,
assert it's still ACTIVE before mutating it. Pulling this out as free
functions means neither service has to import or depend on the other just
for a shared read — they stay independently constructible/testable, which
was the whole point of splitting them apart.
"""

from __future__ import annotations

import uuid

from app.core.exceptions import ConflictError, NotFoundError
from app.modules.sales.infrastructure.models import CartStatus, ShoppingCart
from app.modules.sales.infrastructure.repositories import SqlAlchemyCartRepository


async def get_cart(
    carts: SqlAlchemyCartRepository,
    organization_id: uuid.UUID,
    cart_id: uuid.UUID,
) -> ShoppingCart:
    cart = await carts.get_by_id(organization_id, cart_id)
    if cart is None:
        raise NotFoundError("Cart not found")
    return cart


async def require_active(
    carts: SqlAlchemyCartRepository,
    organization_id: uuid.UUID,
    cart_id: uuid.UUID,
) -> ShoppingCart:
    cart = await get_cart(carts, organization_id, cart_id)
    if cart.status != CartStatus.ACTIVE:
        raise ConflictError(f"Cart is not active (status={cart.status.value})")
    return cart


async def get_cart_for_update(
    carts: SqlAlchemyCartRepository,
    organization_id: uuid.UUID,
    cart_id: uuid.UUID,
) -> ShoppingCart:
    """Locked variant of ``get_cart`` — use for any read that's followed by
    a status-transitioning write (freeze, confirm, cancel). See
    ``SqlAlchemyCartRepository.get_by_id_for_update`` for why."""
    cart = await carts.get_by_id_for_update(organization_id, cart_id)
    if cart is None:
        raise NotFoundError("Cart not found")
    return cart


async def require_active_for_update(
    carts: SqlAlchemyCartRepository,
    organization_id: uuid.UUID,
    cart_id: uuid.UUID,
) -> ShoppingCart:
    cart = await get_cart_for_update(carts, organization_id, cart_id)
    if cart.status != CartStatus.ACTIVE:
        raise ConflictError(f"Cart is not active (status={cart.status.value})")
    return cart
