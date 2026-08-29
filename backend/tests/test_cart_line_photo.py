from datetime import datetime, timezone
from uuid import uuid4

from app.modules.sales.api.cart_router import _line_to_schema


def test_line_to_schema_sets_has_photo_and_hides_key():
    raw = {
        "line_id": uuid4().hex,
        "product_id": str(uuid4()),
        "sku": "DU-7U",
        "product_name": "7Up",
        "quantity": 1,
        "unit_price": "10000",
        "subtotal": "10000",
        "added_via": "ai",
        "source_event_id": "evt-1",
        "global_track_id": "g-1",
        "confidence": 1.0,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "photo_key": "carts/product-crops/org/evt-1.jpg",
    }
    line = _line_to_schema(raw)
    assert line.has_photo is True
    dumped = line.model_dump()
    assert "photo_key" not in dumped


def test_line_to_schema_without_photo():
    raw = {
        "line_id": uuid4().hex,
        "product_id": str(uuid4()),
        "sku": "DU-STI",
        "product_name": "Sting",
        "quantity": 1,
        "unit_price": "10000",
        "subtotal": "10000",
        "added_via": "ai",
        "confidence": 1.0,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    line = _line_to_schema(raw)
    assert line.has_photo is False
