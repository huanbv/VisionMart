from app.modules.detection.application.detection_service import (
    archive_product_detections,
)


def test_archive_prefers_pipeline_sku_and_catalog_name():
    pipeline = [
        {
            "class_name": "du_7u",
            "sku": "DU-7U",
            "confidence": 0.91,
            "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4},
        },
        {"class_name": "person", "confidence": 1.0, "bbox": {"x1": 0, "y1": 0, "x2": 1, "y2": 1}},
    ]
    fallback = [{"class_name": "du_7u", "confidence": 0.4, "bbox": {"x1": 0, "y1": 0, "x2": 2000, "y2": 2000}}]
    out = archive_product_detections(pipeline, fallback, {"DU-7U": "7Up"})
    assert len(out) == 1
    assert out[0]["sku"] == "DU-7U"
    assert out[0]["name"] == "7Up"
    assert out[0]["bbox"]["x2"] == 3


def test_archive_empty_pipeline_does_not_fall_back_to_giant_box():
    out = archive_product_detections(
        [],
        [{"class_name": "du_sti", "confidence": 0.8, "bbox": {"x1": 0, "y1": 0, "x2": 100, "y2": 100}}],
        {},
    )
    assert out == []


def test_archive_falls_back_when_pipeline_missing():
    fallback = [{"class_name": "du_sti", "sku": "DU-STI", "confidence": 0.7, "bbox": None}]
    out = archive_product_detections(None, fallback, {"DU-STI": "Sting đỏ"})
    assert len(out) == 1
    assert out[0]["name"] == "Sting đỏ"
