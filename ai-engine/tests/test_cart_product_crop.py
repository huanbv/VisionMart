from __future__ import annotations

import numpy as np

from app.api.frame import product_crop_jpeg


def test_product_crop_jpeg_is_closeup_not_full_frame():
    frame = np.full((240, 320, 3), 30, dtype=np.uint8)
    frame[80:180, 120:170] = (40, 210, 160)
    jpeg = product_crop_jpeg(frame, 120, 80, 170, 180)
    assert jpeg is not None
    assert jpeg[:2] == b"\xff\xd8"
    assert len(jpeg) < 40_000


def test_product_crop_jpeg_paints_product_name():
    frame = np.full((240, 320, 3), 30, dtype=np.uint8)
    frame[80:180, 120:170] = (40, 210, 160)
    plain = product_crop_jpeg(frame, 120, 80, 170, 180)
    labeled = product_crop_jpeg(frame, 120, 80, 170, 180, label="Hảo Hảo")
    assert labeled is not None
    assert labeled[:2] == b"\xff\xd8"
    assert labeled != plain


def test_product_crop_jpeg_skips_degenerate_full_frame_box():
    frame = np.full((240, 320, 3), 80, dtype=np.uint8)
    assert product_crop_jpeg(frame, 0, 0, 320, 240) is None
