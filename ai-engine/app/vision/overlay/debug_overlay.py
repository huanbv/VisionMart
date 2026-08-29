"""Draws FPS / quality / ROI / detection debug info onto a copy of a frame.

Deliberately decoupled from `person_tracker.TrackedObject` (a lightweight
`OverlayDetection` is defined here instead) so `vision/` doesn't have to
import from the tracking layer — keeps the dependency direction one-way
(pipeline code depends on vision/, not the other way around), matching the
"avoid mixing OpenCV code inside YOLO inference" guidance.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.vision.overlay.trajectory import draw_trajectory_tails
from app.vision.quality.analyzer import FrameQuality
from app.vision.roi.zones import RoiZone


@dataclass(frozen=True)
class OverlayDetection:
    track_id: int | None
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    left_hand: tuple[float, float] | None = None
    right_hand: tuple[float, float] | None = None


def draw_debug_overlay(
    frame_bgr: np.ndarray,
    *,
    camera_name: str,
    fps: float,
    processing_time_ms: float,
    quality: FrameQuality | None,
    zones: list[RoiZone],
    detections: list[OverlayDetection],
    is_checkout_zone: bool,
    trajectories: dict[int, list[tuple[float, float]]] | None = None,
) -> np.ndarray:
    """Returns a NEW array (never mutates ``frame_bgr``) with overlay drawn
    on top — callers that also need the clean frame (e.g. to hand to YOLO)
    must draw the overlay on a separate copy, after inference, not before.
    """
    import cv2

    out = frame_bgr.copy()
    font = cv2.FONT_HERSHEY_SIMPLEX

    # ROI zone borders, colour-coded by zone type.
    zone_colors = {
        "entrance": (255, 200, 0),
        "shelf": (0, 200, 255),
        "checkout": (0, 0, 255),
        "exit": (200, 0, 200),
    }
    for zone in zones:
        height, width = out.shape[:2]
        polygon = zone.to_pixel_polygon(width, height)
        color = zone_colors.get(zone.zone_type, (255, 255, 255))
        cv2.polylines(out, [polygon], isClosed=True, color=color, thickness=2)
        label_pos = tuple(polygon[0])
        cv2.putText(out, zone.name, label_pos, font, 0.5, color, 2, cv2.LINE_AA)

    # Quỹ đạo di chuyển từng người (vài giây gần nhất) — giúp admin xác minh
    # bằng mắt ai thực sự đi tới sản phẩm, thay vì chỉ đứng gần sẵn. Một màu
    # riêng theo mapped_id (đổi theo track_id % bảng màu) để phân biệt nhiều
    # người cùng lúc.
    if trajectories:
        from app.services.person_tracker import TRAJECTORY_PALETTE as palette

        draw_trajectory_tails(out, trajectories, palette)

    # Detections / track ids.
    for det in detections:
        p1 = (int(det.x1), int(det.y1))
        p2 = (int(det.x2), int(det.y2))
        cv2.rectangle(out, p1, p2, (0, 255, 0), 2)
        label = det.class_name
        if det.track_id is not None:
            label = f"#{det.track_id} {label} {det.confidence:.2f}"
        else:
            label = f"{label} {det.confidence:.2f}"
        cv2.putText(out, label, (p1[0], max(0, p1[1] - 6)), font, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        
        # Draw hand keypoints
        if det.left_hand is not None:
            cv2.circle(out, (int(det.left_hand[0]), int(det.left_hand[1])), 6, (0, 255, 255), -1)
        if det.right_hand is not None:
            cv2.circle(out, (int(det.right_hand[0]), int(det.right_hand[1])), 6, (0, 255, 255), -1)

    # Top-left HUD text block.
    lines = [
        f"camera: {camera_name}",
        f"fps: {fps:.1f}",
        f"frame_time: {processing_time_ms:.1f} ms",
        f"detections: {len(detections)}",
        f"checkout_zone: {is_checkout_zone}",
    ]
    if quality is not None:
        lines.append(f"brightness: {quality.brightness:.1f}")
        if not (quality.blur_score != quality.blur_score):  # NaN check w/o importing math
            lines.append(f"blur_score: {quality.blur_score:.1f}")
        if quality.is_low_quality:
            lines.append(f"LOW QUALITY: {quality.reason}")

    y = 20
    for line in lines:
        cv2.putText(out, line, (10, y), font, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, line, (10, y), font, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        y += 22

    return out
