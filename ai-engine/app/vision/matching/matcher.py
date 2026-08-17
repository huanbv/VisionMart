"""Product matching — turns model outputs into a SKU decision.

Each stage produces its own confidence, and this module is where they are
combined into one number the rest of the system can act on:

    YOLO 0.94  ·  Classifier 0.98  ·  OCR 0.91   ->   final 0.96

Why a weighted product rather than an average
---------------------------------------------
The stages are *sequential dependencies*, not independent opinions: if the
detector barely saw an object, a confident classifier reading of that
same blur is not trustworthy either. Averaging would let one strong stage
paper over a weak one (0.2 detection + 0.99 classification averages to a
respectable-looking 0.6). A weighted geometric-style combination keeps a
weak link visible in the final score.

Decision order
--------------
1. Classifier SKU, when it is available *and* confident enough.
2. Otherwise the existing ``class_to_sku`` JSON mapping — today's
   behaviour, kept as the fallback so turning the classifier off (or
   deploying before a model exists) changes nothing.

The result records *which* source decided, so the admin UI and the review
queue can tell "the classifier said so" from "we guessed from the COCO
class name".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("ai-engine.vision.matcher")

# Relative trust. Detection is weighted highest because everything
# downstream is conditioned on it: a bad crop poisons every later stage.
_WEIGHT_YOLO = 0.45
_WEIGHT_CLASSIFIER = 0.40
_WEIGHT_OCR = 0.15


@dataclass(frozen=True)
class MatchResult:
    sku: str | None
    source: str                       # "classifier" | "class_map" | "none"
    final_confidence: float
    yolo_confidence: float
    classifier_sku: str | None = None
    classifier_confidence: float | None = None
    classifier_margin: float | None = None
    ocr_text: str | None = None
    ocr_confidence: float | None = None
    # Why this decision was reached — surfaced in the pipeline log so an
    # operator can see the reasoning without re-running anything.
    reason: str = ""
    stage_confidences: dict[str, float] = field(default_factory=dict)


def combine_confidence(
    *,
    yolo: float,
    classifier: float | None = None,
    ocr: float | None = None,
) -> float:
    """Blend the per-stage scores into one final confidence.

    Only the stages that actually ran are counted, with the weights
    renormalised over them — otherwise skipping OCR would permanently cap
    the achievable score at 0.85.
    """
    parts: list[tuple[float, float]] = [(_WEIGHT_YOLO, max(0.0, min(1.0, yolo)))]
    if classifier is not None:
        parts.append((_WEIGHT_CLASSIFIER, max(0.0, min(1.0, classifier))))
    if ocr is not None:
        parts.append((_WEIGHT_OCR, max(0.0, min(1.0, ocr))))

    total_weight = sum(w for w, _ in parts)
    if total_weight <= 0:
        return 0.0
    # Weighted geometric mean: a near-zero stage drags the result down
    # instead of being averaged away.
    acc = 1.0
    for weight, value in parts:
        acc *= max(value, 1e-6) ** (weight / total_weight)
    return float(round(acc, 4))


def match_product(
    *,
    organization_id: str,
    branch_id: str,
    class_name: str,
    yolo_confidence: float,
    classification: Any | None = None,
    classifier_min_confidence: float = 0.55,
    classifier_min_margin: float = 0.0,
    ocr_text: str | None = None,
    ocr_confidence: float | None = None,
    ocr: Any | None = None,
) -> MatchResult:
    """Decide the SKU for one detected object.

    ``classification`` is a ``ClassificationResult`` or ``None`` (classifier
    disabled, unavailable, or it declined this crop).
    """
    from app.services.product_mapper import (
        find_sku_by_brand_volume,
        map_class_to_sku,
    )

    # Accept either the parsed OCR object or the two loose fields, so
    # existing callers that pass only text keep working unchanged.
    if ocr is not None:
        ocr_text = ocr_text if ocr_text is not None else getattr(ocr, "raw_text", None)
        ocr_confidence = (
            ocr_confidence if ocr_confidence is not None
            else getattr(ocr, "confidence", None)
        )

    cls_sku = getattr(classification, "sku", None) if classification else None
    cls_conf = getattr(classification, "confidence", None) if classification else None
    cls_margin = getattr(classification, "margin", None) if classification else None

    stage_conf: dict[str, float] = {"yolo": round(float(yolo_confidence), 4)}
    if cls_conf is not None:
        stage_conf["classifier"] = round(float(cls_conf), 4)
    if ocr_confidence is not None:
        stage_conf["ocr"] = round(float(ocr_confidence), 4)

    # Cổng margin (mở-tập): vật lạ bị softmax ép về một SKU thường có top-1
    # và top-2 sát nhau. Nếu margin dưới ngưỡng thì coi như classifier KHÔNG
    # chắc chắn — bỏ qua nhánh chấp nhận bên dưới, để rơi xuống class_map/none
    # thay vì thêm nhầm sản phẩm. margin=None (không có runner-up) coi như đạt.
    margin_ok = (
        classifier_min_margin <= 0.0
        or cls_margin is None
        or float(cls_margin) >= classifier_min_margin
    )

    # --- 1. Classifier, when confident enough ---
    # Trước đây lớp "region" (đề xuất contour, không phải lớp YOLO thật —
    # xem person_tracker.py::_merge_classical_proposals) bị siết cứng lên
    # tối thiểu 0.68, cao hơn hẳn CLASSIFIER_MIN_CONFIDENCE (mặc định 0.55)
    # và KHÔNG chỉnh được từ Admin > Cấu hình xử lý ảnh dù mọi ngưỡng khác
    # trong hệ thống đều chỉnh được ở đó không cần sửa code/restart. Bỏ
    # điểm siết riêng này — "region" dùng chung classifier_min_confidence
    # như mọi lớp khác, admin chỉnh một chỗ duy nhất là áp dụng cho tất cả.
    actual_min_conf = classifier_min_confidence
    if (
        cls_sku
        and cls_conf is not None
        and cls_conf >= actual_min_conf
        and margin_ok
    ):
        final = combine_confidence(
            yolo=yolo_confidence, classifier=cls_conf, ocr=ocr_confidence
        )
        stage_conf["final"] = final
        return MatchResult(
            sku=cls_sku,
            source="classifier",
            final_confidence=final,
            yolo_confidence=float(yolo_confidence),
            classifier_sku=cls_sku,
            classifier_confidence=float(cls_conf),
            classifier_margin=float(cls_margin) if cls_margin is not None else None,
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            reason=f"classifier confident ({cls_conf:.2f} >= {classifier_min_confidence:.2f})",
            stage_confidences=stage_conf,
        )

    # --- 2. OCR: what the label actually says ---
    # Placed above the class map, not below it, and this ordering is the
    # point of the stage. The class map answers with the *same* SKU for
    # every object of a YOLO class — every water bottle is "bottle", so it
    # maps them all to one product regardless of brand or size. A brand +
    # size read off the label is specific evidence about *this* object, so
    # it should win over a mapping that could not tell these apart in the
    # first place.
    if ocr is not None and getattr(ocr, "has_signal", False):
        ocr_sku = find_sku_by_brand_volume(
            organization_id,
            getattr(ocr, "brand", None),
            getattr(ocr, "volume_ml", None),
            getattr(ocr, "weight_g", None),
        )
        if ocr_sku:
            final = combine_confidence(
                yolo=yolo_confidence,
                # The classifier reading is folded in only if it *agrees*.
                # A rejected disagreeing guess must not raise confidence in
                # an answer it argued against.
                classifier=cls_conf if cls_sku == ocr_sku else None,
                ocr=ocr_confidence,
            )
            stage_conf["final"] = final
            parts = []
            if getattr(ocr, "brand", None):
                parts.append(str(ocr.brand))
            if getattr(ocr, "volume_ml", None):
                parts.append(f"{ocr.volume_ml}ml")
            return MatchResult(
                sku=ocr_sku,
                source="ocr",
                final_confidence=final,
                yolo_confidence=float(yolo_confidence),
                classifier_sku=cls_sku,
                classifier_confidence=float(cls_conf) if cls_conf is not None else None,
                classifier_margin=float(cls_margin) if cls_margin is not None else None,
                ocr_text=ocr_text,
                ocr_confidence=ocr_confidence,
                reason=f"đọc được nhãn: {' '.join(parts)} → {ocr_sku}",
                stage_confidences=stage_conf,
            )

    # --- 3. Fall back to the existing static class -> SKU map ---
    mapped = map_class_to_sku(organization_id, branch_id, class_name)
    if mapped:
        # The classifier's (low) score is deliberately *not* folded in
        # here: the SKU came from the class map, so scoring it with a
        # reading we just rejected would overstate the confidence.
        final = combine_confidence(yolo=yolo_confidence)
        stage_conf["final"] = final
        if cls_sku and cls_conf is not None and cls_conf >= actual_min_conf and not margin_ok:
            reason = (
                f"classifier margin thấp ({float(cls_margin):.2f} < "
                f"{classifier_min_margin:.2f}) — nghi vật lạ; used class map"
            )
        elif cls_sku:
            reason = (
                f"classifier below threshold ({cls_conf:.2f} < "
                f"{actual_min_conf:.2f}); used class map"
            )
        else:
            reason = "classifier unavailable; used class map"
        return MatchResult(
            sku=mapped,
            source="class_map",
            final_confidence=final,
            yolo_confidence=float(yolo_confidence),
            classifier_sku=cls_sku,
            classifier_confidence=float(cls_conf) if cls_conf is not None else None,
            classifier_margin=float(cls_margin) if cls_margin is not None else None,
            ocr_text=ocr_text,
            ocr_confidence=ocr_confidence,
            reason=reason,
            stage_confidences=stage_conf,
        )

    # --- 3. Nothing matched ---
    stage_conf["final"] = 0.0
    return MatchResult(
        sku=None,
        source="none",
        final_confidence=0.0,
        yolo_confidence=float(yolo_confidence),
        classifier_sku=cls_sku,
        classifier_confidence=float(cls_conf) if cls_conf is not None else None,
        classifier_margin=float(cls_margin) if cls_margin is not None else None,
        ocr_text=ocr_text,
        ocr_confidence=ocr_confidence,
        reason=f"no SKU for class '{class_name}'",
        stage_confidences=stage_conf,
    )
