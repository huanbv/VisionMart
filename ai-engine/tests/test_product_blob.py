from __future__ import annotations

import numpy as np

from app.vision.region_proposal.product_blob import looks_like_product_blob


def test_wood_grain_is_not_product():
    wood = np.full((80, 120, 3), (42, 88, 145), dtype=np.uint8)
    bg = wood.reshape(-1, 3).mean(axis=0)
    assert looks_like_product_blob(wood, bg_median=bg) is False


def test_bright_wood_reflection_is_not_product():
    wood = np.full((80, 120, 3), (42, 88, 145), dtype=np.uint8)
    glare = wood.copy()
    glare[:] = (210, 195, 175)
    bg = wood.reshape(-1, 3).mean(axis=0)
    assert looks_like_product_blob(glare, bg_median=bg) is False


def test_colored_bottle_is_product():
    wood = np.full((80, 120, 3), (42, 88, 145), dtype=np.uint8)
    bottle = wood.copy()
    bottle[20:70, 40:80] = (40, 40, 220)
    bg = wood.reshape(-1, 3).mean(axis=0)
    assert looks_like_product_blob(bottle[20:70, 40:80], bg_median=bg) is True
