from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.modules.sales.application.cart_service import apply_sku_to_line


def test_apply_sku_to_line_keeps_crop_and_swaps_catalog():
    line_id = uuid4().hex
    raw = {
        "line_id": line_id,
        "product_id": str(uuid4()),
        "sku": "DU-STI",
        "product_name": "Sting",
        "quantity": 2,
        "unit_price": "8000",
        "subtotal": "16000",
        "added_via": "ai",
        "source_event_id": "evt-1",
        "confidence": 0.61,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "photo_key": "carts/product-crops/org/evt-1.jpg",
    }
    product = SimpleNamespace(
        id=uuid4(),
        sku="DU-7U",
        name="7Up",
        unit_price=Decimal("10000"),
    )
    updated = apply_sku_to_line(raw, product)
    assert updated["line_id"] == line_id
    assert updated["photo_key"] == "carts/product-crops/org/evt-1.jpg"
    assert updated["quantity"] == 2
    assert updated["sku"] == "DU-7U"
    assert updated["product_name"] == "7Up"
    assert updated["product_id"] == str(product.id)
    assert updated["unit_price"] == "10000"
    assert updated["subtotal"] == "20000"
    assert updated["confidence"] == 1.0
    assert updated["added_via"] == "staff_correction"
    assert updated["source_event_id"] == "evt-1"
    assert raw["sku"] == "DU-STI"
