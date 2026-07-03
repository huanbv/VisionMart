"""SQLAlchemy repositories for the Sales bounded context."""

from __future__ import annotations

import uuid
from datetime import datetime

from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError
from app.modules.sales.infrastructure.models import (
    Order,
    OrderItem,
    OrderStatus,
    ShoppingCart,
    CartStatus,
)
from app.modules.tenancy.infrastructure.models import Branch


class SqlAlchemyOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        branch_id: uuid.UUID | None = None,
        status: OrderStatus | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> tuple[list[tuple[Order, Branch]], int]:
        base = (
            select(Order, Branch)
            .join(Branch, Branch.id == Order.branch_id)
            .where(
                Order.organization_id == organization_id,
                Order.is_deleted.is_(False),
            )
        )
        if branch_id is not None:
            base = base.where(Order.branch_id == branch_id)
        if status is not None:
            base = base.where(Order.status == status)
        if date_from is not None:
            base = base.where(Order.created_at >= date_from)
        if date_to is not None:
            base = base.where(Order.created_at <= date_to)
        if search:
            base = base.where(func.lower(Order.code).like(f"%{search.lower()}%"))

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(Order.created_at.desc()).offset(skip).limit(limit)
            )
        ).all()
        return [(r[0], r[1]) for r in rows], int(total)

    async def get_by_id(
        self, organization_id: uuid.UUID, order_id: uuid.UUID
    ) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(
                Order.id == order_id,
                Order.organization_id == organization_id,
                Order.is_deleted.is_(False),
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_cart_id(self, cart_id: uuid.UUID) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.cart_id == cart_id, Order.is_deleted.is_(False))
            .order_by(Order.created_at.desc())
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def next_code(self, organization_id: uuid.UUID) -> str:
        """Best-effort next code (COUNT-then-format). Not safe on its own
        under concurrency — two checkouts started at nearly the same moment
        can compute the identical code before either has inserted its Order.
        Callers that actually persist an Order must go through
        ``add_with_unique_code`` below, which retries on the resulting
        unique-constraint collision instead of letting one of the two
        requests fail with an unhandled 500."""
        today = datetime.utcnow().strftime("%Y%m%d")
        prefix = f"ORD-{today}-"
        stmt = select(func.count()).where(
            Order.organization_id == organization_id,
            Order.code.like(f"{prefix}%"),
        )
        count = (await self._session.execute(stmt)).scalar_one()
        return f"{prefix}{int(count) + 1:04d}"

    async def add(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.flush()
        return order

    async def add_with_unique_code(
        self,
        organization_id: uuid.UUID,
        build_order: Callable[[str], Order],
        *,
        max_attempts: int = 5,
    ) -> Order:
        """Persist an Order whose ``code`` comes from ``next_code()``,
        retrying with a freshly generated code if it collides with one
        another concurrent request just inserted (see ``next_code``'s
        docstring for why a collision is possible even though each caller
        checked availability first).

        Each attempt runs inside its own SAVEPOINT (``session.begin_nested``)
        so a collision only unwinds that one failed INSERT — not the whole
        transaction. That matters here because the caller (CheckoutService)
        is mid-transaction on a row-locked ShoppingCart at this point; a
        full transaction rollback would also drop that lock and any other
        work already flushed in this request. Verified against a real
        SQLAlchemy async session (SQLite) before wiring in: a failed nested
        flush leaves the outer session fully usable for the retry and for
        whatever the caller does afterward.
        """
        last_error: IntegrityError | None = None
        for _attempt in range(max_attempts):
            code = await self.next_code(organization_id)
            order = build_order(code)
            try:
                async with self._session.begin_nested():
                    self._session.add(order)
                    await self._session.flush()
                return order
            except IntegrityError as exc:
                last_error = exc
                continue
        raise ConflictError(
            f"Could not generate a unique order code after {max_attempts} attempts"
        ) from last_error

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh_with_items(self, order: Order) -> Order:
        stmt = (
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order.id)
        )
        return (await self._session.execute(stmt)).scalar_one()


class SqlAlchemyOrderItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, item: OrderItem) -> OrderItem:
        self._session.add(item)
        await self._session.flush()
        return item


class SqlAlchemyCartRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, cart: ShoppingCart) -> ShoppingCart:
        self._session.add(cart)
        await self._session.flush()
        return cart

    async def get_by_id(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart | None:
        stmt = select(ShoppingCart).where(
            ShoppingCart.id == cart_id,
            ShoppingCart.organization_id == organization_id,
            ShoppingCart.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_for_update(
        self, organization_id: uuid.UUID, cart_id: uuid.UUID
    ) -> ShoppingCart | None:
        """Same as ``get_by_id`` but takes a row lock (SELECT ... FOR
        UPDATE).

        Every checkout state transition (ACTIVE -> PENDING_CHECKOUT,
        PENDING_CHECKOUT -> CONVERTED/ACTIVE) is a read-check-write on this
        row. Without the lock, two concurrent requests for the same cart
        (e.g. a customer's QR-page tap racing a staff "confirm on behalf of"
        click, or a double-tapped confirm button) can both read the cart as
        PENDING_CHECKOUT, both pass the status check, and both proceed to
        finalize — creating two Orders and double-deducting inventory for
        one cart. Mirrors
        ``inventory get_by_product_branch_for_update``.
        """
        stmt = (
            select(ShoppingCart)
            .where(
                ShoppingCart.id == cart_id,
                ShoppingCart.organization_id == organization_id,
                ShoppingCart.is_deleted.is_(False),
            )
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_open_for_session(
        self,
        organization_id: uuid.UUID,
        branch_id: uuid.UUID,
        session_id: str,
    ) -> ShoppingCart | None:
        stmt = select(ShoppingCart).where(
            ShoppingCart.organization_id == organization_id,
            ShoppingCart.branch_id == branch_id,
            ShoppingCart.session_id == session_id,
            ShoppingCart.status == CartStatus.ACTIVE,
            ShoppingCart.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_org(
        self,
        organization_id: uuid.UUID,
        *,
        branch_id: uuid.UUID | None = None,
        status: CartStatus | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[ShoppingCart], int]:
        base = select(ShoppingCart).where(
            ShoppingCart.organization_id == organization_id,
            ShoppingCart.is_deleted.is_(False),
        )
        if branch_id is not None:
            base = base.where(ShoppingCart.branch_id == branch_id)
        if status is not None:
            base = base.where(ShoppingCart.status == status)
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        rows = (
            (
                await self._session.execute(
                    base.order_by(ShoppingCart.created_at.desc())
                    .offset(skip)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    async def list_expired(
        self, cutoff: datetime, *, limit: int = 200
    ) -> list[ShoppingCart]:
        stmt = (
            select(ShoppingCart)
            .where(
                ShoppingCart.status == CartStatus.ACTIVE,
                ShoppingCart.expires_at.is_not(None),
                ShoppingCart.expires_at < cutoff,
                ShoppingCart.is_deleted.is_(False),
            )
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_pending_checkout_expired(
        self, cutoff: datetime, *, limit: int = 200
    ) -> list[ShoppingCart]:
        """PENDING_CHECKOUT carts whose confirmation window has lapsed —
        nobody (customer via QR, or staff) confirmed in time."""
        stmt = (
            select(ShoppingCart)
            .where(
                ShoppingCart.status == CartStatus.PENDING_CHECKOUT,
                ShoppingCart.expires_at.is_not(None),
                ShoppingCart.expires_at < cutoff,
                ShoppingCart.is_deleted.is_(False),
            )
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_checkout_token(
        self, token: str
    ) -> ShoppingCart | None:
        """Look up a cart by its public confirm-page token. Deliberately not
        scoped by organization — the token itself (unguessable,
        `secrets.token_urlsafe`) is the credential, since the customer
        hitting `/shop/checkout/{token}` has no org/user context."""
        stmt = select(ShoppingCart).where(
            ShoppingCart.checkout_token == token,
            ShoppingCart.is_deleted.is_(False),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_checkout_token_for_update(
        self, token: str
    ) -> ShoppingCart | None:
        """Locked variant of ``get_by_checkout_token`` — see
        ``get_by_id_for_update`` for why. This is the one that matters most
        in practice: it's the public, unauthenticated confirm endpoint a
        customer's phone could plausibly double-submit (flaky mobile
        network retry, accidental double-tap)."""
        stmt = (
            select(ShoppingCart)
            .where(
                ShoppingCart.checkout_token == token,
                ShoppingCart.is_deleted.is_(False),
            )
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh(self, cart: ShoppingCart) -> None:
        await self._session.refresh(cart)
