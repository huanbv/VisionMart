"""Localize products with color blobs, then classify each crop with YOLO.

Custom weights were trained as full-image labels, so tiled predict fires a
class on every window (white space, wood, a hand). Contours find the actual
items; a tight crop of one item is what the model was trained to see.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.services.det_nms import box_iou

_REGION_ID_BASE = 700_000
_MIN_CROP = 24
_YOLO_CONF = 0.45


def overlaps_person(box: Any, persons: Sequence[Any], iou_thr: float = 0.22) -> bool:
    """True when the blob sits on a person (hand/arm/torso as a fake bottle)."""
    for p in persons:
        if str(getattr(p, "class_name", "")).lower() != "person":
            continue
        if box_iou(box, p) >= iou_thr:
            return True
        cx = (box.x1 + box.x2) / 2.0
        cy = (box.y1 + box.y2) / 2.0
        if p.x1 <= cx <= p.x2 and p.y1 <= cy <= p.y2:
            return True
    return False


def detect_products_from_regions(
    model,
    img,
    persons: Sequence[Any],
    roi_rect: tuple[int, int, int, int] | None = None,
    *,
    conf_min: float = _YOLO_CONF,
) -> list:
    """One TrackedObject per color-blob, class from YOLO on that crop."""
    from app.services.person_tracker import TrackedObject, _boxes_from_yolo_result
    from app.vision.region_proposal import propose_regions

    if img is None or getattr(img, "size", 0) == 0:
        return []
    h, w = img.shape[:2]
    x0, y0 = 0, 0
    work = img
    if roi_rect is not None:
        rx1, ry1, rx2, ry2 = roi_rect
        rx1, ry1 = max(0, rx1), max(0, ry1)
        rx2, ry2 = min(w, max(rx1 + 1, rx2)), min(h, max(ry1 + 1, ry2))
        work = img[ry1:ry2, rx1:rx2]
        x0, y0 = rx1, ry1
        if work.size == 0:
            return []

    regions = propose_regions(
        work,
        min_area_frac=0.003,
        max_area_frac=0.40,
        max_regions=8,
        bg_tolerance=42,
    )
    out: list = []
    next_id = _REGION_ID_BASE
    for r in regions:
        bw, bh = max(1, r.x2 - r.x1), max(1, r.y2 - r.y1)
        pad_x, pad_y = int(bw * 0.08), int(bh * 0.08)
        wh, ww = work.shape[:2]
        cx1 = max(0, r.x1 - pad_x)
        cy1 = max(0, r.y1 - pad_y)
        cx2 = min(ww, r.x2 + pad_x)
        cy2 = min(wh, r.y2 + pad_y)
        if (cx2 - cx1) < _MIN_CROP or (cy2 - cy1) < _MIN_CROP:
            continue
        crop = work[cy1:cy2, cx1:cx2]
        fx1, fy1 = float(x0 + r.x1), float(y0 + r.y1)
        fx2, fy2 = float(x0 + r.x2), float(y0 + r.y2)
        probe = TrackedObject(
            track_id=next_id,
            class_name="region",
            confidence=1.0,
            x1=fx1,
            y1=fy1,
            x2=fx2,
            y2=fy2,
        )
        if overlaps_person(probe, persons):
            continue
        results = model.predict(
            source=crop,
            conf=conf_min,
            iou=0.50,
            max_det=5,
            verbose=False,
        )
        if not results:
            continue
        boxes = _boxes_from_yolo_result(results[0], id_base=next_id)
        if not boxes:
            continue
        best = max(boxes, key=lambda b: b.confidence)
        if best.confidence < conf_min:
            continue
        out.append(
            TrackedObject(
                track_id=next_id,
                class_name=best.class_name,
                confidence=best.confidence,
                x1=fx1,
                y1=fy1,
                x2=fx2,
                y2=fy2,
            )
        )
        next_id += 1
    return out
