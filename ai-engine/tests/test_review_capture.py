from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app.services.review_capture import (
    _annotate_and_crop,
    is_product_review_class,
    pick_product_for_review,
    pick_uncertain,
)


def test_furniture_is_not_a_review_class():
    assert is_product_review_class("dining table") is False
    assert is_product_review_class("chair") is False
    assert is_product_review_class("person") is False


def test_sku_and_bottle_are_review_classes():
    assert is_product_review_class("bottle") is True
    assert is_product_review_class("du_7u") is True
    assert is_product_review_class("DU-STI") is True


def test_pick_uncertain_skips_empty_counter_furniture():
    dets = [
        SimpleNamespace(class_name="dining table", confidence=0.15),
        SimpleNamespace(class_name="person", confidence=0.9),
    ]
    assert pick_uncertain(dets, 0.5) is None


def test_pick_uncertain_keeps_low_conf_sku():
    sku = SimpleNamespace(class_name="du_7u", confidence=0.22)
    dets = [
        SimpleNamespace(class_name="dining table", confidence=0.18),
        sku,
    ]
    assert pick_uncertain(dets, 0.5) is sku


def test_wood_crop_is_not_saved_as_training_image():
    wood = np.full((80, 120, 3), (42, 88, 145), dtype=np.uint8)
    det = SimpleNamespace(
        x1=10, y1=10, x2=90, y2=70, class_name="bottle", confidence=0.2
    )
    _annotated, crop = _annotate_and_crop(wood, det)
    assert crop is None


def _pay_zone_with_bottles():
    import cv2

    h, w = 240, 320
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    roi = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(
        roi,
        [np.array([[20, 60], [290, 60], [319, 220], [0, 220]], np.int32)],
        255,
    )
    yy, xx = np.indices((h, w))
    counter = np.stack(
        [35 + xx // 7, 55 + xx // 9, 105 + yy // 5], axis=2
    ).clip(1, 240).astype(np.uint8)
    frame[roi > 0] = counter[roi > 0]
    cv2.rectangle(frame, (100, 100), (124, 190), (30, 35, 210), -1)
    cv2.rectangle(frame, (150, 115), (179, 190), (50, 180, 45), -1)
    return frame


def test_review_picks_pay_zone_product_even_when_yolo_says_dining_table():
    frame = _pay_zone_with_bottles()
    dets = [
        SimpleNamespace(
            class_name="dining table",
            confidence=0.15,
            x1=0.0, y1=0.0, x2=319.0, y2=239.0,
        ),
        SimpleNamespace(
            class_name="person",
            confidence=0.9,
            x1=185.0, y1=60.0, x2=260.0, y2=200.0,
        ),
    ]
    picked = pick_product_for_review(frame, dets, 0.5)
    assert picked is not None
    assert (picked.x2 - picked.x1) < 0.5 * 320
    cx = (picked.x1 + picked.x2) / 2.0
    assert 90 <= cx <= 190


def test_empty_wood_pay_zone_is_not_queued():
    import cv2

    h, w = 240, 320
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    roi = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(
        roi,
        [np.array([[20, 60], [290, 60], [319, 220], [0, 220]], np.int32)],
        255,
    )
    yy, xx = np.indices((h, w))
    wood = np.stack(
        [35 + xx // 7, 55 + xx // 9, 105 + yy // 5], axis=2
    ).clip(1, 240).astype(np.uint8)
    frame[roi > 0] = wood[roi > 0]
    dets = [
        SimpleNamespace(
            class_name="dining table",
            confidence=0.15,
            x1=0.0, y1=0.0, x2=319.0, y2=239.0,
        )
    ]
    assert pick_product_for_review(frame, dets, 0.5) is None
