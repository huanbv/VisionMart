"""Shared inventory reservation helpers.

`CartService` reserves stock when a line is added and releases it when a
line is removed or the cart is abandoned. `CheckoutService` releases the
same reservation (immediately before deducting real stock) when a checkout
is finalized. Rather than have `CheckoutService` depend on `CartService`
just to reuse this, or duplicate the locking logic in both, it lives here
as free functions used by both.
"""

from __future__ import annotations

import uuid

from app.core.exceptions import ConflictError
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
)


async def reserve(
    inventories: SqlAlchemyInventoryRepository,
    organization_id: uuid.UUID,
    branch_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: int,
) -> None:
    # Locked read: two concurrent reservations for the same product+branch
    # (two AI-detected pickups, or a cashier and the AI racing) must not
    # both pass the availability check against the same stale snapshot —
    # that oversells stock. See get_by_product_branch_for_update docstring.
    inv = await inventories.get_by_product_branch_for_update(
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
    await inventories.commit()
    await inventories.refresh(inv)


async def release(
    inventories: SqlAlchemyInventoryRepository,
    organization_id: uuid.UUID,
    branch_id: uuid.UUID,
    product_id: uuid.UUID,
    quantity: int,
) -> None:
    inv = await inventories.get_by_product_branch_for_update(
        organization_id, product_id, branch_id
    )
    if inv is None:
        return
    inv.reserved_quantity = max(0, inv.reserved_quantity - quantity)
    await inventories.commit()
    await inventories.refresh(inv)
