"""Application services for the Inventory bounded context."""

from __future__ import annotations

import uuid

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.inventory.infrastructure.models import (
    Inventory,
    StockMovement,
    StockMovementType,
)
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
    SqlAlchemyStockMovementRepository,
)
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)


class InventoryService:
    def __init__(
        self,
        inventories: SqlAlchemyInventoryRepository,
        movements: SqlAlchemyStockMovementRepository,
        products: SqlAlchemyProductRepository,
        branches: SqlAlchemyBranchRepository,
    ) -> None:
        self._inventories = inventories
        self._movements = movements
        self._products = products
        self._branches = branches

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
        search: str | None,
        branch_id: uuid.UUID | None,
        low_stock: bool,
    ) -> tuple[list[tuple[Inventory, object, object]], int]:
        return await self._inventories.list_for_org(
            organization_id,
            skip=skip,
            limit=limit,
            search=search,
            branch_id=branch_id,
            low_stock=low_stock,
        )

    async def get(
        self, organization_id: uuid.UUID, inventory_id: uuid.UUID
    ) -> tuple[Inventory, object, object]:
        row = await self._inventories.get_by_id(organization_id, inventory_id)
        if row is None:
            raise NotFoundError("Inventory entry not found")
        return row

    async def adjust(
        self,
        organization_id: uuid.UUID,
        *,
        product_id: uuid.UUID,
        branch_id: uuid.UUID,
        delta: int,
        movement_type: StockMovementType,
        reason: str | None,
        reference: str | None,
        performed_by: uuid.UUID | None,
    ) -> Inventory:
        if delta == 0:
            raise ValidationError("Delta must not be zero")
        product = await self._products.get_by_id(organization_id, product_id)
        if product is None:
            raise NotFoundError("Product not found")
        branch = await self._branches.get_by_id(organization_id, branch_id)
        if branch is None:
            raise NotFoundError("Branch not found")

        # Locked read — see get_by_product_branch_for_update docstring:
        # without the lock, two concurrent adjust() calls (e.g. checkout
        # deduction racing a manual stock correction) can both read the same
        # quantity and one silently overwrites the other's change.
        inv = await self._inventories.get_by_product_branch_for_update(
            organization_id, product_id, branch_id
        )
        if inv is None:
            inv = Inventory(
                product_id=product_id,
                branch_id=branch_id,
                quantity=0,
                reserved_quantity=0,
                reorder_level=0,
            )
            inv = await self._inventories.add(inv)

        new_qty = inv.quantity + delta
        if new_qty < 0:
            raise ConflictError(
                f"Insufficient stock: have {inv.quantity}, requested {-delta}"
            )
        if new_qty < inv.reserved_quantity:
            raise ConflictError(
                "Resulting quantity is below reserved quantity"
            )
        inv.quantity = new_qty

        movement = StockMovement(
            organization_id=organization_id,
            product_id=product_id,
            branch_id=branch_id,
            movement_type=movement_type,
            delta=delta,
            quantity_after=new_qty,
            reason=reason,
            reference=reference,
            performed_by=performed_by,
        )
        await self._movements.add(movement)
        await self._inventories.commit()
        await self._inventories.refresh(inv)
        return inv

    async def transfer(
        self,
        organization_id: uuid.UUID,
        *,
        product_id: uuid.UUID,
        from_branch_id: uuid.UUID,
        to_branch_id: uuid.UUID,
        quantity: int,
        reason: str | None,
        reference: str | None,
        performed_by: uuid.UUID | None,
    ) -> tuple[Inventory, Inventory]:
        if quantity <= 0:
            raise ValidationError("Transfer quantity must be positive")
        if from_branch_id == to_branch_id:
            raise ValidationError("Source and destination branches must differ")
        src = await self.adjust(
            organization_id,
            product_id=product_id,
            branch_id=from_branch_id,
            delta=-quantity,
            movement_type=StockMovementType.TRANSFER_OUT,
            reason=reason,
            reference=reference,
            performed_by=performed_by,
        )
        dst = await self.adjust(
            organization_id,
            product_id=product_id,
            branch_id=to_branch_id,
            delta=quantity,
            movement_type=StockMovementType.TRANSFER_IN,
            reason=reason,
            reference=reference,
            performed_by=performed_by,
        )
        return src, dst

    async def set_reorder_level(
        self,
        organization_id: uuid.UUID,
        inventory_id: uuid.UUID,
        reorder_level: int,
    ) -> Inventory:
        if reorder_level < 0:
            raise ValidationError("Reorder level must be non-negative")
        row = await self._inventories.get_by_id(organization_id, inventory_id)
        if row is None:
            raise NotFoundError("Inventory entry not found")
        inv = row[0]
        inv.reorder_level = reorder_level
        await self._inventories.commit()
        await self._inventories.refresh(inv)
        return inv

    async def list_movements(
        self,
        organization_id: uuid.UUID,
        inventory_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> tuple[list[StockMovement], int]:
        row = await self._inventories.get_by_id(organization_id, inventory_id)
        if row is None:
            raise NotFoundError("Inventory entry not found")
        inv = row[0]
        return await self._movements.list_for_inventory(
            organization_id, inv.product_id, inv.branch_id, skip=skip, limit=limit
        )
