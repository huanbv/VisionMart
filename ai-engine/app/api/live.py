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
`/detect` and `/capture`. Products are marked with colored dots at each
box center (not full rectangles — custom weights often emit giant boxes
that bury the counter). Persons keep a thin box. A HUD shows object
count, inference time, and achieved fps. Detection does NOT run on
every frame — YOLO inference on CPU is far slower than the stream's
target fps, so inference runs in one background task while capture/JPEG
delivery continues at camera speed. The last completed detection result is
held and redrawn until the next result arrives. This is a fine trade-off for
"watch it live and see markers appear," not analytics (the persisted
DetectionEvent pipeline in the backend — rtsp.scan_all — is the source of
truth for that).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from typing import Any

import cv2  # type: ignore[import-not-found]
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.security import require_api_key
from app.services.person_tracker import TRAJECTORY_PALETTE as _TRAJECTORY_PALETTE
from app.services.yolo_detector import YoloDetector
from app.vision.classify import get_classifier
from app.vision.crop.cropper import crop_detection
from app.vision.overlay.live_markers import draw_live_detections
from app.vision.overlay.presence import filter_overlay_ghosts
from app.vision.overlay.trajectory import draw_trajectory_tails
from app.vision.roi import (
    RoiZone,
    apply_roi,
    box_mostly_in_zones,
    point_in_zones,
    zone_union_bbox,
    zones_from_payload,
)

logger = logging.getLogger("ai-engine.live")

router = APIRouter(tags=["live"], dependencies=[Depends(require_api_key)])

_BOUNDARY = b"frame"
_MIN_FPS = 1.0
_MAX_FPS = 30.0
_MIN_DETECT_EVERY_N = 1
_MAX_DETECT_EVERY_N = 15

# Duoi nguong nay nhan SKU hien kem dau ? — xem muc _label_with_sku.
_LIVE_SKU_MIN_CONFIDENCE = 0.55


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
        if det.get("sku_label"):
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
        if det.get("sku_label"):
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


def _label_from_training(
    detections: list[dict],
    *,
    organization_id: str | None,
    branch_id: str | None,
    sku_names: dict[str, str],
) -> None:
    """Gắn tên sản phẩm đã train/deploy (class → SKU → tên catalog).

    Live đang hiện `du_sti 75%` vì overlay chỉ in class YOLO. Mapping từ
    /ai-training đã nằm trong class_to_sku.json — đọc ra để admin thấy
    "Gấu Đỏ" / "7Up" đúng như trang training.
    """
    if not organization_id or not detections:
        return
    from app.services.product_mapper import map_class_to_sku

    for det in detections:
        if str(det.get("class_name") or "").lower() == "person":
            continue
        sku = map_class_to_sku(
            organization_id, branch_id or "", str(det.get("class_name") or "")
        )
        if not sku:
            continue
        det["sku_label"] = sku_names.get(sku) or sku
        det["sku_confidence"] = float(det.get("confidence") or 0.0)


def _filter_by_zones(
    frame, detections: list[dict], zones: list[RoiZone]
) -> list[dict]:
    """Chỉ giữ box sản phẩm nằm phần lớn trong vùng ROI; người vẫn hiện.

    Lọc theo tâm box không đủ: model train bbox-cả-ảnh cho box khổng lồ
    phủ tượng ngựa bên trái, tâm vẫn rơi vào vùng thanh toán.
    """
    if not zones:
        return detections
    h, w = frame.shape[:2]
    out: list[dict] = []
    for det in detections:
        class_name = str(det.get("class_name") or "").lower()
        if class_name == "person":
            out.append(det)
            continue

        bbox = det.get("bbox") or {}
        try:
            x1, y1 = float(bbox["x1"]), float(bbox["y1"])
            x2, y2 = float(bbox["x2"]), float(bbox["y2"])
        except (KeyError, TypeError, ValueError):
            continue
        if box_mostly_in_zones(zones, x1, y1, x2, y2, w, h, min_frac=0.55) and point_in_zones(
            zones, (x1 + x2) / 2.0, (y1 + y2) / 2.0, w, h
        ):
            out.append(det)
    return out


def _draw_detections(frame, detections: list[dict]) -> None:
    """Mutates `frame` in place — product dots + thin person boxes."""
    draw_live_detections(frame, detections)


def _draw_trajectories(frame, trajectories: dict[int, list[tuple[float, float]]]) -> None:
    """Draw a short smoothed tail for each mapped person."""
    draw_trajectory_tails(frame, trajectories, _TRAJECTORY_PALETTE)


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


def _run_live_detection(
    detector: YoloDetector,
    frame,
    zones: list[RoiZone],
    camera_key: str,
    organization_id: str | None,
    branch_id: str | None,
    sku_names: dict[str, str],
) -> tuple[list[dict], float]:
    """Run the expensive overlay inference away from the video loop."""
    started = time.perf_counter()
    infer_src = frame
    roi_rect = None
    if zones:
        infer_src = apply_roi(frame, zones)
        roi_rect = zone_union_bbox(zones, frame.shape[1], frame.shape[0])
    detections = detector.detect_dense_bgr(infer_src, "overlay", roi_rect)
    detections = filter_overlay_ghosts(infer_src, detections)
    _label_from_training(
        detections,
        organization_id=organization_id,
        branch_id=branch_id,
        sku_names=sku_names,
    )
    _label_with_sku(frame, detections)

    from app.services.person_tracker import get_latest_person_boxes

    for tracked in get_latest_person_boxes(camera_key):
        bbox = tracked.get("bbox") or [0, 0, 0, 0]
        detections.append(
            {
                "class_name": "person",
                "confidence": 1.0,
                "sku_label": f"Khach hang #{tracked.get('mapped_id')}",
                "sku_confidence": 1.0,
                "bbox": {
                    "x1": int(bbox[0]),
                    "y1": int(bbox[1]),
                    "x2": int(bbox[2]),
                    "y2": int(bbox[3]),
                },
            }
        )
    return detections, (time.perf_counter() - started) * 1000.0


async def _mjpeg_frames(
    request: Request,
    stream_url: str,
    fps: float,
    open_timeout_ms: int,
    jpeg_quality: int,
    detect: bool,
    detect_every_n: int,
    zones: list[RoiZone] | None = None,
    organization_id: str | None = None,
    branch_id: str | None = None,
    sku_names: dict[str, str] | None = None,
):
    fps = max(_MIN_FPS, min(_MAX_FPS, fps))
    interval = 1.0 / fps
    detect_every_n = max(
        _MIN_DETECT_EVERY_N, min(_MAX_DETECT_EVERY_N, detect_every_n)
    )

    cap = await asyncio.to_thread(_open_capture, stream_url, open_timeout_ms)
    inference_task: asyncio.Task[tuple[list[dict], float]] | None = None
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

        camera_key = "default"
        try:
            import re
            _cam_match = re.search(r"cam-([a-f0-9-]{36})", stream_url, re.IGNORECASE)
            if _cam_match:
                camera_key = _cam_match.group(1)
        except Exception:
            camera_key = "default"

        while True:
            # Stop as soon as the client (backend proxy -> browser tab)
            # goes away instead of reading an RTSP/video source forever
            # with nobody watching.
            if await request.is_disconnected():
                break

            ok, frame = await asyncio.to_thread(cap.read)
            if not ok or frame is None:
                # Seek back to frame 0 for file-based streams
                try:
                    await asyncio.to_thread(cap.set, cv2.CAP_PROP_POS_FRAMES, 0)
                except Exception:
                    pass
                consecutive_failures += 1
                if consecutive_failures >= 10:
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

            # Collect a completed inference without ever blocking frame
            # delivery. Previously this loop awaited a 1.2s YOLO call inline,
            # freezing the MJPEG feed every third frame (~4.5 fps in practice).
            if inference_task is not None and inference_task.done():
                try:
                    last_detections, last_infer_ms = inference_task.result()
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "live stream: YOLO inference failed, "
                        "keeping last known boxes"
                    )
                finally:
                    inference_task = None

            # Keep at most one inference in flight. Copy the frame because
            # drawing/JPEG encoding below mutates the current ndarray while
            # the worker thread is reading its own inference input.
            if (
                detector is not None
                and inference_task is None
                and frame_index % detect_every_n == 0
            ):
                inference_task = asyncio.create_task(
                    asyncio.to_thread(
                        _run_live_detection,
                        detector,
                        frame.copy(),
                        zones or [],
                        camera_key,
                        organization_id,
                        branch_id,
                        sku_names or {},
                    )
                )

            if detector is not None:
                # Lọc theo vùng NGAY TRƯỚC khi vẽ (dùng kích thước khung hiện
                # tại), để panel chỉ hiện box trong vùng — khớp với giỏ.
                visible = _filter_by_zones(frame, last_detections, zones or [])
                # YOLO overlay ~1s/lần: bàn vừa trống vẫn giữ box cũ. Lọc
                # lại trên khung này (rẻ) để chấm ma biến ngay khi hết vật.
                gate_src = apply_roi(frame, zones) if zones else frame
                visible = filter_overlay_ghosts(gate_src, visible)
                try:
                    from app.services.person_tracker import get_all_trajectories_xy
                    _fh, _fw = frame.shape[:2]
                    _draw_trajectories(frame, get_all_trajectories_xy(camera_key, _fw, _fh))
                except Exception:  # noqa: BLE001
                    logger.exception("live stream: trajectory overlay failed")
                _draw_detections(frame, visible)
                _draw_hud(
                    frame,
                    object_count=len(visible),
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
            processing_time = time.perf_counter() - now
            sleep_duration = max(0.001, interval - processing_time)
            await asyncio.sleep(sleep_duration)
    finally:
        if inference_task is not None:
            inference_task.cancel()
            with suppress(asyncio.CancelledError):
                await inference_task
        await asyncio.to_thread(cap.release)


@router.get("/live")
async def live_stream(
    request: Request,
    stream_url: str = Query(..., min_length=1, max_length=1024),
    fps: float = Query(default=30.0, ge=_MIN_FPS, le=_MAX_FPS),
    open_timeout_ms: int = Query(default=5000, ge=500, le=30000),
    jpeg_quality: int = Query(default=90, ge=10, le=95),
    detect: bool = Query(default=True),
    detect_every_n: int = Query(
        default=3, ge=_MIN_DETECT_EVERY_N, le=_MAX_DETECT_EVERY_N
    ),
    roi_zones: str | None = Query(default=None, max_length=20000),
    organization_id: str | None = Query(default=None, max_length=64),
    branch_id: str | None = Query(default=None, max_length=64),
    sku_names: str | None = Query(default=None, max_length=20000),
) -> StreamingResponse:
    # roi_zones: JSON các vùng (toạ độ phân số) do backend chuyển xuống. Chỉ
    # để LỌC box hiển thị cho khớp giỏ; lỗi parse thì bỏ qua (panel vẫn chạy,
    # chỉ mất phần lọc) — không bao giờ làm hỏng luồng.
    zones: list[RoiZone] = []
    if roi_zones:
        try:
            zones = zones_from_payload(json.loads(roi_zones))
        except Exception:  # noqa: BLE001
            logger.warning("live stream: roi_zones parse lỗi, bỏ lọc vùng", exc_info=True)
            zones = []
    names: dict[str, str] = {}
    if sku_names:
        try:
            parsed = json.loads(sku_names)
            if isinstance(parsed, dict):
                names = {str(k): str(v) for k, v in parsed.items()}
        except Exception:  # noqa: BLE001
            logger.warning("live stream: sku_names parse lỗi", exc_info=True)
    return StreamingResponse(
        _mjpeg_frames(
            request,
            stream_url,
            fps,
            open_timeout_ms,
            jpeg_quality,
            detect,
            detect_every_n,
            zones,
            organization_id,
            branch_id,
            names,
        ),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY.decode()}",
    )
