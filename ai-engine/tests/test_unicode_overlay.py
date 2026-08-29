from __future__ import annotations

import numpy as np

from app.vision.overlay.unicode_text import _font_path, draw_label, measure_text


def test_unicode_font_is_available_on_this_machine():
    assert _font_path(), "Need Tahoma/Arial (Windows) or DejaVu (Linux) for Vietnamese overlay"


def test_vietnamese_label_is_wider_than_question_marks():
    """Hershey putText turns ảo into ??? — three question marks are much narrower."""
    real_w, real_h = measure_text("Hảo Hảo", 16)
    fake_w, _ = measure_text("H???o H???o", 16)
    assert real_h >= 8
    # Real glyphs for ả/ả are not three ASCII question marks.
    assert real_w != fake_w


def test_draw_label_writes_pixels():
    frame = np.zeros((80, 200, 3), dtype=np.uint8)
    draw_label(frame, "Gấu Đỏ", x=4, y=4, bg_bgr=(0, 200, 255), size=16)
    assert frame.sum() > 0
