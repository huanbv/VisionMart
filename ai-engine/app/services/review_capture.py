"""Auto-capture of uncertain frames for the active-learning queue.

Detections below ``min_confidence`` are dropped by the frame endpoint —
which is correct for business logic, but those are precisely the frames a
new label is worth the most on. This module forwards a sample of them to
the backend review queue, where a human confirms the label before it
becomes training data.

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

    from app.vision.crop.cropper import crop_detection

    annotated_jpg: bytes | None = None
    crop_jpg: bytes | None = None
    try:
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

        crop = crop_detection(frame_bgr, det.x1, det.y1, det.x2, det.y2)
        if crop is not None:
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
        annotated, crop_content = _annotate_and_crop(frame_bgr, detection)
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
