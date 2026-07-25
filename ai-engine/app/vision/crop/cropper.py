"""Crop detected objects out of a frame so a classifier can identify them.

This is the bridge between the two model stages. YOLO answers *where is an
object and roughly what kind* ("a bottle, here"); the classifier answers
*which SKU is it* ("Aquafina 500ml"). The classifier needs the object on
its own — feeding it the whole frame would drown the product in shelf
clutter.

Two details matter more than they look:

* **Padding.** YOLO boxes hug the object, often clipping the cap or label
  edge. Those edges carry most of the brand signal, so the crop is
  expanded by a small margin before being handed to the classifier.
* **Minimum size.** A 12x8 px crop upscaled to 224x224 is mush; the
  classifier will still return a confident-looking answer for it, which is
  worse than returning nothing. Crops below a size floor are rejected here
  rather than silently producing a bad SKU downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np


@dataclass(frozen=True)
class CropResult:
    """One cropped object, plus what it was cropped from."""

    image: np.ndarray            # BGR crop
    track_id: int | None
    class_name: str
    yolo_confidence: float
    # Box actually used (after padding + clamping), in frame pixels.
    bbox: tuple[int, int, int, int]
    # Original YOLO box, before padding — kept so the debug overlay can
    # show what the detector proposed vs what the classifier looked at.
    source_bbox: tuple[float, float, float, float]

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]


def is_degenerate_box(
    x1: float, y1: float, x2: float, y2: float, w: int, h: int,
    *, area_frac: float = 0.85, side_frac: float = 0.92,
) -> bool:
    """True khi box gần như trùm cả khung — tức detector KHÔNG định vị được
    sản phẩm, chỉ khoanh cả cảnh.

    Đây là dấu hiệu của detector train bằng nhãn cả-khung (trainer.py ghi
    '0.5 0.5 1.0 1.0'): mọi box ~ cả khung, nên "crop" ra chỉ là ảnh cảnh
    chung chứ không phải sản phẩm cận cảnh. Cắt một ảnh như vậy rồi gọi là
    'crop sản phẩm' là lừa cả người duyệt lẫn classifier, nên chỗ nào cần
    crop cận cảnh thì nên bỏ qua box kiểu này.
    """
    if w <= 0 or h <= 0:
        return False
    bw, bh = max(0.0, x2 - x1), max(0.0, y2 - y1)
    if (bw * bh) / float(w * h) >= area_frac:
        return True
    # Bắt cả trường hợp dải trùm gần hết một chiều (vd cả bề ngang quầy).
    return (bw / w) >= side_frac and (bh / h) >= side_frac


def crop_detection(
    frame_bgr: np.ndarray,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    padding: float = 0.08,
    min_size: int = 24,
    track_id: int | None = None,
    class_name: str = "",
    yolo_confidence: float = 0.0,
) -> CropResult | None:
    """Crop one box. Returns ``None`` when the crop is unusable.

    ``padding`` is a fraction of the box's own size, not a fixed pixel
    count, so a small distant product and a large near one both keep the
    same proportion of surrounding context.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    h, w = frame_bgr.shape[:2]

    bw = x2 - x1
    bh = y2 - y1
    if bw <= 0 or bh <= 0:
        return None

    pad_x = bw * padding
    pad_y = bh * padding

    # Clamp to the frame — a padded box near the edge would otherwise index
    # out of range (numpy would silently return a smaller array).
    cx1 = max(0, int(round(x1 - pad_x)))
    cy1 = max(0, int(round(y1 - pad_y)))
    cx2 = min(w, int(round(x2 + pad_x)))
    cy2 = min(h, int(round(y2 + pad_y)))

    if cx2 - cx1 < min_size or cy2 - cy1 < min_size:
        # Too small to identify. Returning None here (rather than a
        # blurry upscale) keeps the classifier from inventing a confident
        # answer from a handful of pixels.
        return None

    crop = frame_bgr[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None

    return CropResult(
        image=crop,
        track_id=track_id,
        class_name=class_name,
        yolo_confidence=yolo_confidence,
        bbox=(cx1, cy1, cx2, cy2),
        source_bbox=(float(x1), float(y1), float(x2), float(y2)),
    )


def crop_detections(
    frame_bgr: np.ndarray,
    detections: Iterable[Any],
    *,
    padding: float = 0.08,
    min_size: int = 24,
    skip_classes: frozenset[str] = frozenset({"person"}),
) -> list[CropResult]:
    """Crop every detection worth classifying.

    ``skip_classes`` exists because people are tracked for cart pairing but
    are never a product SKU — running a product classifier over them would
    burn CPU to produce a guaranteed-meaningless answer.
    """
    out: list[CropResult] = []
    for det in detections:
        class_name = str(getattr(det, "class_name", "") or "")
        if class_name.lower() in skip_classes:
            continue
        result = crop_detection(
            frame_bgr,
            float(getattr(det, "x1", 0.0)),
            float(getattr(det, "y1", 0.0)),
            float(getattr(det, "x2", 0.0)),
            float(getattr(det, "y2", 0.0)),
            padding=padding,
            min_size=min_size,
            track_id=getattr(det, "track_id", None),
            class_name=class_name,
            yolo_confidence=float(getattr(det, "confidence", 0.0) or 0.0),
        )
        if result is not None:
            out.append(result)
    return out
