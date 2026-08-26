from __future__ import annotations

from dataclasses import dataclass

from app.api.frame import (
    _nearest_person_for_product,
    _person_by_hand_near_product,
)
from app.services.person_tracker import TrackedObject


@dataclass
class Person:
    track_id: int
    cx: float
    cy: float
    left_hand: tuple[float, float] | None = None
    right_hand: tuple[float, float] | None = None


def test_hand_near_product_picks_placer_not_bystander():
    placer = Person(
        1,
        cx=400,
        cy=300,
        right_hand=(210, 420),
    )
    bystander = Person(2, cx=180, cy=280)
    chosen = _person_by_hand_near_product([placer, bystander], 205, 415)
    assert chosen is placer


def test_two_people_without_hand_does_not_guess_from_trajectory():
    bystander = Person(2, cx=200, cy=400)
    placer = Person(1, cx=500, cy=300)
    out = _nearest_person_for_product(
        "cam-1",
        210,
        420,
        [bystander, placer],
        now=100.0,
        frame_w=960,
        frame_h=540,
    )
    assert out is None


def test_single_person_centroid_fallback():
    alone = TrackedObject(
        track_id=3,
        class_name="person",
        confidence=0.9,
        x1=180,
        y1=200,
        x2=240,
        y2=460,
    )
    out = _nearest_person_for_product(
        "cam-1",
        210,
        430,
        [alone],
        now=100.0,
        frame_w=960,
        frame_h=540,
    )
    assert out is not None
    assert out.track_id == 3
