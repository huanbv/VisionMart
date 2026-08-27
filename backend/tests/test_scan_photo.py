from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image

from app.modules.sales.api.cart_router import _cart_to_response
from app.modules.sales.application.scan_photo import (
    annotate_scan_jpeg,
    detection_label,
    session_id_from_emitted,
)
from app.modules.sales.infrastructure.models import CartSource, CartStatus


def _rgb_jpeg(width: int = 80, height: int = 60, color: tuple[int, int, int] = (40, 40, 40)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_detection_label_prefers_catalog_name():
    assert detection_label({"name": "Sting đỏ", "sku": "DU-STI"}) == "Sting đỏ (DU-STI)"
    assert detection_label({"sku": "MG-HH"}) == "MG-HH"
    assert detection_label({"class_name": "mg_hh"}) == "mg_hh"


def test_session_id_from_emitted_manual_track():
    camera_id = uuid4()
    pipeline = {
        "emitted_events": [
            {
                "event": {
                    "event_type": "product_scanned",
                    "track_id": "manual-ab12cd34",
                },
                "backend": {"accepted": True},
            }
        ]
    }
    assert session_id_from_emitted(camera_id, pipeline) == (
        f"cam:{camera_id}:track:manual-ab12cd34"
    )


def test_session_id_from_emitted_empty():
    assert session_id_from_emitted(uuid4(), None) is None
    assert session_id_from_emitted(uuid4(), {"emitted_events": []}) is None


def test_annotate_scan_jpeg_draws_valid_jpeg():
    raw = _rgb_jpeg()
    out = annotate_scan_jpeg(
        raw,
        [
            {
                "name": "Hảo Hảo",
                "sku": "MG-HH",
                "bbox": {"x1": 10, "y1": 10, "x2": 40, "y2": 40},
            }
        ],
        source_width=80,
        source_height=60,
    )
    assert out is not None
    assert out[:2] == b"\xff\xd8"
    labeled = Image.open(BytesIO(out))
    assert labeled.size == (80, 60)


def test_cart_response_exposes_has_scan_photo_not_key():
    cart = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        branch_id=uuid4(),
        customer_id=None,
        session_id="cam:x:track:manual-1",
        status=CartStatus.ACTIVE,
        source=CartSource.AI_VISION,
        items=[],
        total_amount="0",
        currency="VND",
        customer_photo_key=None,
        scan_photo_key="carts/scan-frames/org/cart.jpg",
        expires_at=None,
        converted_at=None,
        checkout_requested_at=None,
        created_at="2026-08-27T00:00:00+00:00",
        updated_at="2026-08-27T00:00:00+00:00",
    )
    payload = _cart_to_response(cart)
    assert payload.has_scan_photo is True
    assert payload.checkout_requested_at is None
    dumped = payload.model_dump()
    assert "scan_photo_key" not in dumped
