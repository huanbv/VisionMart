from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app.services.review_capture import (
    _annotate_and_crop,
    is_product_review_class,
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
