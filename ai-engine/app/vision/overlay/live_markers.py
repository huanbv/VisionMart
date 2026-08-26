"""Live MJPEG product markers: colored dots instead of giant boxes.

Custom YOLO weights were often trained on full-image bboxes, so rectangles
cover the plant, horse, and half the counter. Dots at each box center keep
the feed readable; nearby duplicates of the same SKU collapse to one mark.
Persons keep a thin box so staff can still see who is at the counter.
"""

from __future__ import annotations

import math
from typing import Any

import cv2  # type: ignore[import-not-found]
import numpy as np

from app.vision.overlay.unicode_text import draw_label, measure_text

# BGR — stable per SKU/class so 7Up vs Sting vs mì stay distinct at a glance.
_PALETTE: list[tuple[int, int, int]] = [
    (80, 220, 60),  # green
    (60, 200, 255),  # amber
    (255, 190, 40),  # cyan-blue
    (170, 90, 255),  # magenta
    (60, 120, 255),  # orange
    (255, 255, 90),  # light cyan
    (40, 80, 255),  # red
    (200, 160, 255),  # pink
]

_PERSON_COLOR = (80, 220, 60)
_HAND_LEFT_COLOR = (0, 255, 255)   # cyan — left wrist
_HAND_RIGHT_COLOR = (0, 200, 255)  # amber — right wrist
_HAND_RADIUS = 6


def marker_color(key: str) -> tuple[int, int, int]:
    if not key:
        return _PALETTE[0]
    return _PALETTE[sum(ord(ch) for ch in key) % len(_PALETTE)]


def _color_key(det: dict) -> str:
    label = str(det.get("sku_label") or det.get("class_name") or "object")
    if label.startswith("? "):
        label = label[2:]
    return label.strip().lower()


def _det_label(det: dict) -> str:
    sku_label = det.get("sku_label")
    if sku_label:
        sku_conf = float(det.get("sku_confidence") or 0.0)
        return f"{sku_label} {sku_conf * 100:.0f}%"
    class_name = str(det.get("class_name") or "object")
    confidence = float(det.get("confidence") or 0.0)
    return f"{class_name} {confidence * 100:.0f}%"


def _bbox_xy(det: dict) -> tuple[int, int, int, int] | None:
    bbox = det.get("bbox") or {}
    try:
        return (
            int(bbox["x1"]),
            int(bbox["y1"]),
            int(bbox["x2"]),
            int(bbox["y2"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def collapse_nearby_products(
    items: list[tuple[int, int, float, dict]],
    min_dist: float,
) -> list[tuple[int, int, float, dict]]:
    """Keep the strongest detection when markers stack on one physical object.

    7Up and Sting often fire on the same bottle; merging only same-SKU left
    both labels on screen.
    """
    ranked = sorted(items, key=lambda it: it[2], reverse=True)
    kept: list[tuple[int, int, float, dict]] = []
    for cx, cy, conf, det in ranked:
        too_close = False
        for kx, ky, _, _kdet in kept:
            if math.hypot(cx - kx, cy - ky) < min_dist:
                too_close = True
                break
        if not too_close:
            kept.append((cx, cy, conf, det))
    return kept


def _rects_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _draw_product_dot(
    frame: np.ndarray,
    cx: int,
    cy: int,
    color: tuple[int, int, int],
    radius: int,
) -> None:
    cv2.circle(frame, (cx, cy), radius + 3, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), radius, color, -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), radius, (20, 20, 20), 1, cv2.LINE_AA)


def _draw_hand_dot(
    frame: np.ndarray,
    cx: int,
    cy: int,
    color: tuple[int, int, int],
) -> None:
    cv2.circle(frame, (cx, cy), _HAND_RADIUS + 2, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), _HAND_RADIUS, color, -1, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), _HAND_RADIUS, (20, 20, 20), 1, cv2.LINE_AA)


def _hand_points(det: dict) -> list[tuple[int, int, tuple[int, int, int]]]:
    out: list[tuple[int, int, tuple[int, int, int]]] = []
    for key, color in (("left_hand", _HAND_LEFT_COLOR), ("right_hand", _HAND_RIGHT_COLOR)):
        pt = det.get(key)
        if pt is None:
            continue
        try:
            out.append((int(pt[0]), int(pt[1]), color))
        except (TypeError, ValueError):
            continue
    return out


def draw_live_detections(frame: Any, detections: list[dict]) -> None:
    """Mutates ``frame``: product dots + compact labels; thin person boxes."""
    if frame is None or not detections:
        return
    h, w = frame.shape[:2]
    radius = max(7, min(12, min(h, w) // 90))
    merge_dist = float(max(64, radius * 9))

    products: list[tuple[int, int, float, dict]] = []
    for det in detections:
        xy = _bbox_xy(det)
        if xy is None:
            continue
        x1, y1, x2, y2 = xy
        class_name = str(det.get("class_name") or "object")
        if class_name.lower() == "person":
            cv2.rectangle(frame, (x1, y1), (x2, y2), _PERSON_COLOR, 1, cv2.LINE_AA)
            for hx, hy, hcolor in _hand_points(det):
                if 0 <= hx < w and 0 <= hy < h:
                    _draw_hand_dot(frame, hx, hy, hcolor)
            label = _det_label(det)
            _tw, th = measure_text(label, 13)
            draw_label(
                frame,
                label,
                x=x1,
                y=max(0, y1 - th - 6),
                fg_bgr=(20, 20, 20),
                bg_bgr=_PERSON_COLOR,
                size=13,
            )
            continue
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        conf = float(det.get("sku_confidence") or det.get("confidence") or 0.0)
        products.append((cx, cy, conf, det))

    products = collapse_nearby_products(products, merge_dist)
    occupied: list[tuple[int, int, int, int]] = []
    label_size = 13

    for cx, cy, _conf, det in products:
        color = marker_color(_color_key(det))
        _draw_product_dot(frame, cx, cy, color, radius)
        label = _det_label(det)
        tw, th = measure_text(label, label_size)
        pad_w, pad_h = tw + 8, th + 6
        lx = cx + radius + 6
        if lx + pad_w > w - 2:
            lx = max(2, cx - radius - 6 - pad_w)
        ly = cy - pad_h // 2
        ly = max(0, min(ly, h - pad_h))
        box = (lx, ly, pad_w, pad_h)
        for _ in range(16):
            if not any(_rects_overlap(box, other) for other in occupied):
                break
            ly = min(h - pad_h, ly + pad_h + 2)
            box = (lx, ly, pad_w, pad_h)
        occupied.append(box)
        draw_label(
            frame,
            label,
            x=lx,
            y=ly,
            fg_bgr=(20, 20, 20),
            bg_bgr=color,
            size=label_size,
        )

    # Visual hint: line from wrist to product when hand is placing (debug for staff).
    hand_reach = 100.0
    for det in detections:
        if str(det.get("class_name") or "").lower() != "person":
            continue
        for hx, hy, _ in _hand_points(det):
            best_d = hand_reach
            best_prod: tuple[int, int] | None = None
            for pcx, pcy, _, _pdet in products:
                d = math.hypot(hx - pcx, hy - pcy)
                if d < best_d:
                    best_d = d
                    best_prod = (pcx, pcy)
            if best_prod is not None:
                cv2.line(
                    frame,
                    (hx, hy),
                    best_prod,
                    (180, 180, 180),
                    1,
                    cv2.LINE_AA,
                )
