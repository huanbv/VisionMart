from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.region_detect import detect_products_from_regions, overlaps_person


@dataclass
class Box:
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def test_overlaps_person_when_center_on_arm():
    sleeve = Box("region", 1.0, 500, 80, 620, 220)
    person = Box("person", 0.9, 480, 40, 780, 700)
    assert overlaps_person(sleeve, [person]) is True


def test_overlaps_person_ignores_counter_product():
    bottle = Box("region", 1.0, 200, 400, 280, 620)
    person = Box("person", 0.9, 500, 40, 780, 700)
    assert overlaps_person(bottle, [person]) is False


def test_overlaps_person_keeps_pack_in_hands_on_counter():
    """Pose box covers the pay zone; a pack on the table is in the lower half."""
    pack = Box("region", 1.0, 520, 480, 640, 620)
    person = Box("person", 0.9, 480, 40, 780, 700)
    assert overlaps_person(pack, [person]) is False


def test_high_iou_below_torso_still_keeps_counter_product():
    product = Box("region", 1.0, 0, 50, 100, 100)
    person = Box("person", 0.9, 0, 0, 100, 100)
    assert overlaps_person(product, [person]) is False


def test_empty_frame_does_not_call_yolo():
    class Boom:
        def predict(self, **kwargs):
            raise AssertionError("YOLO should not run when there are no blobs")

    img = np.zeros((120, 160, 3), dtype=np.uint8)
    assert detect_products_from_regions(Boom(), img, []) == []


class _Row:
    def __init__(self, value):
        self._value = value

    def tolist(self):
        return list(self._value)

    def __float__(self):
        return float(self._value)

    def __int__(self):
        return int(self._value)


class _Col:
    def __init__(self, rows):
        self._rows = rows

    def __getitem__(self, i):
        return _Row(self._rows[i])

    def __len__(self):
        return len(self._rows)


class _Boxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = _Col(xyxy)
        self.conf = _Col(conf)
        self.cls = _Col(cls)
        self.id = None

    def __len__(self):
        return len(self.xyxy)


class _Result:
    def __init__(self, class_name: str, conf: float):
        self.names = {0: class_name}
        h, w = 40, 30
        self.boxes = _Boxes([[0, 0, w, h]], [conf], [0])


class _StubModel:
    def __init__(self, class_name="du_sti", conf=0.92):
        self.calls = 0
        self.class_name = class_name
        self.conf = conf
        self.requested_conf: list[float] = []

    def predict(self, **kwargs):
        self.calls += 1
        self.requested_conf.append(float(kwargs["conf"]))
        return [_Result(self.class_name, self.conf)]


class _ContextOnlyModel(_StubModel):
    def predict(self, **kwargs):
        self.calls += 1
        self.requested_conf.append(float(kwargs["conf"]))
        if self.calls == 1:
            result = _Result(self.class_name, self.conf)
            result.boxes = None
            return [result]
        return [_Result(self.class_name, self.conf)]


def test_wood_colored_crop_is_non_product():
    from app.services.region_detect import _crop_is_non_product

    work = np.full((240, 320, 3), (42, 88, 145), dtype=np.uint8)
    crop = work[70:170, 120:200]
    assert _crop_is_non_product(crop, work) is True


def test_white_tray_crop_is_non_product():
    from app.services.region_detect import _crop_is_non_product

    work = np.full((240, 320, 3), 250, dtype=np.uint8)
    crop = work[80:160, 100:220]
    assert _crop_is_non_product(crop, work) is True


def test_saturated_bottle_crop_is_kept():
    from app.services.region_detect import _crop_is_non_product

    work = np.full((240, 320, 3), (42, 88, 145), dtype=np.uint8)
    work[70:170, 120:170] = (40, 40, 220)
    crop = work[70:170, 120:170]
    assert _crop_is_non_product(crop, work) is False


def test_one_blob_one_product():
    img = np.full((240, 320, 3), 255, dtype=np.uint8)
    img[70:170, 120:170] = (40, 40, 220)
    model = _StubModel()
    out = detect_products_from_regions(model, img, [])
    assert model.calls >= 1
    assert len(out) == 1
    assert out[0].class_name == "du_sti"
    assert out[0].confidence == 0.92
    assert 100 < out[0].cx < 190
    assert 60 < out[0].cy < 180


def test_caller_confidence_is_honored():
    img = np.full((240, 320, 3), 255, dtype=np.uint8)
    img[70:170, 120:170] = (40, 40, 220)
    model = _StubModel(conf=0.25)
    out = detect_products_from_regions(model, img, [], conf_min=0.20)
    assert len(out) == 1
    assert model.requested_conf == [0.20]


def test_context_crop_recovers_tight_crop_miss_without_dense_grid():
    img = np.full((240, 320, 3), 255, dtype=np.uint8)
    img[70:170, 120:170] = (40, 40, 220)
    model = _ContextOnlyModel()
    out = detect_products_from_regions(model, img, [])
    assert len(out) == 1
    assert out[0].class_name == "du_sti"
    assert model.calls == 2


def test_product_on_counter_in_front_of_person_is_kept():
    img = np.full((240, 320, 3), 255, dtype=np.uint8)
    img[160:220, 140:190] = (40, 40, 220)
    person = Box("person", 0.99, 80, 20, 250, 230)
    model = _StubModel()
    out = detect_products_from_regions(model, img, [person])
    assert len(out) == 1
    assert out[0].class_name == "du_sti"


def test_blob_on_person_torso_is_skipped():
    img = np.full((240, 320, 3), 255, dtype=np.uint8)
    img[70:170, 120:170] = (40, 40, 220)
    person = Box("person", 0.99, 80, 40, 220, 220)
    model = _StubModel()
    out = detect_products_from_regions(model, img, [person])
    assert out == []
    assert model.calls == 0
