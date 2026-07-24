"""Continuous MJPEG live-view stream for a camera's stream_url.

Unlike `/capture` (opens a fresh `cv2.VideoCapture`, reads exactly one
frame, closes) this endpoint keeps a single `cv2.VideoCapture` open for
the lifetime of the HTTP connection and continuously pushes frames as a
`multipart/x-mixed-replace` stream — the same MJPEG format IP cameras
themselves often serve natively, and something every browser already
knows how to decode frame-by-frame. See docs/21_CAMERA_MANAGER.md
("Real-time Streaming Design") for where this fits in the wider design;
this is the pragmatic MJPEG implementation of that section rather than
the WebRTC/HLS path also described there.

The backend proxies this endpoint (see camera_router.py's
`/cameras/{id}/live`) rather than exposing it to the browser directly —
same "AI Engine isolation" boundary every other route here respects.

Optional live YOLO overlay (`detect=true`, the default): every
`detect_every_n`-th frame is run through the same `YoloDetector` used by
`/detect` and `/capture`, and the resulting boxes/labels are burned
directly into the frames sent to the browser, along with a small HUD
(object count, inference time, achieved fps). Detection does NOT run on
every frame — YOLO inference on CPU is far slower than the stream's
target fps, so running it every frame would make the stream stutter
badly. Instead the last detection result is held and redrawn on the
frames in between, which is a fine trade-off for "watch it live and see
boxes appear," not analytics (the persisted DetectionEvent pipeline in
the backend — rtsp.scan_all — is the source of truth for that).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import cv2  # type: ignore[import-not-found]
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.security import require_api_key
from app.services.yolo_detector import YoloDetector
from app.vision.classify import get_classifier
from app.vision.crop.cropper import crop_detection

logger = logging.getLogger("ai-engine.live")

router = APIRouter(tags=["live"], dependencies=[Depends(require_api_key)])

_BOUNDARY = b"frame"
_MIN_FPS = 1.0
_MAX_FPS = 15.0
_MAX_CONSECUTIVE_FAILURES = 10
_MIN_DETECT_EVERY_N = 1
_MAX_DETECT_EVERY_N = 15

# Sci-fi-HUD-ish palette — cycled by class name so the same class always
# gets the same color within a stream (helps the eye track "that's the
# person box, that's the bottle box" at a glance). BGR, since that's what
# cv2 wants.
_PALETTE: list[tuple[int, int, int]] = [
    (80, 220, 60),   # green
    (60, 200, 255),  # amber
    (255, 190, 40),  # cyan-blue
    (170, 90, 255),  # magenta
    (60, 120, 255),  # orange
    (255, 255, 90),  # light cyan
    (120, 60, 255),  # red-violet
]


# Duoi nguong nay nhan SKU hien kem dau ? — xem muc _label_with_sku.
_LIVE_SKU_MIN_CONFIDENCE = 0.55


def _class_color(class_name: str) -> tuple[int, int, int]:
    return _PALETTE[hash(class_name) % len(_PALETTE)]


def _open_capture(stream_url: str, open_timeout_ms: int) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, open_timeout_ms)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, open_timeout_ms)
    except Exception:  # pragma: no cover — older OpenCV builds
        pass
    return cap


def _label_with_sku(frame, detections: list[dict]) -> None:
    """Gan ten SKU vao tung detection, sua truc tiep trong `detections`.

    Truoc day man hinh xem truc tiep ve thang ten lop cua YOLO, nen mot chai
    7up hien la "bottle" — dung voi detector nhung vo nghia voi nguoi ban
    hang, va khong cho biet bo phan loai SKU dang nghi gi. Bo phan loai von
    da chay san trong luong /ai/frame; o day goi lai chinh no nen nhan hien
    tren man hinh khop voi thu he thong thuc su dua vao gio hang.

    Chay theo lo: tren CPU chi phi moi lan goi lan at chi phi tinh toan, nen
    phan loai ca 3 mon trong khung cung luc gan bang phan loai mot mon.

    Moi that bai deu bo qua trong im lang va giu nguyen nhan goc cua YOLO:
    day chi la lop hien thi, khong duoc phep lam hong luong video.
    """
    classifier = get_classifier()
    if classifier is None or not detections:
        return

    targets: list[tuple[dict, Any]] = []
    for det in detections:
        if str(det.get("class_name") or "").lower() == "person":
            continue
        bbox = det.get("bbox") or {}
        try:
            crop = crop_detection(
                frame,
                float(bbox["x1"]),
                float(bbox["y1"]),
                float(bbox["x2"]),
                float(bbox["y2"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if crop is not None:
            targets.append((det, crop))

    if not targets:
        return

    try:
        results = classifier.classify_batch([c.image for _, c in targets])
    except Exception:  # noqa: BLE001
        logger.exception("live stream: SKU classification failed, keeping YOLO labels")
        return

    for (det, _), res in zip(targets, results):
        if res is None:
            continue
        # Duoi nguong thi noi ro la "khong chac" thay vi im lang hien ten
        # san pham: mot nhan sai nhung trong day tu tin con nguy hiem hon
        # nhan "bottle" trung thuc, vi nguoi dung se tin no.
        if res.confidence >= _LIVE_SKU_MIN_CONFIDENCE:
            det["sku_label"] = res.sku
            det["sku_confidence"] = res.confidence
        else:
            det["sku_label"] = f"? {res.sku}"
            det["sku_confidence"] = res.confidence


def _draw_detections(frame, detections: list[dict]) -> None:
    """Mutates `frame` in place, drawing a box + label per detection."""
    for det in detections:
        bbox = det.get("bbox") or {}
        try:
            x1, y1 = int(bbox["x1"]), int(bbox["y1"])
            x2, y2 = int(bbox["x2"]), int(bbox["y2"])
        except (KeyError, TypeError, ValueError):
            continue
        class_name = str(det.get("class_name") or "object")
        confidence = float(det.get("confidence") or 0.0)
        color = _class_color(class_name)

        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

        # Uu tien ten SKU khi bo phan loai da nhan ra; van giu ten lop YOLO
        # trong ngoac de con truy duoc tang nao dang sai khi ket qua la la.
        sku_label = det.get("sku_label")
        if sku_label:
            sku_conf = float(det.get("sku_confidence") or 0.0)
            label = f"{sku_label} {sku_conf * 100:.0f}% ({class_name})"
        else:
            label = f"{class_name} {confidence * 100:.0f}%"
        (tw, th), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
        )
        label_y1 = max(0, y1 - th - baseline - 4)
        cv2.rectangle(frame, (x1, label_y1), (x1 + tw + 6, y1), color, -1)
        cv2.putText(
            frame,
            label,
            (x1 + 3, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (20, 20, 20),
            1,
            cv2.LINE_AA,
        )


def _draw_hud(
    frame,
    *,
    object_count: int,
    infer_ms: float | None,
    fps: float,
    model_name: str,
) -> None:
    """Small translucent status bar, top-left — camera-name/timestamp are
    left to the frontend (it already shows those around the video); this
    only shows numbers the ai-engine actually knows about this frame.
    """
    h, w = frame.shape[:2]
    bar_h = max(28, h // 18)
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (15, 15, 15), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, dst=frame)

    infer_text = f"{infer_ms:.0f}ms" if infer_ms is not None else "--"
    text = (
        f"AI VISION  |  {model_name}  |  {object_count} object(s)  |  "
        f"infer {infer_text}  |  {fps:.1f} fps"
    )
    scale = 0.42 if w < 960 else 0.5
    cv2.putText(
        frame,
        text,
        (8, int(bar_h * 0.68)),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        (90, 255, 140),
        1,
        cv2.LINE_AA,
    )


async def _mjpeg_frames(
    request: Request,
    stream_url: str,
    fps: float,
    open_timeout_ms: int,
    jpeg_quality: int,
    detect: bool,
    detect_every_n: int,
):
    fps = max(_MIN_FPS, min(_MAX_FPS, fps))
    interval = 1.0 / fps
    detect_every_n = max(
        _MIN_DETECT_EVERY_N, min(_MAX_DETECT_EVERY_N, detect_every_n)
    )

    cap = await asyncio.to_thread(_open_capture, stream_url, open_timeout_ms)
    try:
        if not cap.isOpened():
            logger.warning("live stream: could not open %s", stream_url)
            return

        detector: YoloDetector | None = None
        if detect:
            try:
                detector = await asyncio.to_thread(YoloDetector.get)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "live stream: failed to load YOLO model, "
                    "continuing without detection overlay"
                )
                detector = None

        last_detections: list[dict] = []
        last_infer_ms: float | None = None
        frame_index = 0
        consecutive_failures = 0
        # Rolling achieved-fps estimate (exponential moving average) --
        # what actually reaches the browser, not the requested `fps`.
        achieved_fps = fps
        last_tick = time.perf_counter()

        while True:
            # Stop as soon as the client (backend proxy -> browser tab)
            # goes away instead of reading an RTSP/video source forever
            # with nobody watching.
            if await request.is_disconnected():
                break

            ok, frame = await asyncio.to_thread(cap.read)
            if not ok or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    logger.warning(
                        "live stream: %d consecutive read failures, stopping %s",
                        consecutive_failures,
                        stream_url,
                    )
                    break
                await asyncio.sleep(interval)
                continue
            consecutive_failures = 0
            frame_index += 1

            now = time.perf_counter()
            delta = now - last_tick
            last_tick = now
            if delta > 0:
                instant_fps = 1.0 / delta
                achieved_fps = (achieved_fps * 0.8) + (instant_fps * 0.2)

            if detector is not None and frame_index % detect_every_n == 0:
                ok3, det_buf = cv2.imencode(".jpg", frame)
                if ok3:
                    started = time.perf_counter()
                    try:
                        last_detections = await detector.detect(
                            det_buf.tobytes()
                        )
                        # Chi phan loai o dung nhung khung vua chay detector
                        # (moi detect_every_n khung), khong phai moi khung —
                        # nhan duoc giu lai va ve lai cho toi lan detect sau.
                        _label_with_sku(frame, last_detections)
                        last_infer_ms = (time.perf_counter() - started) * 1000.0
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "live stream: YOLO inference failed, "
                            "keeping last known boxes"
                        )

            if detector is not None:
                _draw_detections(frame, last_detections)
                _draw_hud(
                    frame,
                    object_count=len(last_detections),
                    infer_ms=last_infer_ms,
                    fps=achieved_fps,
                    model_name=detector.model_name,
                )

            ok2, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
            )
            if not ok2:
                await asyncio.sleep(interval)
                continue

            chunk = buf.tobytes()
            yield (
                b"--" + _BOUNDARY + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(chunk)).encode("ascii") + b"\r\n\r\n"
                + chunk + b"\r\n"
            )
            await asyncio.sleep(interval)
    finally:
        await asyncio.to_thread(cap.release)


@router.get("/live")
async def live_stream(
    request: Request,
    stream_url: str = Query(..., min_length=1, max_length=1024),
    fps: float = Query(default=8.0, ge=_MIN_FPS, le=_MAX_FPS),
    open_timeout_ms: int = Query(default=5000, ge=500, le=30000),
    jpeg_quality: int = Query(default=70, ge=10, le=95),
    detect: bool = Query(default=True),
    detect_every_n: int = Query(
        default=3, ge=_MIN_DETECT_EVERY_N, le=_MAX_DETECT_EVERY_N
    ),
) -> StreamingResponse:
    return StreamingResponse(
        _mjpeg_frames(
            request,
            stream_url,
            fps,
            open_timeout_ms,
            jpeg_quality,
            detect,
            detect_every_n,
        ),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY.decode()}",
    )
