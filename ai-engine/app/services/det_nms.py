"""Spatial merge for tiled YOLO checkout detections.

Custom weights trained on full-image labels fire once per *window*, so a
3-product counter scanned with overlapping tiles yields many boxes of the
same bottle. Class-aware IoU NMS alone is not enough: two boxes of the
same 7up in neighbouring tiles often overlap < 0.45 IoU. Cluster by
center / containment so one physical object becomes one box.
"""

from __future__ import annotations

from typing import TypeVar, Protocol


class HasBox(Protocol):
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


T = TypeVar("T", bound=HasBox)


def box_iou(a: HasBox, b: HasBox) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(1.0, (a.x2 - a.x1) * (a.y2 - a.y1))
    area_b = max(1.0, (b.x2 - b.x1) * (b.y2 - b.y1))
    return inter / (area_a + area_b - inter)


def _center(d: HasBox) -> tuple[float, float]:
    return (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0


def _center_in_box(inner: HasBox, outer: HasBox) -> bool:
    cx, cy = _center(inner)
    return outer.x1 <= cx <= outer.x2 and outer.y1 <= cy <= outer.y2


def drop_giant_scene_boxes(dets: list[T], width: int, height: int, max_frac: float = 0.42) -> list[T]:
    """Full-image training labels produce one box covering the whole counter.

    Keep it only when it is the *only* detection; otherwise the smaller
    tile/local boxes are the actual products.
    """
    area = float(max(1, width) * max(1, height))
    localized = [
        d for d in dets if ((d.x2 - d.x1) * (d.y2 - d.y1) / area) < max_frac
    ]
    return localized if localized else dets


def nms_same_class(dets: list[T], iou_thr: float = 0.45) -> list[T]:
    """Suppress overlaps of the SAME class only — 7up next to Sting must both survive."""
    by_cls: dict[str, list[T]] = {}
    for d in dets:
        by_cls.setdefault(d.class_name.lower(), []).append(d)
    kept: list[T] = []
    for group in by_cls.values():
        group = sorted(group, key=lambda d: d.confidence, reverse=True)
        selected: list[T] = []
        for d in group:
            if all(box_iou(d, s) < iou_thr for s in selected):
                selected.append(d)
        kept.extend(selected)
    return kept


def cluster_physical_objects(dets: list[T], width: int, height: int) -> list[T]:
    """One box per physical object on the counter.

    Same class: merge if IoU is modest, centers are close, or one center
    sits inside the other box (typical of overlapping tiles). Different
    classes are never merged — 7up next to Sting must both stay, even
    when full-image training draws oversized overlapping boxes.
    """
    if not dets:
        return []
    diag = (float(width) ** 2 + float(height) ** 2) ** 0.5
    ordered = sorted(dets, key=lambda d: d.confidence, reverse=True)
    kept: list[T] = []
    for d in ordered:
        duplicate = False
        for s in kept:
            iou = box_iou(d, s)
            same = d.class_name.lower() == s.class_name.lower()
            min_side = min(
                max(1.0, d.x2 - d.x1),
                max(1.0, d.y2 - d.y1),
                max(1.0, s.x2 - s.x1),
                max(1.0, s.y2 - s.y1),
            )
            dcx, dcy = _center(d)
            scx, scy = _center(s)
            dist = ((dcx - scx) ** 2 + (dcy - scy) ** 2) ** 0.5
            close = dist < max(28.0, 0.55 * min_side, 0.07 * diag)
            contained = _center_in_box(d, s) or _center_in_box(s, d)
            if same and (iou >= 0.18 or close or contained):
                duplicate = True
                break
        if not duplicate:
            kept.append(d)
    return kept


def merge_tiled_detections(dets: list[T], width: int, height: int) -> list[T]:
    pruned = drop_giant_scene_boxes(dets, width, height)
    nmsed = nms_same_class(pruned, iou_thr=0.25)
    return cluster_physical_objects(nmsed, width, height)


def dense_tile_origins(
    width: int,
    height: int,
    *,
    layout: str = "scan",
) -> list[tuple[int, int, int, int]]:
    """Return (ox, oy, tile_w, tile_h) windows covering the frame.

    ``scan`` (Chụp & Quét): 3×2 + center — enough windows to separate 3–4
    products when the weight was trained on full-image labels.

    ``overlay`` (live MJPEG): 2×2 + full-frame is enough to *draw* boxes
    without running 8 predicts on every HUD refresh.
    """
    w, h = max(1, width), max(1, height)
    if layout == "overlay":
        cols, rows = 2, 2
        tw, th = max(32, int(w * 0.55)), max(32, int(h * 0.55))
        include_center = False
    else:
        cols, rows = 3, 2
        tw, th = max(32, int(w * 0.42)), max(32, int(h * 0.58))
        include_center = True

    origins: list[tuple[int, int, int, int]] = []
    for r in range(rows):
        for c in range(cols):
            ox = int(round(c * (w - tw) / max(1, cols - 1)))
            oy = int(round(r * (h - th) / max(1, rows - 1)))
            origins.append((max(0, ox), max(0, oy), tw, th))
    if include_center:
        origins.append((max(0, (w - tw) // 2), max(0, (h - th) // 2), tw, th))
    return origins
