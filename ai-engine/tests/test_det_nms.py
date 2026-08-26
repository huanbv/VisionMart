from __future__ import annotations

from dataclasses import dataclass

from app.services.det_nms import (
    cluster_physical_objects,
    cluster_winner_take_all,
    drop_giant_scene_boxes,
    merge_tiled_detections,
)


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


def test_winner_take_all_keeps_one_class_on_same_object():
    """Sting bottle tiles also fire du_7u — keep the higher-confidence class."""
    sevenup = Box("du_7u", 0.91, 250, 200, 380, 430)
    sting = Box("du_sti", 0.81, 260, 210, 390, 440)
    kept = cluster_winner_take_all([sevenup, sting])
    assert [d.class_name for d in kept] == ["du_7u"]


def test_winner_take_all_merges_close_centers_different_class():
    """HUD dots a few dozen pixels apart on one bottle keep the stronger SKU."""
    sevenup = Box("du_7u", 0.96, 200, 200, 250, 280)
    sting = Box("du_sti", 0.66, 210, 210, 255, 275)
    kept = cluster_winner_take_all([sevenup, sting])
    assert [d.class_name for d in kept] == ["du_7u"]


def test_winner_take_all_keeps_side_by_side_bottles():
    a = Box("du_7u", 0.9, 100, 200, 220, 400)
    b = Box("du_sti", 0.9, 240, 200, 360, 400)
    kept = cluster_winner_take_all([a, b])
    assert {d.class_name for d in kept} == {"du_7u", "du_sti"}


def test_sole_full_frame_box_is_dropped():
    giant = Box("du_sti", 0.72, 0, 0, 1280, 724)
    assert drop_giant_scene_boxes([giant], 1280, 724) == []


def test_merge_drops_second_class_on_same_bottle():
    sevenup = Box("du_7u", 0.98, 250, 200, 400, 450)
    sting = Box("du_sti", 0.81, 255, 205, 395, 445)
    merged = merge_tiled_detections([sevenup, sting], 960, 540)
    assert [d.class_name for d in merged] == ["du_7u"]
