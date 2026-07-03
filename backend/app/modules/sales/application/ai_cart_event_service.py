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
        if event.confidence < self._settings.CART_AI_MIN_CONFIDENCE:
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

        if event.event_type == AICartEventType.PRODUCT_PICKED_UP:
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
        )

    async def _resolve_product(self, event: AICartEventRequest) -> Product | None:
        if event.product_id is not None:
            return await self._products.get_by_id(event.organization_id, event.product_id)
        if event.product_sku:
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
