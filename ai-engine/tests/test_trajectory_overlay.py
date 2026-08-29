from __future__ import annotations

import numpy as np

from app.services.person_tracker import _prepare_display_trajectory
from app.vision.overlay.trajectory import draw_trajectory_tails


def test_stationary_bbox_jitter_does_not_draw_scribble():
    now = 100.0
    raw = [
        (0.500 + offset, 0.500 - offset, now - 1.0 + i * 0.1)
        for i, offset in enumerate((0.0, 0.002, -0.002, 0.001, -0.001))
    ]
    assert _prepare_display_trajectory(raw, 640, 360, now=now) == []


def test_recent_motion_is_smoothed_and_keeps_latest_endpoint():
    now = 100.0
    raw = [
        (0.20 + i * 0.025, 0.40 + (0.004 if i % 2 else -0.004), now - 1 + i * 0.1)
        for i in range(10)
    ]
    points = _prepare_display_trajectory(raw, 640, 360, now=now)

    assert 2 <= len(points) <= 10
    assert all(points[i][0] > points[i - 1][0] for i in range(1, len(points)))
    assert points[-1] == (raw[-1][0] * 640, raw[-1][1] * 360)


def test_tracker_jump_discards_old_segment():
    now = 100.0
    raw = [
        (0.10, 0.40, now - 1.0),
        (0.12, 0.40, now - 0.9),
        (0.80, 0.40, now - 0.3),
        (0.83, 0.40, now - 0.2),
        (0.86, 0.40, now - 0.1),
    ]
    points = _prepare_display_trajectory(raw, 640, 360, now=now)

    assert points
    assert min(x for x, _y in points) >= 0.80 * 640


def test_trajectory_renderer_draws_antialiased_tail():
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    draw_trajectory_tails(
        frame,
        {2: [(10.0, 20.0), (40.0, 40.0), (80.0, 50.0)]},
        [(255, 0, 255), (0, 165, 255), (0, 255, 0)],
    )

    assert np.count_nonzero(frame) > 0
    assert tuple(frame[50, 80]) != (0, 0, 0)
