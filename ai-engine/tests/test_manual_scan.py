from __future__ import annotations

from app.api.frame import _aggregate_manual_products
from app.services.person_tracker import TrackedObject


def _product(track_id: int, confidence: float) -> TrackedObject:
    return TrackedObject(
        track_id=track_id,
        class_name="du_sti",
        confidence=confidence,
        x1=float(track_id * 100),
        y1=10.0,
        x2=float(track_id * 100 + 50),
        y2=150.0,
    )


def test_same_sku_physical_products_become_cart_quantity():
    aggregated = _aggregate_manual_products(
        [
            (_product(1, 0.82), "DU-STI"),
            (_product(2, 0.91), "DU-STI"),
            (_product(3, 0.88), "DU-7U"),
        ]
    )

    assert aggregated == {
        "DU-STI": (2, 0.91),
        "DU-7U": (1, 0.88),
    }
