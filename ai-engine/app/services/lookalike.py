"""Disambiguate YOLO lookalikes that share a silhouette.

Custom checkout weights fire ``du_7u`` and ``du_sti`` on the same bottle
at ~0.44–0.50. Multiframe SKU voting never runs on that path: the class
name already maps to a SKU, so the classifier is skipped and the HUD/cart
flip every frame.

7Up is lime-green; Sting đỏ is red/orange. A cheap HSV vote on the crop
plus a short spatial hold (same counter spot keeps its SKU) stops the
flip without retraining.
"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any

import cv2
import numpy as np

from app.services.det_nms import _center, _center_in_box, box_iou

logger = logging.getLogger("ai-engine.lookalike")

# Detector class names that YOLO confuses on one physical object.
CLASS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"du_7u", "du_sti"}),
)
# Catalog SKUs for the same pairs — used when bridging a track that flipped.
SKU_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"DU-7U", "DU-STI"}),
)

_CLASS_TO_GROUP: dict[str, frozenset[str]] = {
    name: group for group in CLASS_GROUPS for name in group
}
_SKU_TO_GROUP: dict[str, frozenset[str]] = {
    sku: group for group in SKU_GROUPS for sku in group
}

# Hold a counter spot for a couple of seconds of missed frames (occlusion).
_SLOT_TTL_SECONDS = 2.8
_SLOT_MAX_DIST_PX = 52.0
_SLOT_MAX_PER_CAMERA = 24

# camera_key -> list of spatial slots
_SLOTS: dict[str, list[dict[str, Any]]] = {}


def class_group(class_name: str) -> frozenset[str] | None:
    return _CLASS_TO_GROUP.get(str(class_name).strip().lower())


def sku_group(sku: str) -> frozenset[str] | None:
    return _SKU_TO_GROUP.get(str(sku).strip().upper())


def skus_are_lookalikes(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return False
    group = sku_group(a)
    return group is not None and b.strip().upper() in group


def reset_slots(camera_key: str | None = None) -> None:
    if camera_key is None:
        _SLOTS.clear()
        return
    _SLOTS.pop(camera_key, None)
    for key in list(_SLOTS):
        if camera_key in key:
            _SLOTS.pop(key, None)


def color_hint_7up_sting(crop: np.ndarray | None) -> str | None:
    """Return ``du_7u`` (green) or ``du_sti`` (red/orange), else None."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None
    if crop.ndim != 3 or crop.shape[0] < 8 or crop.shape[1] < 8:
        return None
    h, w = crop.shape[:2]
    # Inner crop: skip wood/hand around the bottle.
    y1, y2 = int(h * 0.12), max(int(h * 0.12) + 1, int(h * 0.88))
    x1, x2 = int(w * 0.18), max(int(w * 0.18) + 1, int(w * 0.82))
    inner = crop[y1:y2, x1:x2]
    if inner.size == 0:
        inner = crop
    hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    chroma = (sat >= 55) & (val >= 45) & (val <= 245)
    if int(chroma.sum()) < 40:
        return None
    green = chroma & (hue >= 35) & (hue <= 85)
    red = chroma & ((hue <= 12) | (hue >= 165))
    orange = chroma & (hue > 12) & (hue < 32) & (sat >= 90)
    n_green = int(green.sum())
    n_red = int(red.sum()) + int(orange.sum())
    total = n_green + n_red
    if total < 40:
        return None
    if n_green > n_red * 1.30:
        return "du_7u"
    if n_red > n_green * 1.30:
        return "du_sti"
    return None


def _crop(frame: np.ndarray | None, det: Any) -> np.ndarray | None:
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    h, w = frame.shape[:2]
    x1 = max(0, int(det.x1))
    y1 = max(0, int(det.y1))
    x2 = min(w, max(x1 + 1, int(det.x2)))
    y2 = min(h, max(y1 + 1, int(det.y2)))
    crop = frame[y1:y2, x1:x2]
    return crop if crop.size else None


def _spatial_clash(a: Any, b: Any) -> bool:
    acx, acy = _center(a)
    bcx, bcy = _center(b)
    amin = min(max(1.0, a.x2 - a.x1), max(1.0, a.y2 - a.y1))
    bmin = min(max(1.0, b.x2 - b.x1), max(1.0, b.y2 - b.y1))
    dist = ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5
    close = dist < max(36.0, 0.55 * min(amin, bmin))
    return (
        box_iou(a, b) >= 0.22
        or _center_in_box(a, b)
        or _center_in_box(b, a)
        or close
    )


def _prune_slots(camera_key: str, now: float) -> list[dict[str, Any]]:
    slots = _SLOTS.get(camera_key) or []
    slots = [s for s in slots if now - float(s["last_seen"]) <= _SLOT_TTL_SECONDS]
    if len(slots) > _SLOT_MAX_PER_CAMERA:
        slots = sorted(slots, key=lambda s: float(s["last_seen"]), reverse=True)[
            :_SLOT_MAX_PER_CAMERA
        ]
    _SLOTS[camera_key] = slots
    return slots


def _find_slot(
    slots: list[dict[str, Any]], cx: float, cy: float, group: frozenset[str]
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_d = _SLOT_MAX_DIST_PX
    for slot in slots:
        if slot.get("group") != group:
            continue
        d = ((float(slot["cx"]) - cx) ** 2 + (float(slot["cy"]) - cy) ** 2) ** 0.5
        if d < best_d:
            best_d = d
            best = slot
    return best


def _resolve_class(yolo_cls: str, hint: str | None, slot: dict[str, Any] | None) -> str:
    """Color wins; otherwise keep the bottle at this spot from flipping."""
    if hint:
        return hint
    if slot:
        return str(slot["class_name"])
    return yolo_cls


def _collapse_overlapping_lookalikes(dets: list[Any]) -> list[Any]:
    look, other = [], []
    for d in dets:
        if class_group(d.class_name) is None:
            other.append(d)
        else:
            look.append(d)
    if len(look) < 2:
        return dets
    ordered = sorted(look, key=lambda d: d.confidence, reverse=True)
    kept: list[Any] = []
    for d in ordered:
        group = class_group(d.class_name)
        clash = False
        for s in kept:
            if class_group(s.class_name) != group:
                continue
            if _spatial_clash(d, s):
                clash = True
                break
        if not clash:
            kept.append(d)
    return other + kept


def stabilize_lookalikes(
    camera_key: str,
    detections: list[Any],
    frame_bgr: np.ndarray | None,
    now: float | None = None,
) -> list[Any]:
    """Rewrite 7Up/Sting class names using color + a spatial hold."""
    if not detections:
        return detections
    ts = time.monotonic() if now is None else now
    slots = _prune_slots(camera_key, ts)
    out: list[Any] = []
    for det in detections:
        yolo_cls = str(det.class_name).strip().lower()
        group = class_group(yolo_cls)
        if group is None:
            out.append(det)
            continue
        hint = None
        if group == CLASS_GROUPS[0]:
            hint = color_hint_7up_sting(_crop(frame_bgr, det))
        slot = _find_slot(slots, det.cx, det.cy, group)
        chosen = _resolve_class(yolo_cls, hint, slot)
        if slot is None:
            slot = {
                "cx": det.cx,
                "cy": det.cy,
                "class_name": chosen,
                "group": group,
                "last_seen": ts,
            }
            slots.append(slot)
        else:
            prev = str(slot["class_name"])
            if chosen != prev:
                logger.warning(
                    "LOOKALIKE: %s -> %s at (%.0f,%.0f) color=%s yolo=%s",
                    prev,
                    chosen,
                    det.cx,
                    det.cy,
                    hint,
                    yolo_cls,
                )
            slot["class_name"] = chosen
            slot["cx"] = det.cx
            slot["cy"] = det.cy
            slot["last_seen"] = ts
        if chosen != yolo_cls:
            det = replace(det, class_name=chosen)
        out.append(det)
    _SLOTS[camera_key] = slots
    return _collapse_overlapping_lookalikes(out)
