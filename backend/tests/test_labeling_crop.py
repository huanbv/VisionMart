"""Unit tests for bbox relabeling after image crop."""

from types import SimpleNamespace

from app.modules.ai_training.application.labeling_service import (
    _normalize_rect,
    _transform_box_after_crop,
)


def test_normalize_rect():
    assert _normalize_rect(0.8, 0.2, 0.1, 0.9) == (0.1, 0.2, 0.8, 0.9)


def test_transform_box_fully_inside_crop():
    box = SimpleNamespace(cx=0.5, cy=0.5, w=0.2, h=0.2)
    out = _transform_box_after_crop(
        box,
        img_w=1000,
        img_h=800,
        crop_left=200,
        crop_top=100,
        crop_w=600,
        crop_h=500,
    )
    assert out is not None
    cx, cy, w, h = out
    assert abs(cx - 0.5) < 1e-6
    assert abs(cy - 0.6) < 1e-6
    assert abs(w - 0.2 * 1000 / 600) < 1e-6
    assert abs(h - 0.2 * 800 / 500) < 1e-6


def test_transform_box_clipped_outside_crop():
    box = SimpleNamespace(cx=0.05, cy=0.05, w=0.08, h=0.08)
    assert (
        _transform_box_after_crop(
            box,
            img_w=1000,
            img_h=800,
            crop_left=200,
            crop_top=100,
            crop_w=600,
            crop_h=500,
        )
        is None
    )
