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
_YOLO_CONF = 0.28
_TILE_RECOVER_CONF = 0.50
# Hands / packs sit on the counter = lower part of the pose box. Upper half
# is head/torso — that is where a sleeve used to become "Sting 98%".
_PERSON_TORSO_FRAC = 0.55


def overlaps_person(box: Any, persons: Sequence[Any], iou_thr: float = 0.35) -> bool:
    """True when the blob *is* the person (torso/head), not a product they hold.

    A standing customer bbox covers the pay zone. Treating "center inside
    person" as overlap dropped every pack on the counter — Chụp & Quét then
    reported zero products while the live overlay still showed bottles.
    """
    for p in persons:
        if str(getattr(p, "class_name", "")).lower() != "person":
            continue
        if box_iou(box, p) >= iou_thr:
            return True
        cx = (box.x1 + box.x2) / 2.0
        cy = (box.y1 + box.y2) / 2.0
        if not (p.x1 <= cx <= p.x2 and p.y1 <= cy <= p.y2):
            continue
        torso_bottom = p.y1 + _PERSON_TORSO_FRAC * max(1.0, p.y2 - p.y1)
        if cy <= torso_bottom:
            return True
    return False


def _hits_region(box: Any, region: Any, x0: float, y0: float) -> bool:
    rx1, ry1 = x0 + region.x1, y0 + region.y1
    rx2, ry2 = x0 + region.x2, y0 + region.y2
    cx = (box.x1 + box.x2) / 2.0
    cy = (box.y1 + box.y2) / 2.0
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
        return True
    rcx, rcy = (rx1 + rx2) / 2.0, (ry1 + ry2) / 2.0
    if box.x1 <= rcx <= box.x2 and box.y1 <= rcy <= box.y2:
        return True

    class _R:
        __slots__ = ("x1", "y1", "x2", "y2")

        def __init__(self) -> None:
            self.x1, self.y1, self.x2, self.y2 = rx1, ry1, rx2, ry2

    return box_iou(box, _R()) >= 0.12


def detect_products_from_regions(
    model,
    img,
    persons: Sequence[Any],
    roi_rect: tuple[int, int, int, int] | None = None,
    *,
    conf_min: float = _YOLO_CONF,
) -> list:
    """One TrackedObject per color-blob, class from YOLO on that crop."""
    from app.services.det_nms import cluster_winner_take_all
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
        min_area_frac=0.0012,
        max_area_frac=0.22,
        max_regions=12,
        bg_tolerance=38,
    )
    out: list = []
    next_id = _REGION_ID_BASE
    classified_idx: set[int] = set()
    skipped_person: set[int] = set()
    for i, r in enumerate(regions):
        bw, bh = max(1, r.x2 - r.x1), max(1, r.y2 - r.y1)
        pad_x, pad_y = int(bw * 0.15), int(bh * 0.15)
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
            skipped_person.add(i)
            continue
        boxes = _predict_crop(model, crop, next_id, conf_min, _boxes_from_yolo_result)
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
        classified_idx.add(i)
        next_id += 1

    uncovered = [
        r
        for i, r in enumerate(regions)
        if i not in classified_idx and i not in skipped_person
    ]
    if uncovered:
        out.extend(
            _recover_uncovered_with_tiles(
                model,
                img,
                persons,
                roi_rect,
                uncovered,
                x0,
                y0,
                existing=out,
            )
        )
        out = cluster_winner_take_all(out)
    return out


def _predict_crop(model, crop, id_base: int, conf_min: float, boxes_from_result) -> list:
    for conf in (conf_min, min(conf_min, 0.18)):
        results = model.predict(
            source=crop,
            conf=conf,
            iou=0.50,
            max_det=5,
            verbose=False,
        )
        if not results:
            continue
        boxes = boxes_from_result(results[0], id_base=id_base)
        if boxes:
            return boxes
    return []


def _recover_uncovered_with_tiles(
    model,
    img,
    persons: Sequence[Any],
    roi_rect: tuple[int, int, int, int] | None,
    uncovered: list,
    x0: float,
    y0: float,
    existing: list,
) -> list:
    """If YOLO-on-crop missed a blob (typical: Sting fragments), keep a tile on it."""
    from app.services.person_tracker import dense_detect_on_model

    tiles = dense_detect_on_model(model, img, layout="scan", roi_rect=roi_rect)
    extras: list = []
    for t in tiles:
        if t.confidence < _TILE_RECOVER_CONF:
            continue
        if overlaps_person(t, persons):
            continue
        if existing and any(
            box_iou(t, s) >= 0.22
            or _center_in(t, s)
            or _center_in(s, t)
            for s in existing
        ):
            continue
        if any(_hits_region(t, r, x0, y0) for r in uncovered):
            extras.append(t)
    return extras


def _center_in(inner: Any, outer: Any) -> bool:
    cx = (inner.x1 + inner.x2) / 2.0
    cy = (inner.y1 + inner.y2) / 2.0
    return outer.x1 <= cx <= outer.x2 and outer.y1 <= cy <= outer.y2
