"""Disambiguate YOLO lookalikes that share a silhouette.

Custom checkout weights fire ``du_7u`` and ``du_sti`` on the same bottle
at ~0.44–0.50. Multiframe SKU voting never runs on that path: the class
name already maps to a SKU, so the classifier is skipped and the HUD/cart
flip every frame.

7Up is lime-green; Sting đỏ is red/orange. A cheap HSV vote on the crop
plus a spatial hold (same counter spot keeps its SKU) stops the flip
without retraining.
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

# Checkout often misses the bottle for several seconds (n=0). Keep the
# last SKU at that spot long enough to cover those gaps.
_SLOT_TTL_SECONDS = 10.0
# One bottle width, not a neighbour SKU on the same counter.
_SLOT_MAX_DIST_PX = 52.0
_SLOT_MAX_PER_CAMERA = 24
# Color must beat the other hue by this much to *flip* a sticky SKU
# when YOLO still disagrees. YOLO+color agreement flips without this.
_STRONG_COLOR_RATIO = 1.45

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


def color_vote_7up_sting(crop: np.ndarray | None) -> tuple[str | None, float]:
    """Return ``(class, winner/loser ratio)``. Ratio 0 means inconclusive."""
    if crop is None or getattr(crop, "size", 0) == 0:
        return None, 0.0
    if crop.ndim != 3 or crop.shape[0] < 8 or crop.shape[1] < 8:
        return None, 0.0
    h, w = crop.shape[:2]
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
        return None, 0.0
    # Lime 7Up under warm LEDs sits at hue ~25–40. The old orange band
    # (12–32) counted that as Sting, so a 7Up bottle stayed red for seconds.
    green = chroma & (hue >= 25) & (hue <= 95)
    red = chroma & ((hue <= 8) | (hue >= 170))
    sting_orange = chroma & (hue > 8) & (hue < 22) & (sat >= 120)
    n_green = int(green.sum())
    n_red = int(red.sum()) + int(sting_orange.sum())
    total = n_green + n_red
    if total < 40:
        return None, 0.0
    if n_green > n_red * 1.15:
        return "du_7u", n_green / max(1.0, float(n_red))
    if n_red > n_green * 1.15:
        return "du_sti", n_red / max(1.0, float(n_green))
    return None, 0.0


def color_hint_7up_sting(crop: np.ndarray | None) -> str | None:
    cls, _ratio = color_vote_7up_sting(crop)
    return cls


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


def _union_crop(frame: np.ndarray | None, dets: list[Any]) -> np.ndarray | None:
    if not dets:
        return None
    x1 = min(d.x1 for d in dets)
    y1 = min(d.y1 for d in dets)
    x2 = max(d.x2 for d in dets)
    y2 = max(d.y2 for d in dets)

    class _Box:
        def __init__(self) -> None:
            self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

    return _crop(frame, _Box())


def _color_disagrees(frame: np.ndarray | None, a: Any, b: Any) -> bool:
    """Two boxes with strong opposite 7Up/Sting colors are two bottles."""
    ha, ra = color_vote_7up_sting(_crop(frame, a))
    hb, rb = color_vote_7up_sting(_crop(frame, b))
    if not ha or not hb or ha == hb:
        return False
    return ra >= 1.15 and rb >= 1.15


def _same_bottle(a: Any, b: Any) -> bool:
    """True when two 7Up/Sting boxes are parts of one standing bottle.

    Overlap / containment catches the usual dual-class fire on one object.
    A wide horizontal gap is two bottles on the counter — do not merge those,
    or the cart keeps 7Up and crops the Sting box (highest YOLO score).
    """
    if box_iou(a, b) >= 0.12 or _center_in_box(a, b) or _center_in_box(b, a):
        return True
    acx, acy = _center(a)
    bcx, bcy = _center(b)
    aw = max(1.0, a.x2 - a.x1)
    bw = max(1.0, b.x2 - b.x1)
    ah = max(1.0, a.y2 - a.y1)
    bh = max(1.0, b.y2 - b.y1)
    horiz = abs(acx - bcx)
    vert = abs(acy - bcy)
    min_w = min(aw, bw)
    max_h = max(ah, bh)
    if horiz >= max(40.0, 0.55 * min_w):
        return False
    col = max(36.0, 0.30 * max_h, 0.45 * min_w)
    if horiz < col and vert < max(140.0, 1.05 * max_h):
        return True
    iy1, iy2 = max(a.y1, b.y1), min(a.y2, b.y2)
    ih = max(0.0, iy2 - iy1)
    vert_ov = ih / min(ah, bh)
    return vert_ov >= 0.45 and horiz < max(40.0, 0.50 * min_w)


def _cluster_same_bottle(
    dets: list[Any], frame_bgr: np.ndarray | None
) -> list[list[Any]]:
    clusters: list[list[Any]] = []
    for d in sorted(dets, key=lambda x: x.confidence, reverse=True):
        placed = False
        group = class_group(d.class_name)
        for cluster in clusters:
            if class_group(cluster[0].class_name) != group:
                continue
            if not any(_same_bottle(d, other) for other in cluster):
                continue
            if any(_color_disagrees(frame_bgr, d, other) for other in cluster):
                continue
            cluster.append(d)
            placed = True
            break
        if not placed:
            clusters.append([d])
    return clusters


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


def _resolve_class(
    yolo_cls: str,
    hint: str | None,
    ratio: float,
    slot: dict[str, Any] | None,
) -> str:
    """Strong color may flip; a live 7Up box must not stay hidden behind Sting.

    Warm LEDs make the first frames look red, so the spatial slot often
    stores Sting. Strong color still wins (a red crop is Sting even if YOLO
    said 7Up). Sticky still blocks a lone Sting flicker. A live ``du_7u``
    box with no color vote is shown and carted immediately.
    """
    yolo_cls = str(yolo_cls).strip().lower()
    hint_cls = str(hint).strip().lower() if hint else None
    strong = bool(hint_cls) and ratio >= _STRONG_COLOR_RATIO
    if hint_cls and hint_cls == yolo_cls:
        return yolo_cls
    if strong:
        return str(hint_cls)
    if yolo_cls == "du_7u":
        return "du_7u"
    if slot:
        return str(slot["class_name"])
    if hint_cls:
        return hint_cls
    return yolo_cls


def _touch_slot(
    slots: list[dict[str, Any]],
    group: frozenset[str],
    cx: float,
    cy: float,
    chosen: str,
    ts: float,
) -> None:
    slot = _find_slot(slots, cx, cy, group)
    if slot is None:
        slots.append(
            {
                "cx": cx,
                "cy": cy,
                "class_name": chosen,
                "group": group,
                "last_seen": ts,
            }
        )
        return
    slot["class_name"] = chosen
    slot["cx"] = cx
    slot["cy"] = cy
    slot["last_seen"] = ts


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
    look: list[Any] = []
    other: list[Any] = []
    for det in detections:
        if class_group(det.class_name) is None:
            other.append(det)
        else:
            look.append(det)
    if not look:
        return detections

    out = list(other)
    for cluster in _cluster_same_bottle(look, frame_bgr):
        group = class_group(cluster[0].class_name)
        assert group is not None
        cx = sum(d.cx for d in cluster) / len(cluster)
        cy = sum(d.cy for d in cluster) / len(cluster)
        crop = _union_crop(frame_bgr, cluster) if len(cluster) > 1 else _crop(frame_bgr, cluster[0])
        hint, ratio = (None, 0.0)
        if group == CLASS_GROUPS[0]:
            hint, ratio = color_vote_7up_sting(crop)
        slot = _find_slot(slots, cx, cy, group)
        # Highest-conf YOLO class is the default identity of this cluster.
        top = max(cluster, key=lambda d: d.confidence)
        yolo_cls = str(top.class_name).strip().lower()
        chosen = _resolve_class(yolo_cls, hint, ratio, slot)
        matching = [d for d in cluster if str(d.class_name).lower() == chosen]
        box = max(matching, key=lambda d: d.confidence) if matching else top
        yolo_names = [str(d.class_name).lower() for d in cluster]
        if len(cluster) > 1 or chosen != yolo_cls or (slot and chosen != slot["class_name"]):
            logger.warning(
                "LOOKALIKE: yolo=%s -> %s n=%d color=%s/%.1f sticky=%s box_tid=%s",
                yolo_names,
                chosen,
                len(cluster),
                hint,
                ratio,
                None if slot is None else slot["class_name"],
                box.track_id,
            )
        winner = replace(box, class_name=chosen)
        out.append(winner)
        _touch_slot(slots, group, cx, cy, chosen, ts)

    _SLOTS[camera_key] = slots
    return out
