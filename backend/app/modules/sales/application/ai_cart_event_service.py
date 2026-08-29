"""Translates AI Engine proposals into calls on CartService/CheckoutService.

AI never writes to cart/inventory/order tables directly. It POSTs a
proposal (`AICartEventRequest`); this service validates it, resolves
camera-scoped session/journey identity, and decides which
CartService/CheckoutService method that proposal maps to. AI's own code
(ai-engine/app/api/frame.py) has no idea any of this exists — it only knows
how to emit events and read back an accept/reject reason.

This is also the architectural boundary called for by the project's
constitution: AI's responsibility ends at proposing
`checkout_initiated` -> this service turns that into
`CheckoutService.request_checkout()` (freeze, no charge) and stops. It never
calls anything on `CheckoutService` that would confirm or pay.
"""

from __future__ import annotations

import asyncio

from app.config.settings import get_settings
from app.core.exceptions import ConflictError
from app.modules.catalog.infrastructure.models import Product
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.sales.application.cart_service import CartService
from app.modules.sales.application.checkout_service import CheckoutService
from app.modules.sales.application.visitor_linker import resolve_global_track_id
from app.modules.sales.infrastructure.models import CartSource, Order, ShoppingCart
from app.modules.sales.schemas.ai_events import AICartEventRequest, AICartEventType

_CART_LOCKS: dict[str, asyncio.Lock] = {}
_LOCK_MUTEX = asyncio.Lock()

async def _get_cart_lock(session_id: str) -> asyncio.Lock:
    async with _LOCK_MUTEX:
        if session_id not in _CART_LOCKS:
            _CART_LOCKS[session_id] = asyncio.Lock()
        return _CART_LOCKS[session_id]


class AiCartEventService:
    def __init__(
        self,
        cart_service: CartService,
        checkout_service: CheckoutService,
        products: SqlAlchemyProductRepository,
    ) -> None:
        self._carts = cart_service
        self._checkout = checkout_service
        self._products = products
        self._settings = get_settings()

    async def apply_ai_event(
        self, event: AICartEventRequest
    ) -> tuple[str, ShoppingCart | None, Order | None]:
        # Automatic grab-and-go (product_picked_up) is gated so a shaky
        # detection does not spawn a cart. product_scanned is an explicit
        # checkout/manual scan — the operator (or CHECKOUT_SCAN_MODE) already
        # decided to add the SKU, so a YOLO score of 0.3 must not silently
        # drop the event after the UI said "detected".
        if (
            event.event_type != AICartEventType.PRODUCT_SCANNED
            and event.confidence < self._settings.CART_AI_MIN_CONFIDENCE
        ):
            return "rejected_low_confidence", None, None

        # `event.track_id` from the real /ai/frame pipeline is already
        # camera-scoped (see ai-engine/app/api/frame.py::_track_key). This
        # extra camera_id prefix is defense-in-depth for callers that don't
        # go through that pipeline (e.g. the /cart/simulate demo endpoint) —
        # without it, two different cameras' local track "3" would resolve
        # to the same cart session and silently merge two shoppers' carts.
        camera_part = str(event.camera_id) if event.camera_id else "no-camera"
        session_id = f"cam:{camera_part}:track:{event.track_id}"

        # Best-effort anonymous journey linkage across cameras (analytics
        # only — never used for cart identity/billing, see visitor_linker.py
        # module docstring for the heuristic and its known limitations).
        # This is VisionMart's "Multi-camera Re-identification (without
        # biometric identity)" responsibility, not a customer identity.
        global_track_id = await resolve_global_track_id(
            settings=self._settings,
            organization_id=str(event.organization_id),
            branch_id=str(event.branch_id),
            camera_id=str(event.camera_id) if event.camera_id else None,
            local_track_id=event.track_id,
        )

        lock = await _get_cart_lock(session_id)
        async with lock:
            if event.event_type in (
                AICartEventType.PRODUCT_PICKED_UP,
                AICartEventType.PRODUCT_SCANNED,
            ):
                # Cả hai đều thêm một dòng hàng vào giỏ. product_scanned đến từ
                # camera quầy (không có track người), nhưng bước xử lý giống hệt.
                return await self._handle_picked_up(event, session_id, global_track_id)

            if event.event_type == AICartEventType.PRODUCT_RETURNED:
                return await self._handle_returned(event, session_id)

            if event.event_type == AICartEventType.CHECKOUT_INITIATED:
                return await self._handle_checkout_initiated(event, session_id)

            return "rejected_unknown_event", None, None

    async def _handle_picked_up(
        self, event: AICartEventRequest, session_id: str, global_track_id: str
    ) -> tuple[str, ShoppingCart | None, Order | None]:
        product = await self._resolve_product(event)
        if product is None:
            return "rejected_unknown_product", None, None
        cart = await self._get_or_create_ai_cart(event, session_id)

        # Dedup: với event đến từ quầy tự động (PRODUCT_SCANNED), mỗi SKU
        # chỉ được thêm 1 lần / phiên giỏ — ngay cả khi AI engine khởi động
        # lại và mất bộ nhớ đệm _CHECKOUT_SCANNED. Backend (DB) là nguồn
        # sự thật; nếu SKU đã có trong giỏ do AI thêm, bỏ qua lần này.
        # PRODUCT_PICKED_UP (kệ hàng) cho phép thêm nhiều lần vì khách có
        # thể nhặt nhiều món cùng loại nên không áp dụng quy tắc này.
        if event.event_type == AICartEventType.PRODUCT_SCANNED:
            existing_skus = {
                li.get("sku")
                for li in (cart.items or [])
                if li.get("added_via") == "ai"
            }
            if product.sku in existing_skus:
                return "accepted_already_in_cart", cart, None

        try:
            cart = await self._carts.add_line(
                event.organization_id,
                cart.id,
                product_id=product.id,
                quantity=event.quantity,
                unit_price=None,
                added_via="ai",
                source_event_id=event.event_id,
                global_track_id=global_track_id,
                confidence=event.confidence,
                photo_key=event.product_photo_key,
            )
        except ConflictError:
            return "rejected_insufficient_stock", cart, None
        return "accepted", cart, None

    async def _handle_returned(
        self, event: AICartEventRequest, session_id: str
    ) -> tuple[str, ShoppingCart | None, Order | None]:
        cart = await self._carts.get_open_cart_for_session(
            event.organization_id, event.branch_id, session_id
        )
        if cart is None:
            return "rejected_no_cart", None, None
        product = await self._resolve_product(event)
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
        cart = await self._carts.remove_line(event.organization_id, cart.id, match["line_id"])
        return "accepted", cart, None

    async def _handle_checkout_initiated(
        self, event: AICartEventRequest, session_id: str
    ) -> tuple[str, ShoppingCart | None, Order | None]:
        cart = await self._carts.get_open_cart_for_session(
            event.organization_id, event.branch_id, session_id
        )
        if cart is None or not (cart.items or []):
            return "rejected_empty_cart", cart, None
        # AI's involvement stops here: freeze the bill and wait for an
        # explicit human confirmation (customer scans the QR shown on the
        # checkout-zone screen, or staff confirms for a walk-in without a
        # phone). See CheckoutService.request_checkout().
        cart = await self._checkout.request_checkout(event.organization_id, cart.id)
        return "accepted_pending_confirmation", cart, None

    async def _get_or_create_ai_cart(
        self, event: AICartEventRequest, session_id: str
    ) -> ShoppingCart:
        existing = await self._carts.get_open_cart_for_session(
            event.organization_id, event.branch_id, session_id
        )
        if existing is not None:
            return existing
        return await self._carts.create(
            event.organization_id,
            branch_id=event.branch_id,
            customer_id=event.customer_id,
            session_id=session_id,
            source=CartSource.AI_VISION,
            customer_photo_key=event.customer_photo_key,
        )

    async def _resolve_product(self, event: AICartEventRequest) -> Product | None:
        if event.product_id is not None:
            return await self._products.get_by_id(event.organization_id, event.product_id)
        if event.product_sku:
            exact = await self._products.get_by_sku(
                event.organization_id, event.product_sku
            )
            if exact is not None:
                return exact
            items, _ = await self._products.list_for_org(
                event.organization_id,
                skip=0,
                limit=1,
                search=event.product_sku,
                is_active=True,
            )
            for item in items:
                if item.sku.lower() == event.product_sku.lower():
                    return item
        return None
