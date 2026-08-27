from __future__ import annotations

import numpy as np

from app.services.person_tracker import dense_detect_on_model


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
    def __init__(self, xyxy, class_name="du_7u", conf=0.72):
        self.names = {0: class_name}
        self.boxes = _Boxes([xyxy], [conf], [0])


class _RecordingModel:
    def __init__(self):
        self.shapes: list[tuple[int, ...]] = []

    def predict(self, **kwargs):
        src = kwargs["source"]
        self.shapes.append(tuple(src.shape[:2]))
        h, w = src.shape[:2]
        # A bottle in the middle of whatever crop YOLO was given.
        return [_Result([w * 0.2, h * 0.2, w * 0.4, h * 0.8])]


def test_custom_checkout_predicts_on_pay_zone_crop(monkeypatch):
    """Cart pipeline used to YOLO the full 1080p frame; bottles vanished."""
    monkeypatch.setattr(
        "app.services.model_path.is_custom_detection_weight",
        lambda: True,
    )
    model = _RecordingModel()
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    roi = (400, 300, 900, 650)
    out = dense_detect_on_model(model, img, layout="scan", roi_rect=roi)
    assert model.shapes, "YOLO must run"
    crop_h, crop_w = model.shapes[0]
    assert crop_h < 720 and crop_w < 1280
    assert crop_h == (650 + 16) - (300 - 16)
    assert crop_w == (900 + 16) - (400 - 16)
    assert len(out) == 1
    assert out[0].x1 >= 400 - 16
    assert out[0].class_name == "du_7u"
