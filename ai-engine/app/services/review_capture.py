"""Auto-capture of pay-zone product crops for the active-learning queue.

YOLO class names are not the filter. Stock weights call empty wood
``dining table``; custom weights may miss a bottle entirely — neither
gives admin a SKU to confirm. This module samples frames where a color
blob in the ROI-masked pay zone looks like packaging, then a human
assigns the catalog SKU before it becomes training data.

Three properties matter more than completeness here, because this runs on
the frame hot path:

1. **Never blocks or breaks detection.** The upload runs as a fire-and-
   forget task and every failure is swallowed with a log line. A debugging
   / data-collection aid must not be able to fail a customer-facing frame.
2. **Rate-limited per camera.** A camera at 15 FPS staring at one
   ambiguous object would otherwise produce thousands of near-identical
   candidates in a minute, burying the reviewer and the object store. One
   capture per ``REVIEW_CAPTURE_COOLDOWN_SECONDS`` per camera.
3. **Bounded band, not "everything below the threshold."** Detections with
   almost no confidence are usually noise rather than a mislabelled
   product, so only the band between ``REVIEW_CAPTURE_MIN_CONFIDENCE`` and
   the caller's ``min_confidence`` is captured — the "the model saw
   something and hesitated" range.

Disabled by default (``ENABLE_REVIEW_CAPTURE``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from app.vision.config import get_vision_config

logger = logging.getLogger("ai-engine.review_capture")

# COCO furniture/scene classes that fire on an empty pay-zone mask
# (black + wood). They must never enter the review queue as "training crops".
_SKIP_REVIEW_CLASSES = frozenset(
    {
        "person",
        "dining table",
        "chair",
        "couch",
        "bed",
        "toilet",
        "tv",
        "laptop",
        "mouse",
        "remote",
        "keyboard",
        "cell phone",
        "microwave",
        "oven",
        "toaster",
        "sink",
        "refrigerator",
        "book",
        "clock",
        "vase",
        "potted plant",
        "bench",
        "parking meter",
        "traffic light",
        "stop sign",
        "fire hydrant",
        "teddy bear",
        "hair drier",
        "toothbrush",
        "scissors",
        "umbrella",
        "backpack",
        "handbag",
        "suitcase",
        "tie",
    }
)
_COCO_PRODUCTISH = frozenset({"bottle", "cup", "wine glass", "bowl"})

# camera_key -> monotonic timestamp of the last capture
_LAST_CAPTURE: dict[str, float] = {}


# These read through VisionConfig rather than os.getenv directly so the
# admin screen can tune them at runtime like every other vision setting.
def _enabled() -> bool:
    return get_vision_config().enable_review_capture


def _cooldown_seconds() -> float:
    return get_vision_config().review_capture_cooldown_seconds


def _floor_confidence() -> float:
    return get_vision_config().review_capture_min_confidence


def _backend_base_url() -> str:
    return os.getenv("BACKEND_BASE_URL", "http://backend:8000/api/v1")


def _api_key() -> str:
    return os.getenv("AI_ENGINE_API_KEY", "change-me-ai-engine-key")


def is_product_review_class(class_name: str) -> bool:
    """True when this detector class can be a shop SKU, not empty furniture."""
    name = str(class_name).strip().lower()
    if not name or name in _SKIP_REVIEW_CLASSES:
        return False
    from app.services.product_mapper import list_coco_classes

    coco = {c.lower() for c in list_coco_classes()}
    if name not in coco:
        return True
    return name in _COCO_PRODUCTISH


def is_enabled() -> bool:
    return _enabled()


def _box_iou(a: Any, b: Any) -> float:
    ix1 = max(float(a.x1), float(b.x1))
    iy1 = max(float(a.y1), float(b.y1))
    ix2 = min(float(a.x2), float(b.x2))
    iy2 = min(float(a.y2), float(b.y2))
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(1.0, (float(a.x2) - float(a.x1)) * (float(a.y2) - float(a.y1)))
    area_b = max(1.0, (float(b.x2) - float(b.x1)) * (float(b.y2) - float(b.y1)))
    return inter / (area_a + area_b - inter)


def _crop_is_product(frame_bgr: Any, x1: float, y1: float, x2: float, y2: float) -> bool:
    from app.vision.crop.cropper import crop_detection, is_degenerate_box
    from app.vision.region_proposal import looks_like_product_blob, median_background

    h, w = frame_bgr.shape[:2]
    if is_degenerate_box(x1, y1, x2, y2, w, h):
        return False
    crop = crop_detection(frame_bgr, x1, y1, x2, y2)
    if crop is None:
        return False
    return looks_like_product_blob(
        crop.image, bg_median=median_background(frame_bgr)
    )


def pick_product_for_review(
    frame_bgr: Any,
    detections: list[Any],
    min_confidence: float,
) -> Any | None:
    """Pay-zone crop that actually contains a product, for admin SKU labeling.

    YOLO class names are *not* the filter. Stock weights call empty wood
    ``dining table``; custom weights may miss the bottle entirely. Admin
    then has nothing to label. Filter is: color blob on the ROI-masked
    counter that looks like packaging. The catalog SKU is chosen later
    on the review screen.
    """
    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return None

    yolo = pick_uncertain(detections, min_confidence)
    if yolo is not None and _crop_is_product(frame_bgr, yolo.x1, yolo.y1, yolo.x2, yolo.y2):
        return yolo

    from types import SimpleNamespace

    import numpy as np

    from app.services.region_detect import _without_person_torsos
    from app.vision.region_proposal import looks_like_product_blob, median_background, propose_regions

    persons = [
        d for d in detections
        if str(getattr(d, "class_name", "")).lower() == "person"
    ]
    work = _without_person_torsos(frame_bgr, persons, 0, 0)
    regions = propose_regions(
        work,
        min_area_frac=0.0012,
        max_area_frac=0.22,
        max_regions=12,
        bg_tolerance=38,
    )
    bg = median_background(work)
    accepted = [
        d for d in detections
        if getattr(d, "confidence", 0) is not None
        and float(d.confidence) >= min_confidence
        and is_product_review_class(str(getattr(d, "class_name", "")))
    ]
    # Wood grain at the ROI edge can pass the generic blob check (sat is
    # high on brown counter). Packaging is much further from the median
    # counter colour than that edge artifact (~50 vs 140+).
    min_bg_delta = 70.0
    best: Any | None = None
    best_delta = -1.0
    for r in regions:
        blob = work[
            max(0, r.y1) : min(work.shape[0], r.y2),
            max(0, r.x1) : min(work.shape[1], r.x2),
        ]
        if not looks_like_product_blob(blob, bg_median=bg):
            continue
        delta = 0.0
        if bg is not None and getattr(blob, "size", 0):
            delta = float(np.abs(blob.reshape(-1, 3).mean(axis=0) - bg).sum())
        if delta < min_bg_delta:
            continue
        probe = SimpleNamespace(
            x1=float(r.x1), y1=float(r.y1), x2=float(r.x2), y2=float(r.y2),
            class_name="", confidence=None,
        )
        if any(_box_iou(probe, d) >= 0.4 for d in accepted):
            continue
        if delta > best_delta:
            best_delta = delta
            best = probe
    return best


def pick_uncertain(detections: list[Any], min_confidence: float) -> Any | None:
    """Best candidate from this frame, or ``None``.

    "Best" means the *highest* confidence still under the threshold: that
    is the detection the model came closest to accepting, so it is the one
    where a human label most likely flips a wrong answer into a right one.

    Tra ve NGUYEN detection (khong chi ten lop + confidence) vi buoc chup
    can bbox de ve khung do va cat crop — mot khung hinh co hai san pham
    ma khong co bbox thi nguoi duyet khong biet AI dang hoi ve cai nao.
    """
    floor = _floor_confidence()
    best: Any | None = None
    best_conf: float | None = None
    for det in detections:
        conf = getattr(det, "confidence", None)
        name = getattr(det, "class_name", None)
        if conf is None or name is None:
            continue
        if str(name).lower() == "person":
            continue  # people aren't a trainable product class here
        if not is_product_review_class(str(name)):
            continue
        if floor <= conf < min_confidence and (best_conf is None or conf > best_conf):
            best, best_conf = det, float(conf)
    return best


def should_capture(camera_key: str) -> bool:
    """Rate-limit gate. Records the attempt so concurrent frames don't all
    pass at once."""
    if not _enabled():
        return False
    now = time.monotonic()
    last = _LAST_CAPTURE.get(camera_key)
    if last is not None and now - last < _cooldown_seconds():
        return False
    _LAST_CAPTURE[camera_key] = now
    return True


def _annotate_and_crop(frame_bgr: Any, det: Any) -> tuple[bytes | None, bytes | None]:
    """Ve khung do len ban sao khung hinh + cat rieng vung phat hien.

    Hai anh phuc vu hai nguoi dung khac nhau, va do la ly do can ca hai:

    * Khung hinh CO khung do — cho NGUOI duyet: mot canh co hai san pham
      ma khong khoanh vung thi khong biet AI dang hoi ve cai nao, va mot
      nhan gan nham doi tuong con te hon khong co nhan.
    * Crop — cho MAY hoc: classifier huan luyen tren anh cat mot san
      pham; neu lay nguyen khung canh lam mau huan luyen thi model hoc
      ca ke hang, nen nha va... cai khung do vua ve. Vi the khung do chi
      nam tren anh xem, tuyet doi khong nam tren anh hoc.
    """
    import cv2

    from app.vision.crop.cropper import crop_detection, is_degenerate_box

    annotated_jpg: bytes | None = None
    crop_jpg: bytes | None = None
    try:
        h, w = frame_bgr.shape[:2]
        x1, y1 = int(det.x1), int(det.y1)
        x2, y2 = int(det.x2), int(det.y2)
        canvas = frame_bgr.copy()
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 0, 255), 3)
        label = f"{det.class_name} {det.confidence:.2f}"
        cv2.putText(canvas, label, (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if ok:
            annotated_jpg = buf.tobytes()

        # Box trùm cả khung -> "crop" chỉ là ảnh cảnh chung, không phải sản
        # phẩm cận cảnh. KHÔNG lưu crop giả: để trống crop_key thì UI hiện mỗi
        # khung hình (trung thực) thay vì một ảnh cắt trông như cả cảnh mà lại
        # gắn mác "crop sản phẩm". Dấu hiệu detector chưa định vị được — xem
        # chẩn đoán về YOLO_MODEL cả-khung.
        if is_degenerate_box(det.x1, det.y1, det.x2, det.y2, w, h):
            logger.warning(
                "review: box trùm cả khung (%.0f%% diện tích) — detector chưa"
                " định vị, bỏ crop giả. class=%s",
                100.0 * max(0.0, (x2 - x1)) * max(0.0, (y2 - y1)) / float(max(1, w * h)),
                getattr(det, "class_name", "?"),
            )
        else:
            crop = crop_detection(frame_bgr, det.x1, det.y1, det.x2, det.y2)
            if crop is not None:
                from app.vision.region_proposal import looks_like_product_blob, median_background

                bg = median_background(frame_bgr)
                if not looks_like_product_blob(crop.image, bg_median=bg):
                    logger.warning(
                        "review: crop looks like empty counter, skip class=%s",
                        getattr(det, "class_name", "?"),
                    )
                    return annotated_jpg, None
                ok, buf = cv2.imencode(".jpg", crop.image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
                if ok:
                    crop_jpg = buf.tobytes()
    except Exception:  # noqa: BLE001 — annotation is an aid, never a blocker
        logger.exception("review annotate/crop failed")
    return annotated_jpg, crop_jpg


async def _upload(
    *,
    content: bytes,
    crop_content: bytes | None,
    bbox: dict[str, float] | None,
    organization_id: str,
    camera_id: str | None,
    predicted_class: str | None,
    confidence: float | None,
    source: str,
) -> None:
    url = f"{_backend_base_url().rstrip('/')}/ai/review/ingest"
    data: dict[str, str] = {"organization_id": organization_id, "source": source}
    if camera_id:
        data["camera_id"] = camera_id
    if predicted_class:
        data["predicted_class"] = predicted_class
    if confidence is not None:
        data["confidence"] = str(confidence)
    if bbox is not None:
        for k, v in bbox.items():
            data[f"bbox_{k}"] = str(v)
    files = {"file": ("frame.jpg", content, "image/jpeg")}
    if crop_content is not None:
        files["crop"] = ("crop.jpg", crop_content, "image/jpeg")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url, data=data, files=files, headers={"X-AI-Engine-Key": _api_key()}
            )
        if resp.status_code >= 300:
            logger.warning(
                "review ingest rejected (%s): %s", resp.status_code, resp.text[:200]
            )
    except Exception:  # noqa: BLE001 - never propagate into frame handling
        logger.exception("review ingest failed")


def capture_async(
    *,
    content: bytes,
    organization_id: str,
    camera_id: str | None,
    predicted_class: str | None,
    confidence: float | None,
    source: str = "low_confidence",
    frame_bgr: Any = None,
    detection: Any = None,
) -> None:
    """Schedule the upload without awaiting it.

    Keeping a reference to the task avoids the "task was destroyed but it
    is pending" warning that comes from letting a bare ``create_task``
    result get garbage-collected mid-flight.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop (sync context) — skip rather than block
        return

    # Ve khung + cat crop NGAY tai day (dong bo, vai ms mot khung) chu
    # khong trong task nen: frame_bgr la buffer pipeline tai su dung, doi
    # task chay 200ms sau thi noi dung da bi khung hinh ke tiep de len.
    crop_content: bytes | None = None
    bbox: dict[str, float] | None = None
    if frame_bgr is not None and detection is not None:
        cls = str(getattr(detection, "class_name", "") or "").strip()
        if cls and not is_product_review_class(cls):
            return
        annotated, crop_content = _annotate_and_crop(frame_bgr, detection)
        if crop_content is None:
            return
        if annotated is not None:
            content = annotated  # nguoi duyet xem ban co khung do
        bbox = {
            "x1": float(detection.x1), "y1": float(detection.y1),
            "x2": float(detection.x2), "y2": float(detection.y2),
        }

    task = loop.create_task(
        _upload(
            content=content,
            crop_content=crop_content,
            bbox=bbox,
            organization_id=organization_id,
            camera_id=camera_id,
            predicted_class=predicted_class,
            confidence=confidence,
            source=source,
        )
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


_BACKGROUND_TASKS: set[asyncio.Task] = set()
