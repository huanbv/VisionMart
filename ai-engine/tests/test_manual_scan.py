from __future__ import annotations

from app.api.frame import (
    _aggregate_manual_products,
    _reuse_recent_checkout_products,
    _sanitize_scan_session,
)
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


def test_missed_frame_keeps_recent_checkout_skus():
    first = [(_product(1, 0.82), "DU-STI"), (_product(2, 0.88), "DU-7U")]
    kept = _reuse_recent_checkout_products("cam-hold", first, now=10.0)
    assert kept == first
    held = _reuse_recent_checkout_products("cam-hold", [], now=14.0)
    assert [s for _, s in held] == ["DU-STI", "DU-7U"]
    expired = _reuse_recent_checkout_products("cam-hold", [], now=19.0)
    assert expired == []


def test_scan_session_token_is_reused_across_frames():
    assert _sanitize_scan_session("vmmh2k1") == "vmmh2k1"
    assert _sanitize_scan_session("vmmh2k1") == _sanitize_scan_session("vmmh2k1")
    assert _sanitize_scan_session("") is None
    assert _sanitize_scan_session("bad token!") is None
    assert _sanitize_scan_session("x" * 81) is None
