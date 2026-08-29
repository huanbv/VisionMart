"""Clean, anti-aliased trajectory tails shared by live and debug overlays."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def draw_trajectory_tails(
    frame,
    trajectories: Mapping[int, Sequence[tuple[float, float]]],
    palette: Sequence[tuple[int, int, int]],
) -> None:
    """Draw short fading tails instead of one noisy full-history polyline."""
    import cv2

    if not palette:
        return
    for mapped_id, points in trajectories.items():
        if len(points) < 2:
            continue
        color = palette[mapped_id % len(palette)]
        integer_points = [(int(round(x)), int(round(y))) for x, y in points]
        segment_count = len(integer_points) - 1

        for i in range(1, len(integer_points)):
            progress = i / segment_count
            fade = 0.30 + 0.70 * progress
            segment_color = tuple(int(channel * fade) for channel in color)
            cv2.line(
                frame,
                integer_points[i - 1],
                integer_points[i],
                segment_color,
                2,
                cv2.LINE_AA,
            )

        endpoint = integer_points[-1]
        cv2.circle(frame, endpoint, 5, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, endpoint, 3, color, -1, cv2.LINE_AA)
