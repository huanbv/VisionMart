"""Application services for the Sales bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.inventory.application.services import InventoryService
from app.modules.inventory.infrastructure.models import StockMovementType
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
    SqlAlchemyStockMovementRepository,
)
from app.modules.sales.infrastructure.models import (
    Order,
    OrderItem,
    OrderStatus,
)
from app.modules.sales.infrastructure.repositories import (
    SqlAlchemyOrderItemRepository,
    SqlAlchemyOrderRepository,
)
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)


class OrderLineInput:
    __slots__ = ("product_id", "quantity", "unit_price", "discount_amount")

    def __init__(
        self,
        product_id: uuid.UUID,
        quantity: int,
        unit_price: Decimal | None,
        discount_amount: Decimal,
    ) -> None:
        self.product_id = product_id
        self.quantity = quantity
        self.unit_price = unit_price
        self.discount_amount = discount_amount


class OrderService:
    def __init__(
        self,
        orders: SqlAlchemyOrderRepository,
        order_items: SqlAlchemyOrderItemRepository,
        products: SqlAlchemyProductRepository,
        branches: SqlAlchemyBranchRepository,
        inventory: InventoryService,
    ) -> None:
        self._orders = orders
        self._items = order_items
        self._products = products
        self._branches = branches
        self._inventory = inventory

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
        branch_id: uuid.UUID | None,
        status: OrderStatus | None,
        date_from: datetime | None,
        date_to: datetime | None,
        search: str | None,
    ) -> tuple[list[tuple[Order, object]], int]:
        return await self._orders.list_for_org(
            organization_id,
            skip=skip,
            limit=limit,
            branch_id=branch_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )

    async def get(
        self, organization_id: uuid.UUID, order_id: uuid.UUID
    ) -> Order:
        order = await self._orders.get_by_id(organization_id, order_id)
        if order is None:
            raise NotFoundError("Order not found")
        return order

    async def create_order(
        self,
        organization_id: uuid.UUID,
        *,
        branch_id: uuid.UUID,
        lines: list[OrderLineInput],
        customer_id: uuid.UUID | None,
        notes: str | None,
        performed_by: uuid.UUID | None,
    ) -> Order:
        if not lines:
            raise ValidationError("Order must contain at least one line")
        branch = await self._branches.get_by_id(organization_id, branch_id)
        if branch is None:
            raise NotFoundError("Branch not found")

        normalized: list[tuple[OrderLineInput, Decimal, Decimal]] = []
        total = Decimal("0")
        aggregated: dict[uuid.UUID, int] = {}
        for line in lines:
            if line.quantity <= 0:
                raise ValidationError("Line quantity must be positive")
            if line.discount_amount < 0:
                raise ValidationError("Discount must be non-negative")
            product = await self._products.get_by_id(
                organization_id, line.product_id
            )
            if product is None:
                raise NotFoundError(f"Product {line.product_id} not found")
            unit_price = (
                line.unit_price if line.unit_price is not None else product.unit_price
            )
            if unit_price < 0:
                raise ValidationError("Unit price must be non-negative")
            gross = unit_price * line.quantity
            subtotal = gross - line.discount_amount
            if subtotal < 0:
                raise ValidationError(
                    f"Discount exceeds gross for product {product.sku}"
                )
            normalized.append((line, unit_price, subtotal))
            total += subtotal
            aggregated[line.product_id] = (
                aggregated.get(line.product_id, 0) + line.quantity
            )

        for product_id, needed in aggregated.items():
            inv = await self._inventory._inventories.get_by_product_branch(
                organization_id, product_id, branch_id
            )
            available = (inv.quantity - inv.reserved_quantity) if inv else 0
            if available < needed:
                raise ConflictError(
                    f"Insufficient stock for product {product_id}: "
                    f"need {needed}, have {available}"
                )

        now = datetime.now(timezone.utc)

        def _build_order(code: str) -> Order:
            return Order(
                organization_id=organization_id,
                branch_id=branch_id,
                customer_id=customer_id,
                employee_id=None,
                cart_id=None,
                code=code,
                status=OrderStatus.PAID,
                total_amount=total,
                currency="VND",
                paid_at=now,
                notes=notes,
            )

        # Same next_code() collision risk as CheckoutService — two manual
        # orders created in the same instant can compute the same code.
        # See SqlAlchemyOrderRepository.add_with_unique_code.
        order = await self._orders.add_with_unique_code(organization_id, _build_order)
        code = order.code

        for line, unit_price, subtotal in normalized:
            item = OrderItem(
                order_id=order.id,
                product_id=line.product_id,
                quantity=line.quantity,
                unit_price=unit_price,
                discount_amount=line.discount_amount,
                subtotal=subtotal,
            )
            await self._items.add(item)

            await self._inventory.adjust(
                organization_id,
                product_id=line.product_id,
                branch_id=branch_id,
                delta=-line.quantity,
                movement_type=StockMovementType.OUT,
                reason=f"Order {code}",
                reference=code,
                performed_by=performed_by,
            )

        return await self._orders.refresh_with_items(order)

    async def cancel_order(
        self,
        organization_id: uuid.UUID,
        order_id: uuid.UUID,
        *,
        performed_by: uuid.UUID | None,
    ) -> Order:
        order = await self.get(organization_id, order_id)
        if order.status == OrderStatus.CANCELLED:
            raise ConflictError("Order already cancelled")
        if order.status == OrderStatus.REFUNDED:
            raise ConflictError("Cannot cancel a refunded order")

        for item in order.items:
            await self._inventory.adjust(
                organization_id,
                product_id=item.product_id,
                branch_id=order.branch_id,
                delta=item.quantity,
                movement_type=StockMovementType.IN,
                reason=f"Cancel {order.code}",
                reference=order.code,
                performed_by=performed_by,
            )

        order.status = OrderStatus.CANCELLED
        await self._orders.commit()
        return await self._orders.refresh_with_items(order)
