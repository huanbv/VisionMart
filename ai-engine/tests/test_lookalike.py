from __future__ import annotations

import numpy as np

from app.services.lookalike import (
    color_hint_7up_sting,
    reset_slots,
    skus_are_lookalikes,
    stabilize_lookalikes,
)
from app.services.person_tracker import TrackedObject


def _box(cls: str, conf: float, x1: float, y1: float, x2: float, y2: float, tid: int = 1) -> TrackedObject:
    return TrackedObject(
        track_id=tid,
        class_name=cls,
        confidence=conf,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
    )


def _paint_bottle(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int, bgr: tuple[int, int, int]) -> None:
    frame[y1:y2, x1:x2] = bgr


def test_green_crop_is_7up():
    crop = np.zeros((160, 70, 3), dtype=np.uint8)
    crop[:, :] = (40, 210, 40)
    assert color_hint_7up_sting(crop) == "du_7u"


def test_red_crop_is_sting():
    crop = np.zeros((160, 70, 3), dtype=np.uint8)
    crop[:, :] = (20, 20, 210)
    assert color_hint_7up_sting(crop) == "du_sti"


def test_gray_crop_is_inconclusive():
    crop = np.full((160, 70, 3), 90, dtype=np.uint8)
    assert color_hint_7up_sting(crop) is None


def test_color_overrides_wrong_yolo_class():
    reset_slots()
    frame = np.full((400, 400, 3), 30, dtype=np.uint8)
    _paint_bottle(frame, 100, 80, 160, 280, (40, 210, 40))
    det = _box("du_sti", 0.48, 100, 80, 160, 280)
    out = stabilize_lookalikes("cam-a", [det], frame, now=1.0)
    assert len(out) == 1
    assert out[0].class_name == "du_7u"


def test_sticky_holds_when_yolo_flips_without_color():
    reset_slots()
    gray = np.full((400, 400, 3), 80, dtype=np.uint8)
    first = _box("du_7u", 0.46, 100, 80, 160, 280, tid=11)
    second = _box("du_sti", 0.49, 104, 84, 158, 276, tid=12)
    stabilize_lookalikes("cam-b", [first], gray, now=10.0)
    out = stabilize_lookalikes("cam-b", [second], gray, now=10.2)
    assert out[0].class_name == "du_7u"


def test_overlapping_7up_and_sting_collapse_to_color_winner():
    reset_slots()
    frame = np.full((400, 400, 3), 30, dtype=np.uint8)
    _paint_bottle(frame, 200, 100, 280, 300, (20, 20, 210))
    seven = _box("du_7u", 0.50, 200, 100, 280, 300, tid=1)
    sting = _box("du_sti", 0.44, 210, 110, 270, 290, tid=2)
    out = stabilize_lookalikes("cam-c", [seven, sting], frame, now=20.0)
    names = [d.class_name for d in out]
    assert names == ["du_sti"]


def test_side_by_side_bottles_keep_both():
    reset_slots()
    frame = np.full((400, 500, 3), 30, dtype=np.uint8)
    _paint_bottle(frame, 40, 80, 110, 280, (40, 210, 40))
    _paint_bottle(frame, 260, 80, 330, 280, (20, 20, 210))
    seven = _box("du_sti", 0.45, 40, 80, 110, 280, tid=1)
    sting = _box("du_7u", 0.45, 260, 80, 330, 280, tid=2)
    out = stabilize_lookalikes("cam-d", [seven, sting], frame, now=30.0)
    assert {d.class_name for d in out} == {"du_7u", "du_sti"}


def test_offset_boxes_on_one_bottle_collapse_to_one():
    """Live: du_7u 0.535 and du_sti 0.419 on one bottle ~60px apart."""
    reset_slots()
    gray = np.full((400, 400, 3), 80, dtype=np.uint8)
    seven = _box("du_7u", 0.535, 80, 100, 160, 300, tid=1)
    sting = _box("du_sti", 0.419, 140, 110, 220, 290, tid=2)
    out = stabilize_lookalikes("cam-offset", [seven, sting], gray, now=40.0)
    assert len(out) == 1
    assert out[0].class_name == "du_7u"


def test_sticky_survives_multi_second_miss():
    reset_slots()
    gray = np.full((400, 400, 3), 80, dtype=np.uint8)
    first = _box("du_7u", 0.46, 100, 80, 160, 280, tid=11)
    later = _box("du_sti", 0.49, 104, 84, 158, 276, tid=12)
    stabilize_lookalikes("cam-ttl", [first], gray, now=10.0)
    out = stabilize_lookalikes("cam-ttl", [later], gray, now=16.0)
    assert out[0].class_name == "du_7u"


def test_weak_color_does_not_flip_sticky():
    reset_slots()
    gray = np.full((400, 400, 3), 80, dtype=np.uint8)
    first = _box("du_7u", 0.70, 100, 80, 160, 280, tid=1)
    stabilize_lookalikes("cam-weak", [first], gray, now=1.0)
    mixed = np.full((400, 400, 3), 80, dtype=np.uint8)
    mixed[80:280, 100:130] = (40, 210, 40)
    mixed[80:280, 130:160] = (20, 20, 210)
    flip = _box("du_sti", 0.48, 100, 80, 160, 280, tid=2)
    out = stabilize_lookalikes("cam-weak", [flip], mixed, now=1.2)
    assert out[0].class_name == "du_7u"


def test_lookalike_sku_helper():
    assert skus_are_lookalikes("DU-7U", "DU-STI")
    assert not skus_are_lookalikes("DU-7U", "DU-7U")
    assert not skus_are_lookalikes("DU-7U", "MG-HH")


def test_bridge_treats_7up_sting_as_same_physical_product():
    from app.api import frame as frame_mod

    frame_mod._PHYSICAL_PRODUCTS["cam-bridge"] = {
        "DU-7U:1:1": {
            "sku": "DU-7U",
            "cx": 200.0,
            "cy": 200.0,
            "last_seen": 50.0,
        }
    }
    hit = frame_mod._find_bridge_match(
        "cam-bridge", "DU-STI", 205.0, 198.0, now=50.4, claimed_this_frame=set()
    )
    assert hit == "DU-7U:1:1"
    frame_mod._PHYSICAL_PRODUCTS.pop("cam-bridge", None)
