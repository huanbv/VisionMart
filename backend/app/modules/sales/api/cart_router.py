"""REST router for shopping carts (manual + auto-checkout by AI)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user
from app.dependencies.providers import get_event_bus
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyProductRepository,
)
from app.modules.inventory.application.services import InventoryService
from app.modules.inventory.infrastructure.repositories import (
    SqlAlchemyInventoryRepository,
    SqlAlchemyStockMovementRepository,
)
from app.modules.sales.application import cart_realtime as _cart_realtime  # noqa: F401
from app.modules.sales.application.cart_service import (
    CartService,
    compute_overall_confidence,
)
from app.modules.sales.application.checkout_service import CheckoutService
from app.modules.sales.application.payment import build_payment_gateway
from app.modules.sales.infrastructure.models import CartStatus, ShoppingCart
from app.modules.sales.infrastructure.repositories import (
    SqlAlchemyCartRepository,
    SqlAlchemyOrderItemRepository,
    SqlAlchemyOrderRepository,
)
from app.modules.sales.schemas.cart import (
    CartAddLineRequest,
    CartCheckoutQrResponse,
    CartCheckoutResponse,
    CartCreateRequest,
    CartLine,
    CartListResponse,
    CartResponse,
    CartRetagLineRequest,
    CartRetagLineResponse,
)
from app.modules.tenancy.infrastructure.repositories import (
    SqlAlchemyBranchRepository,
)
from app.services.qr import render_qr_svg

router = APIRouter(prefix="/carts", tags=["sales"])


def build_cart_service(session: AsyncSession) -> CartService:
    return CartService(
        carts=SqlAlchemyCartRepository(session),
        inventories=SqlAlchemyInventoryRepository(session),
        products=SqlAlchemyProductRepository(session),
        branches=SqlAlchemyBranchRepository(session),
        event_bus=get_event_bus(),
    )


def build_checkout_service(session: AsyncSession) -> CheckoutService:
    inventory_service = InventoryService(
        SqlAlchemyInventoryRepository(session),
        SqlAlchemyStockMovementRepository(session),
        SqlAlchemyProductRepository(session),
        SqlAlchemyBranchRepository(session),
    )
    return CheckoutService(
        carts=SqlAlchemyCartRepository(session),
        inventories=SqlAlchemyInventoryRepository(session),
        inventory_service=inventory_service,
        orders=SqlAlchemyOrderRepository(session),
        order_items=SqlAlchemyOrderItemRepository(session),
        event_bus=get_event_bus(),
        payment_gateway=build_payment_gateway(),
    )


def _line_to_schema(raw: dict) -> CartLine:
    payload = dict(raw)
    payload["has_photo"] = bool(payload.get("photo_key"))
    payload.pop("photo_key", None)
    return CartLine.model_validate(payload)


def _cart_to_response(cart: ShoppingCart) -> CartResponse:
    raw_lines = cart.items or []
    lines: list[CartLine] = [_line_to_schema(raw) for raw in raw_lines]
    return CartResponse(
        id=cart.id,
        organization_id=cart.organization_id,
        branch_id=cart.branch_id,
        customer_id=cart.customer_id,
        session_id=cart.session_id,
        status=cart.status,
        source=cart.source,
        total_amount=cart.total_amount,
        currency=cart.currency,
        lines=lines,
        overall_confidence=compute_overall_confidence(raw_lines),
        has_customer_photo=bool(cart.customer_photo_key),
        has_scan_photo=bool(cart.scan_photo_key),
        expires_at=cart.expires_at,
        converted_at=cart.converted_at,
        checkout_requested_at=getattr(cart, "checkout_requested_at", None),
        created_at=cart.created_at,
        updated_at=cart.updated_at,
    )


@router.get("", response_model=CartListResponse)
async def list_carts(
    branch_id: uuid.UUID | None = None,
    cart_status: CartStatus | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartListResponse:
    rows, total = await build_cart_service(session).list(
        current.organization_id,
        branch_id=branch_id,
        status=cart_status,
        skip=skip,
        limit=limit,
    )
    return CartListResponse(
        items=[_cart_to_response(c) for c in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=CartResponse, status_code=status.HTTP_201_CREATED)
async def create_cart(
    payload: CartCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).create(
            current.organization_id,
            branch_id=payload.branch_id,
            customer_id=payload.customer_id,
            session_id=payload.session_id,
            source=payload.source,
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return _cart_to_response(cart)


@router.get("/{cart_id}", response_model=CartResponse)
async def get_cart(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).get(current.organization_id, cart_id)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return _cart_to_response(cart)


@router.get("/{cart_id}/customer-photo")
async def get_cart_customer_photo(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Ảnh crop người (chủ giỏ hàng) do ai-engine chụp lúc gán chủ sở hữu —
    xem ai-engine/app/api/frame.py, nhánh checkout.

    Stream bytes thẳng qua backend (như GET /detections/{id}/image) thay vì
    302 redirect sang link ký sẵn MinIO: trình duyệt theo redirect này vẫn
    gắn kèm header Authorization (cùng origin qua location /visionmart/
    của nginx), trong khi presigned URL đã tự có chữ ký AWS4 riêng trong
    query string — MinIO từ chối thẳng request có CẢ HAI kiểu xác thực
    ("multiple authentication types"). Stream tránh hẳn vấn đề này."""
    from app.services.object_storage import MinioStorage

    try:
        cart = await build_cart_service(session).get(current.organization_id, cart_id)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    if not cart.customer_photo_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Giỏ hàng chưa có ảnh khách")

    storage = MinioStorage()

    def _fetch() -> bytes:
        client = storage._get_client()
        obj = client.get_object(storage._settings.MINIO_BUCKET, cart.customer_photo_key)
        try:
            return obj.read()
        finally:
            obj.close()
            obj.release_conn()

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Lỗi lưu trữ: {exc}"
        ) from exc

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{cart_id}/scan-photo")
async def get_cart_scan_photo(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Ảnh Tải ảnh / Chụp & Quét đã vẽ box và tên sản phẩm — phóng to trên giỏ."""
    from app.services.object_storage import MinioStorage

    try:
        cart = await build_cart_service(session).get(current.organization_id, cart_id)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    if not cart.scan_photo_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Giỏ hàng chưa có ảnh quét")

    storage = MinioStorage()

    def _fetch() -> bytes:
        client = storage._get_client()
        obj = client.get_object(storage._settings.MINIO_BUCKET, cart.scan_photo_key)
        try:
            return obj.read()
        finally:
            obj.close()
            obj.release_conn()

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Lỗi lưu trữ: {exc}"
        ) from exc

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/{cart_id}/lines/{line_id}/photo")
async def get_cart_line_photo(
    cart_id: uuid.UUID,
    line_id: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Crop cận cảnh sản phẩm lúc AI detect — đính cạnh tên trong danh sách giỏ."""
    from app.services.object_storage import MinioStorage

    try:
        cart = await build_cart_service(session).get(current.organization_id, cart_id)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    line = next(
        (li for li in (cart.items or []) if str(li.get("line_id")) == line_id),
        None,
    )
    key = (line or {}).get("photo_key") if line else None
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Dòng giỏ chưa có ảnh crop")

    storage = MinioStorage()

    def _fetch() -> bytes:
        client = storage._get_client()
        obj = client.get_object(storage._settings.MINIO_BUCKET, key)
        try:
            return obj.read()
        finally:
            obj.close()
            obj.release_conn()

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Lỗi lưu trữ: {exc}"
        ) from exc

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/{cart_id}/lines", response_model=CartResponse)
async def add_cart_line(
    cart_id: uuid.UUID,
    payload: CartAddLineRequest,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).add_line(
            current.organization_id,
            cart_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            unit_price=payload.unit_price,
            added_via=payload.added_via,
            source_event_id=payload.source_event_id,
            confidence=1.0,  # a staff member typing this in IS the ground truth
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except (ValidationError, ConflictError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _cart_to_response(cart)


@router.delete("/{cart_id}/lines/{line_id}", response_model=CartResponse)
async def remove_cart_line(
    cart_id: uuid.UUID,
    line_id: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).remove_line(
            current.organization_id, cart_id, line_id
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ConflictError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _cart_to_response(cart)


@router.post("/{cart_id}/lines/{line_id}/sku", response_model=CartRetagLineResponse)
async def retag_cart_line(
    cart_id: uuid.UUID,
    line_id: str,
    payload: CartRetagLineRequest,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartRetagLineResponse:
    """Đổi SKU trên dòng giỏ. Có crop thì đưa vào tập học (checkout_mismatch)."""
    try:
        cart, correction = await build_cart_service(session).retag_line(
            current.organization_id,
            cart_id,
            line_id,
            product_id=payload.product_id,
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except (ValidationError, ConflictError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))

    added = False
    photo_key = (correction or {}).get("photo_key") if correction else None
    if photo_key:
        from app.modules.ai_training.application.review_service import (
            ReviewError,
            ReviewService,
        )
        from app.services.object_storage import MinioStorage

        try:
            conf_raw = correction.get("confidence") if correction else None
            try:
                conf = float(conf_raw) if conf_raw is not None else None
            except (TypeError, ValueError):
                conf = None
            await ReviewService(session, MinioStorage()).record_human_sku_correction(
                organization_id=current.organization_id,
                crop_key=str(photo_key),
                confirmed_product_id=correction["confirmed_product_id"],
                reviewed_by=current.user_id,
                predicted_product_id=correction.get("predicted_product_id"),
                predicted_class=correction.get("predicted_sku"),
                confirmed_sku=correction.get("confirmed_sku"),
                confidence=conf,
            )
            added = True
        except ReviewError:
            added = False
        except Exception:  # noqa: BLE001 — sửa đơn không phụ thuộc MinIO/học
            import logging

            logging.getLogger(__name__).exception(
                "sku correction saved on cart but not in training cart=%s line=%s",
                cart_id,
                line_id,
            )
            added = False

    return CartRetagLineResponse(
        cart=_cart_to_response(cart),
        added_to_training=added,
    )


@router.post("/{cart_id}/checkout", response_model=CartCheckoutResponse)
async def checkout_cart(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartCheckoutResponse:
    try:
        cart, order = await build_checkout_service(session).checkout(
            current.organization_id, cart_id, performed_by=current.user_id
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except (ValidationError, ConflictError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return CartCheckoutResponse(
        cart_id=cart.id,
        order_id=order.id,
        order_code=order.code,
        total_amount=order.total_amount,
        currency=order.currency,
    )


@router.get("/{cart_id}/checkout-qr", response_model=CartCheckoutQrResponse)
async def get_checkout_qr(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartCheckoutQrResponse:
    """For the checkout-zone customer-facing screen: shows this so the
    shopper can scan it with their own phone to review + confirm their
    bill. Only meaningful while the cart is PENDING_CHECKOUT."""
    checkout_service = build_checkout_service(session)
    try:
        cart = await checkout_service.get(current.organization_id, cart_id)
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    if cart.status != CartStatus.PENDING_CHECKOUT or not cart.checkout_token:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cart is not awaiting checkout confirmation",
        )
    confirm_url = checkout_service.build_confirm_url(cart.checkout_token)
    return CartCheckoutQrResponse(
        cart_id=cart.id,
        checkout_token=cart.checkout_token,
        confirm_url=confirm_url,
        qr_svg=render_qr_svg(confirm_url),
        expires_at=cart.expires_at,
    )


@router.post("/{cart_id}/confirm-checkout", response_model=CartCheckoutResponse)
async def confirm_checkout_staff(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartCheckoutResponse:
    """Staff confirms on behalf of a walk-in customer who has no phone/QR —
    staff's own login + presence is the confirmation here."""
    try:
        cart, order = await build_checkout_service(session).confirm_checkout_staff(
            current.organization_id, cart_id, performed_by=current.user_id
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except (ValidationError, ConflictError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return CartCheckoutResponse(
        cart_id=cart.id,
        order_id=order.id,
        order_code=order.code,
        total_amount=order.total_amount,
        currency=order.currency,
    )


@router.post("/{cart_id}/cancel-checkout", response_model=CartResponse)
async def cancel_checkout(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_checkout_service(session).cancel_pending_checkout(
            current.organization_id, cart_id
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ConflictError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _cart_to_response(cart)


@router.post("/{cart_id}/abandon", response_model=CartResponse)
async def abandon_cart(
    cart_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CartResponse:
    try:
        cart = await build_cart_service(session).abandon(
            current.organization_id, cart_id
        )
    except NotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except ConflictError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e))
    return _cart_to_response(cart)


@router.post("/bulk-abandon")
async def bulk_abandon_carts(
    payload: dict,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    cart_ids = payload.get("cart_ids", [])
    service = build_cart_service(session)
    count = 0
    errors = []
    if not cart_ids:
        # "Xóa tất cả" — không giới hạn 1 trang. list() vẫn phân trang nội bộ
        # (an toàn cho bộ nhớ/DB), nhưng vòng lặp này gom HẾT các trang thay
        # vì chỉ lấy trang đầu — trước đây limit=100 khiến nút "Xóa tất cả"
        # chỉ dọn được 100 giỏ/loại mỗi lần bấm, phải bấm hàng chục lần mới
        # hết một backlog vài nghìn giỏ tồn đọng.
        branch_id = payload.get("branch_id")
        b_id = uuid.UUID(str(branch_id)) if branch_id else None
        cart_ids = []
        for cart_status in (CartStatus.ACTIVE, CartStatus.PENDING_CHECKOUT):
            skip = 0
            while True:
                page, _ = await service.list(
                    current.organization_id, branch_id=b_id, status=cart_status,
                    skip=skip, limit=500,
                )
                if not page:
                    break
                cart_ids.extend(c.id for c in page)
                skip += len(page)
                if len(page) < 500:
                    break

    for cid in cart_ids:
        try:
            uid = uuid.UUID(str(cid))
            await service.abandon(current.organization_id, uid)
            count += 1
        except Exception as e:
            errors.append(f"{cid}: {e}")

    # Also notify AI Engine to reset checkout session if active
    try:
        import httpx
        from app.core.config import get_settings
        st = get_settings()
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                f"{st.AI_ENGINE_BASE_URL}/ai/reset-session",
                headers={"X-AI-Engine-Key": st.AI_ENGINE_API_KEY},
            )
    except Exception:
        pass

    return {"status": "ok", "abandoned": count, "errors": errors}
