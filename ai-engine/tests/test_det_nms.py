from __future__ import annotations

from dataclasses import dataclass

from app.services.det_nms import cluster_physical_objects, merge_tiled_detections


@dataclass
class Box:
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def test_overlapping_tiles_of_same_sku_collapse_to_one():
    """Chụp & Quét previously listed DU-7U four times for one 7up bottle."""
    sevenup = [
        Box("du_7u", 0.91, 100, 200, 220, 420),
        Box("du_7u", 0.72, 90, 190, 240, 440),
        Box("du_7u", 0.68, 130, 210, 250, 430),
        Box("du_7u", 0.55, 80, 180, 210, 400),
    ]
    sting = [
        Box("du_sti", 0.88, 260, 210, 380, 430),
        Box("du_sti", 0.61, 250, 200, 400, 450),
    ]
    noodle = [Box("mg_hh", 0.77, 410, 240, 560, 390)]
    merged = merge_tiled_detections(sevenup + sting + noodle, 960, 540)
    names = sorted(d.class_name for d in merged)
    assert names == ["du_7u", "du_sti", "mg_hh"]


def test_adjacent_different_skus_are_kept():
    a = Box("du_7u", 0.9, 100, 200, 220, 400)
    b = Box("du_sti", 0.9, 240, 200, 360, 400)
    kept = cluster_physical_objects([a, b], 960, 540)
    assert {d.class_name for d in kept} == {"du_7u", "du_sti"}
