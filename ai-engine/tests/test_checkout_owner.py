from __future__ import annotations

from dataclasses import dataclass

from app.api.frame import (
    _closest_person_by_centroid,
    _collapse_duplicate_persons,
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
        280,
        [alone],
        now=100.0,
        frame_w=960,
        frame_h=540,
    )
    assert out is not None
    assert out.track_id == 3


def test_legs_in_pay_zone_does_not_claim_payer():
    bystander = TrackedObject(
        track_id=2,
        class_name="person",
        confidence=0.9,
        x1=160,
        y1=40,
        x2=280,
        y2=500,
    )
    out = _nearest_person_for_product(
        "cam-1",
        210,
        470,
        [bystander],
        now=100.0,
        frame_w=960,
        frame_h=540,
    )
    assert out is None


def test_overlapping_torso_and_arm_boxes_collapse_to_one_shopper():
    torso = TrackedObject(
        track_id=2,
        class_name="person",
        confidence=0.9,
        x1=400,
        y1=80,
        x2=620,
        y2=520,
    )
    arm = TrackedObject(
        track_id=1,
        class_name="person",
        confidence=0.7,
        x1=480,
        y1=160,
        x2=600,
        y2=360,
    )
    kept = _collapse_duplicate_persons([torso, arm])
    assert len(kept) == 1
    assert kept[0].track_id == 2


def test_two_separated_shoppers_are_not_merged():
    left = TrackedObject(
        track_id=1,
        class_name="person",
        confidence=0.9,
        x1=40,
        y1=80,
        x2=160,
        y2=500,
    )
    right = TrackedObject(
        track_id=2,
        class_name="person",
        confidence=0.9,
        x1=500,
        y1=80,
        x2=640,
        y2=500,
    )
    kept = _collapse_duplicate_persons([left, right])
    assert {p.track_id for p in kept} == {1, 2}


def test_pay_zone_product_goes_to_nearest_shopper_without_waiting_for_wrist():
    bystander = TrackedObject(
        track_id=2,
        class_name="person",
        confidence=0.9,
        x1=40,
        y1=80,
        x2=160,
        y2=480,
    )
    placer = TrackedObject(
        track_id=1,
        class_name="person",
        confidence=0.9,
        x1=180,
        y1=80,
        x2=300,
        y2=480,
    )
    chosen = _closest_person_by_centroid(220, 200, [bystander, placer])
    assert chosen is placer
