"""Product router: CRUD scoped to the current tenant."""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.session import get_session
from app.dependencies.auth import CurrentUser, get_current_user, require_roles
from app.modules.catalog.application.services import ProductService
from app.modules.catalog.infrastructure.repositories import (
    SqlAlchemyCategoryRepository,
    SqlAlchemyProductRepository,
)
from app.modules.catalog.schemas.product import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)

router = APIRouter(prefix="/products", tags=["catalog"])


def _service(session: AsyncSession) -> ProductService:
    return ProductService(
        products=SqlAlchemyProductRepository(session),
        categories=SqlAlchemyCategoryRepository(session),
    )


@router.get("", response_model=ProductListResponse)
async def list_products(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None, max_length=120),
    category_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProductListResponse:
    items, total = await _service(session).list(
        current.organization_id,
        skip=skip,
        limit=limit,
        search=search,
        category_id=category_id,
        is_active=is_active,
    )
    return ProductListResponse(
        items=[ProductResponse.model_validate(p) for p in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    try:
        prod = await _service(session).create(
            current.organization_id,
            sku=payload.sku,
            name=payload.name,
            category_id=payload.category_id,
            barcode=payload.barcode,
            description=payload.description,
            unit_price=payload.unit_price,
            currency=payload.currency,
            attributes=payload.attributes,
            image_url=payload.image_url,
            is_active=payload.is_active,
        )
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProductResponse.model_validate(prod)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    try:
        prod = await _service(session).get(current.organization_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProductResponse.model_validate(prod)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    def _maybe(value, unset: bool):
        if unset:
            return None
        return value if value is not None else ...

    try:
        prod = await _service(session).update(
            current.organization_id,
            product_id,
            sku=payload.sku,
            name=payload.name,
            category_id=_maybe(payload.category_id, payload.category_unset),
            barcode=_maybe(payload.barcode, payload.barcode_unset),
            description=_maybe(payload.description, payload.description_unset),
            unit_price=payload.unit_price,
            currency=payload.currency,
            attributes=_maybe(payload.attributes, payload.attributes_unset),
            image_url=_maybe(payload.image_url, payload.image_url_unset),
            is_active=payload.is_active,
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ProductResponse.model_validate(prod)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_product(
    product_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await _service(session).delete(current.organization_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------
# Tải ảnh sản phẩm
#
# Trước đây trường `image_url` chỉ nhận một URL dán tay, nghĩa là ảnh phải
# được host ở đâu đó khác trước — bất tiện, và tạo ra phụ thuộc vào một
# nơi lưu trữ ngoài tầm kiểm soát: link chết thì sản phẩm mất ảnh, và
# không có cách nào biết trước.
#
# Hệ thống đã có MinIO và đã dùng nó cho ảnh huấn luyện, nên endpoint này
# chỉ tái dùng đúng đường đó. `image_url` vẫn giữ nguyên kiểu và ý nghĩa,
# nên mọi client cũ (kể cả cái đang dán URL ngoài) tiếp tục chạy —
# đây là thêm một cách, không phải thay cách cũ.
# --------------------------------------------------------------------
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_EXT_BY_IMAGE_TYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_MAX_PRODUCT_IMAGE_BYTES = 8 * 1024 * 1024


@router.post("/{product_id}/image", response_model=ProductResponse)
async def upload_product_image(
    product_id: uuid.UUID,
    file: UploadFile = File(...),
    current: CurrentUser = Depends(require_roles("super_admin", "org_admin")),
    session: AsyncSession = Depends(get_session),
) -> ProductResponse:
    """Tải ảnh đại diện sản phẩm lên MinIO và gán vào `image_url`.

    Lưu ý về phạm vi: đây là ảnh *hiển thị trong danh mục*, KHÔNG phải ảnh
    huấn luyện. Ảnh huấn luyện đi qua `/ai/training/images` và nằm ở bảng
    riêng, vì hai loại có vòng đời khác nhau — đổi ảnh hiển thị không được
    phép làm thay đổi tập dữ liệu mà một mô hình đã được huấn luyện trên
    đó.
    """
    from app.services.object_storage import MinioStorage, ObjectStorageError

    service = _service(session)
    # get() ném NotFoundError chứ không trả None — kiểm tra `is None` sẽ
    # không bao giờ chạy tới, và ngoại lệ thoát ra thành 500 thay vì 404.
    try:
        await service.get(current.organization_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Chỉ nhận JPEG/PNG/WebP, nhận được: {content_type or 'không rõ'}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="File rỗng")
    if len(content) > _MAX_PRODUCT_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Ảnh vượt {_MAX_PRODUCT_IMAGE_BYTES // (1024 * 1024)}MB",
        )

    ext = _EXT_BY_IMAGE_TYPE[content_type]
    # UUID mới mỗi lần tải, không ghi đè theo product_id: nếu ghi đè, ảnh
    # cũ vẫn nằm trong cache trình duyệt và CDN, nên người dùng đổi ảnh mà
    # vẫn thấy ảnh cũ — một lỗi rất khó chẩn đoán.
    key = f"products/{current.organization_id}/{product_id}/{uuid.uuid4()}.{ext}"

    storage = MinioStorage()
    try:
        await storage.put(key, content, content_type=content_type)
    except ObjectStorageError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Lỗi lưu trữ: {exc}"
        ) from exc

    try:
        updated = await service.update(
            current.organization_id, product_id, image_url=key
        )
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProductResponse.model_validate(updated)


@router.get("/{product_id}/image")
async def get_product_image(
    product_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Trả về ảnh sản phẩm.

    Chuyển hướng sang link ký sẵn khi ảnh nằm trong MinIO, và sang chính
    URL đó khi nó là link ngoài. Nhờ vậy frontend chỉ cần một địa chỉ duy
    nhất cho cả hai kiểu, không phải tự đoán ảnh đang được lưu ở đâu.
    """
    from fastapi.responses import RedirectResponse

    from app.services.object_storage import MinioStorage, ObjectStorageError

    try:
        product = await _service(session).get(current.organization_id, product_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if not product.image_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Sản phẩm chưa có ảnh")

    if product.image_url.startswith(("http://", "https://")):
        return RedirectResponse(product.image_url)

    try:
        url = await MinioStorage().presigned_get(product.image_url)
    except ObjectStorageError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail=f"Lỗi lưu trữ: {exc}"
        ) from exc
    return RedirectResponse(url)
