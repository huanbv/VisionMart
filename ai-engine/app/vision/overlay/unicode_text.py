"""Draw Unicode (Vietnamese) labels onto OpenCV BGR frames.

``cv2.putText`` uses Hershey fonts which have no ă/â/ê/ô/ơ/ư — product
names like "Hảo Hảo" and "Sting đỏ" render as ``H???o H???o``. PIL + a
TrueType font that covers Latin Extended is the portable fix.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger("ai-engine.overlay.text")

_FONT_CANDIDATES = (
    os.environ.get("VISIONMART_OVERLAY_FONT") or "",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
)


@lru_cache(maxsize=1)
def _font_path() -> str | None:
    for path in _FONT_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    logger.warning(
        "No Unicode TTF found for overlay labels; Vietnamese names will show as ???"
    )
    return None


@lru_cache(maxsize=8)
def _font(size: int):
    from PIL import ImageFont

    path = _font_path()
    if not path:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def measure_text(text: str, size: int = 16) -> tuple[int, int]:
    from PIL import Image, ImageDraw

    font = _font(size)
    dummy = Image.new("RGB", (1, 1))
    x0, y0, x1, y1 = ImageDraw.Draw(dummy).textbbox((0, 0), text, font=font)
    return max(1, x1 - x0), max(1, y1 - y0)


def draw_label(
    frame_bgr: Any,
    text: str,
    *,
    x: int,
    y: int,
    fg_bgr: tuple[int, int, int] = (20, 20, 20),
    bg_bgr: tuple[int, int, int] | None = (80, 220, 60),
    size: int = 16,
) -> None:
    """Paint ``text`` onto ``frame_bgr`` with the top-left of the label at (x, y).

    Mutates the frame in place. ``fg_bgr`` / ``bg_bgr`` are OpenCV BGR.
    """
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw

    if not text:
        return
    font = _font(size)
    tw, th = measure_text(text, size)
    pad_x, pad_y = 4, 3
    box_w, box_h = tw + pad_x * 2, th + pad_y * 2
    fh, fw = frame_bgr.shape[:2]
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    x2 = min(fw, x + box_w)
    y2 = min(fh, y + box_h)
    crop_w, crop_h = max(1, x2 - x), max(1, y2 - y)

    bg_rgb = (int(bg_bgr[2]), int(bg_bgr[1]), int(bg_bgr[0])) if bg_bgr else None
    fg_rgb = (int(fg_bgr[2]), int(fg_bgr[1]), int(fg_bgr[0]))

    patch = Image.new("RGB", (box_w, box_h), bg_rgb or (0, 0, 0))
    draw = ImageDraw.Draw(patch)
    if bg_rgb is None:
        # Transparent-ish: we'll blend; still need a canvas.
        pass
    draw.text((pad_x, pad_y), text, font=font, fill=fg_rgb)
    patch_bgr = cv2.cvtColor(np.asarray(patch), cv2.COLOR_RGB2BGR)
    frame_bgr[y:y2, x:x2] = patch_bgr[:crop_h, :crop_w]
