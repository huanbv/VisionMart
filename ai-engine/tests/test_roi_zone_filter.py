from __future__ import annotations

from app.vision.roi.zones import (
    RoiZone,
    box_fraction_in_zones,
    box_mostly_in_zones,
    zone_union_bbox,
)
from app.services.det_nms import dense_tile_origins


def _right_half_zone() -> list[RoiZone]:
    return [
        RoiZone(
            name="pay",
            zone_type="checkout",
            points=((0.5, 0.0), (1.0, 0.0), (1.0, 1.0), (0.5, 1.0)),
        )
    ]


def test_zone_union_bbox():
    bbox = zone_union_bbox(_right_half_zone(), 200, 100)
    assert bbox == (100, 0, 200, 100)


def test_box_entirely_outside_pay_zone_is_rejected():
    zones = _right_half_zone()
    # Statue on the left half of a 200×100 frame.
    assert box_fraction_in_zones(zones, 10, 20, 80, 90, 200, 100) == 0.0
    assert not box_mostly_in_zones(zones, 10, 20, 80, 90, 200, 100)


def test_box_inside_pay_zone_is_kept():
    zones = _right_half_zone()
    assert box_mostly_in_zones(zones, 120, 20, 180, 80, 200, 100)


def test_giant_box_spilling_out_of_pay_zone_is_rejected():
    """Label on the statue, box stretching into the counter — old center filter kept it."""
    zones = _right_half_zone()
    assert not box_mostly_in_zones(zones, 10, 10, 160, 90, 200, 100, min_frac=0.5)


def test_dense_tiles_stay_inside_roi():
    roi = (100, 20, 200, 80)
    tiles = dense_tile_origins(400, 200, layout="scan", roi_rect=roi)
    assert tiles
    for ox, oy, tw, th in tiles:
        assert ox >= 100
        assert oy >= 20
        assert ox < 200
        assert oy < 80
