"""Localize products with color blobs, then classify each crop with YOLO.

Custom weights were trained as full-image labels, so tiled predict fires a
class on every window (white space, wood, a hand). Contours find the actual
items; a tight crop of one item is what the model was trained to see.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.det_nms import box_iou, cluster_winner_take_all

_REGION_ID_BASE = 700_000
_MIN_CROP = 24
# Wood reflections still fire Sting at ~0.50; real counter scans need higher floor.
_YOLO_CONF = 0.55
_ACCEPT_CONF = 0.55
# Products on the counter sit near the bottom of a standing-person box.
# Masking the upper 70% removes the whole arm/torso blob (not just a fragment)
# while preserving packs and bottles on the table.
_PERSON_TORSO_FRAC = 0.70


def overlaps_person(box: Any, persons: Sequence[Any], iou_thr: float = 0.35) -> bool:
    """True when the blob *is* the person (torso/head), not a product they hold.

    A standing customer bbox covers the pay zone. Treating "center inside
    person" as overlap dropped every pack on the counter — Chụp & Quét then
    reported zero products while the live overlay still showed bottles.
    """
    for p in persons:
        if str(getattr(p, "class_name", "")).lower() != "person":
            continue
        cx = (box.x1 + box.x2) / 2.0
        cy = (box.y1 + box.y2) / 2.0
        torso_bottom = p.y1 + _PERSON_TORSO_FRAC * max(1.0, p.y2 - p.y1)
        # A product on the counter can overlap most of a leaning person's
        # bbox. Geometry below the torso boundary wins over IoU in that case.
        if cy > torso_bottom:
            continue
        if p.x1 <= cx <= p.x2 and p.y1 <= cy <= p.y2:
            return True
        if box_iou(box, p) >= iou_thr:
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
    from app.vision.region_proposal import looks_like_product_blob, median_background, propose_regions

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

    proposal_img = _without_person_torsos(work, persons, x0, y0)
    regions = propose_regions(
        proposal_img,
        min_area_frac=0.0012,
        max_area_frac=0.22,
        max_regions=12,
        bg_tolerance=38,
    )
    bg_median = median_background(proposal_img)
    out: list = []
    next_id = _REGION_ID_BASE
    for r in regions:
        blob = work[
            max(0, r.y1) : min(work.shape[0], r.y2),
            max(0, r.x1) : min(work.shape[1], r.x2),
        ]
        if not looks_like_product_blob(blob, bg_median=bg_median):
            continue
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
        best = _classify_region(
            model,
            work,
            r,
            next_id,
            conf_min,
            _boxes_from_yolo_result,
        )
        if best is None:
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
    return cluster_winner_take_all(out)


def _without_person_torsos(work, persons: Sequence[Any], x0: int, y0: int):
    """Remove head/torso pixels before contours, preserving products on the counter."""
    import cv2

    proposal = work.copy()
    h, w = proposal.shape[:2]
    for person in persons:
        if str(getattr(person, "class_name", "")).lower() != "person":
            continue
        px1 = max(0, min(w, int(person.x1 - x0)))
        py1 = max(0, min(h, int(person.y1 - y0)))
        px2 = max(0, min(w, int(person.x2 - x0)))
        torso_bottom = person.y1 + _PERSON_TORSO_FRAC * max(
            1.0, person.y2 - person.y1
        )
        py2 = max(0, min(h, int(torso_bottom - y0)))
        if px2 > px1 and py2 > py1:
            cv2.rectangle(proposal, (px1, py1), (px2, py2), (0, 0, 0), -1)
    return proposal


def _classify_region(
    model,
    work,
    region,
    id_base: int,
    conf_min: float,
    boxes_from_result,
):
    """Try a tight crop, then one context crop; never rescan the whole grid."""
    h, w = work.shape[:2]
    bw, bh = max(1, region.x2 - region.x1), max(1, region.y2 - region.y1)
    tight = work[
        max(0, region.y1) : min(h, region.y2),
        max(0, region.x1) : min(w, region.x2),
    ]
    if _crop_is_non_product(tight, work):
        return None
    for pad_frac in (0.15, 0.65):
        pad_x, pad_y = int(bw * pad_frac), int(bh * pad_frac)
        cx1 = max(0, region.x1 - pad_x)
        cy1 = max(0, region.y1 - pad_y)
        cx2 = min(w, region.x2 + pad_x)
        cy2 = min(h, region.y2 + pad_y)
        if (cx2 - cx1) < _MIN_CROP or (cy2 - cy1) < _MIN_CROP:
            continue
        crop = work[cy1:cy2, cx1:cx2]
        results = model.predict(
            source=crop,
            conf=conf_min,
            iou=0.50,
            max_det=5,
            verbose=False,
        )
        if not results:
            continue
        boxes = boxes_from_result(results[0], id_base=id_base)
        if boxes:
            best = max(boxes, key=lambda box: box.confidence)
            if best.confidence >= conf_min:
                return best
    return None


def _crop_is_non_product(crop, work) -> bool:
    """Skip wood, white trays, and other counter background YOLO hallucinates on."""
    import cv2
    import numpy as np

    if crop is None or getattr(crop, "size", 0) == 0:
        return True
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1].astype(np.float32)
    val = hsv[:, :, 2].astype(np.float32)
    # Khay nhựa trắng / khăn / highlight bàn.
    if float(sat.mean()) < 40.0 and float(val.mean()) > 150.0:
        return True
    if float(sat.mean()) < 48.0 and float(val.mean()) > 135.0:
        return True
    pixels = work.reshape(-1, 3)
    pixels = pixels[pixels.sum(axis=1) > 24]
    if pixels.shape[0] < 50:
        return False
    bg = np.median(pixels, axis=0)
    crop_mean = crop.reshape(-1, 3).mean(axis=0)
    # Crop gần màu mặt bàn gỗ — model full-ảnh vẫn gán 7Up/Sting.
    if float(np.abs(crop_mean - bg).sum()) < 42.0:
        return True
    return False
