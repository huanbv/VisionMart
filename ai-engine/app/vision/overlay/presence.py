"""Drop live-overlay ghosts on an empty checkout counter.

Custom YOLO weights labeled as full-image boxes (0.5 0.5 1 1) fire a class
on *every* tile, including bare wood. Live HUD used to draw those as
products. A real item differs from the counter color (see propose_regions);
empty wood does not. Keep a YOLO hit only when it overlaps such a blob.
"""

from __future__ import annotations

from typing import Any

# Live HUD only — cart scan / Chụp & Quét keep the lower YOLO floor.
OVERLAY_MIN_CONFIDENCE = 0.55


def _bbox(det: dict) -> tuple[float, float, float, float] | None:
    box = det.get("bbox") or {}
    try:
        return (
            float(box["x1"]),
            float(box["y1"]),
            float(box["x2"]),
            float(box["y2"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _iou(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1.0, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


def _hits_region(
    box: tuple[float, float, float, float],
    region: Any,
) -> bool:
    x1, y1, x2, y2 = box
    rx1, ry1, rx2, ry2 = float(region.x1), float(region.y1), float(region.x2), float(region.y2)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
        return True
    rcx, rcy = (rx1 + rx2) / 2.0, (ry1 + ry2) / 2.0
    if x1 <= rcx <= x2 and y1 <= rcy <= y2:
        return True
    return _iou(box, (rx1, ry1, rx2, ry2)) >= 0.08


def filter_overlay_ghosts(frame_bgr: Any, detections: list[dict]) -> list[dict]:
    """Keep persons + product boxes that sit on an actual object vs empty wood."""
    if not detections:
        return []

    persons: list[dict] = []
    candidates: list[dict] = []
    custom_bbox = False
    try:
        from app.services.model_path import is_custom_detection_weight

        custom_bbox = is_custom_detection_weight()
    except Exception:  # noqa: BLE001
        custom_bbox = False
    min_conf = 0.30 if custom_bbox else OVERLAY_MIN_CONFIDENCE
    for det in detections:
        if str(det.get("class_name") or "").lower() == "person":
            persons.append(det)
            continue
        if float(det.get("confidence") or 0.0) < min_conf:
            continue
        if _bbox(det) is None:
            continue
        candidates.append(det)

    if not candidates:
        return persons

    # Bbox-trained SKU detector already localizes packs. The color-blob gate
    # was for tiled classifier weights and hid real products on live HUD.
    if custom_bbox:
        return persons + candidates

    try:
        from app.vision.region_proposal import (
            looks_like_product_blob,
            median_background,
            propose_regions,
        )

        regions = propose_regions(
            frame_bgr,
            min_area_frac=0.0015,
            max_area_frac=0.22,
            max_regions=8,
            bg_tolerance=48,
            # Local-contrast fallback treats wood grain as objects, so
            # YOLO hits on empty counter would survive this gate.
            allow_local_fallback=False,
        )
        bg_median = median_background(frame_bgr)
        product_regions = [
            r
            for r in regions
            if looks_like_product_blob(
                frame_bgr[
                    max(0, r.y1) : min(frame_bgr.shape[0], r.y2),
                    max(0, r.x1) : min(frame_bgr.shape[1], r.x2),
                ],
                bg_median=bg_median,
            )
        ]
    except Exception:  # noqa: BLE001 — overlay must never break the stream
        return persons + candidates

    if not product_regions:
        return persons

    kept = [
        det
        for det in candidates
        if any(_hits_region(_bbox(det), r) for r in product_regions)  # type: ignore[arg-type]
        and not _center_on_person_torso(_bbox(det), persons)  # type: ignore[arg-type]
    ]
    return persons + kept


def _center_on_person_torso(
    box: tuple[float, float, float, float],
    persons: list[dict],
) -> bool:
    """Grab jackets / sleeves look like 7Up to full-image YOLO."""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    for person in persons:
        pb = _bbox(person)
        if pb is None:
            continue
        px1, py1, px2, py2 = pb
        torso_bottom = py1 + 0.70 * max(1.0, py2 - py1)
        if px1 <= cx <= px2 and py1 <= cy <= torso_bottom:
            return True
    return False
