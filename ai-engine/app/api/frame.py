"""End-to-end frame processing for AI-assisted checkout detection.

AI's job stops at proposing events (product_picked_up / product_returned /
checkout_initiated) to the backend — it never charges anyone. The backend
decides whether to accept the proposal and, for checkout_initiated, freezes
the cart into a "pending checkout" state that always requires an explicit
human confirmation (customer via QR, or staff) before any payment happens.
See backend/app/modules/sales/application/cart_service.py.

Pipeline (per uploaded frame):
  1. Run YOLOv8 + ByteTrack on the frame (persistent per camera).
  2. Split tracked objects into `persons` and `products` (using the
     class-to-SKU mapping — anything not mappable and not `person` is ignored).
  3. Associate each product detection with the nearest person's track_id
     (Euclidean bbox-center distance).
  4. Apply a per-track cooldown to suppress duplicate `product_picked_up`
     events for the same product within a short window.
  5. Emit one AI cart event per product + person association, forwarded to
     the backend `/ai/cart-events` inbox.
  6. Track which (track, sku) pairs are currently "held" (paired) so that
     when a previously-held product stops being paired with that same
     person — while the person is still visible in frame — for longer than
     ``PRODUCT_RETURN_MISSING_SECONDS``, emit `product_returned`. This is a
     proximity heuristic (no separate "shelf zone" detector): it cannot
     distinguish "put back on the shelf" from "occluded for a few seconds",
     which is why the missing-window is deliberately a few seconds, not
     instant.
  7. If the camera is marked as a checkout zone AND at least one person is
     present, additionally emit `checkout_initiated` for each such track.
  8. Optionally run face recognition and attach `customer_id` when a match
     is found.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.security import require_api_key
from app.services.face_recognizer import get_face_recognizer
from app.services.person_tracker import (
    TrackedObject,
    get_last_vision_result,
    track_frame_detailed,
)
from app.services.product_mapper import map_class_to_sku
from app.services import review_capture, sku_identifier, telemetry_client
from app.vision.config import get_vision_config
from app.vision.roi import zones_from_payload
from app.vision.storage import step_writer

logger = logging.getLogger("ai-engine.frame")

router = APIRouter(prefix="/ai", tags=["ai-frame"], dependencies=[Depends(require_api_key)])

_COOLDOWN: dict[str, float] = {}
_CAMERA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CAMERA_TTL_SECONDS = 30.0

# --- "held product" state for product_returned detection ---
# track_key -> {sku: last_seen_ts} for skus that were picked up and are
# still being tracked as "in this person's hands".
_HELD: dict[str, dict[str, float]] = {}
# track_key -> last time this person was seen at all (any camera frame),
# used only to garbage-collect stale entries above — not for return logic.
_TRACK_LAST_SEEN: dict[str, float] = {}
_LAST_CLEANUP_TS = 0.0
_CLEANUP_INTERVAL_SECONDS = 60.0
_STALE_TRACK_SECONDS = 120.0

# --- phiên checkout theo từng camera quầy ---
# camera_key -> (thời điểm quét gần nhất, số thứ tự phiên). Mỗi khách ở quầy
# là một "phiên": khi có khoảng lặng (không quét được sản phẩm nào) đủ dài,
# khách trước coi như đã rời, lần quét kế mở phiên mới -> giỏ mới. Nếu không,
# mọi khách qua quầy dồn chung một giỏ (lỗi "nhiều người thành một đơn").
_CHECKOUT_SESSION: dict[str, tuple[float, int]] = {}

# Khử trùng lặp + đối soát cho quầy: mỗi phiên khách đếm mỗi SKU MỘT lần, và
# tự gỡ khỏi giỏ khi SKU biến mất khỏi khung đủ lâu. Key =
# "<camera_key>:<checkout_track>" (đổi khi sang khách mới) -> { sku: lần thấy
# cuối (giây, cùng đồng hồ với biến `now` = time.time() trong frame) }.
#
# Vì sao KHÔNG dùng cooldown theo track như trước: sản phẩm đặt yên trên quầy
# sống lâu hơn cooldown 5s nên bị đếm lại; track_id của đề xuất contour đổi khi
# vật xê dịch nhẹ nên mỗi lần thành "track mới" -> đếm lại. Cả hai làm 1 sản
# phẩm thành 2-3. Khoá theo (phiên, SKU) loại bỏ cả hai.
#
# Đối soát: mỗi khung cập nhật "lần thấy cuối" cho SKU đang hiện; SKU đã ghi
# nhận mà vắng mặt lâu hơn CHECKOUT_ABSENT_SECONDS thì phát product_returned để
# GỠ khỏi giỏ — nên món nhận nhầm (vd Hảo Hảo thoáng qua) không bị khoá cứng,
# và giỏ luôn phản ánh những gì đang thực sự trên quầy.
#
# Đánh đổi: một khách đặt 2 sản phẩm CÙNG loại chỉ tính 1 (không có tracking
# ổn định thì không phân biệt "2 cái giống nhau" với "1 cái thấy hai lần").
_CHECKOUT_SCANNED: dict[str, dict[str, float]] = {}


def _checkout_absent_seconds() -> float:
    """Vắng mặt bao lâu (giây) thì gỡ SKU khỏi giỏ quầy. Đủ lớn để nhiễu nhận
    diện thoáng qua không làm món thật nhấp nháy; đủ nhỏ để nhấc sản phẩm ra là
    giỏ cập nhật kịp. Chỉnh bằng CHECKOUT_ABSENT_SECONDS."""
    try:
        return float(os.getenv("CHECKOUT_ABSENT_SECONDS", "5"))
    except ValueError:
        return 5.0


def _backend_base_url() -> str:
    return os.getenv("BACKEND_BASE_URL", "http://backend:8000/api/v1")


def _api_key() -> str:
    return os.getenv("AI_ENGINE_API_KEY", "change-me-ai-engine-key")


def _cooldown_seconds() -> float:
    try:
        return float(os.getenv("TRACK_PICK_COOLDOWN_SECONDS", "5"))
    except ValueError:
        return 5.0


def _checkout_gap_seconds() -> float:
    """Khoảng lặng (giây) để coi là khách mới ở quầy. Không quét được sản
    phẩm nào lâu hơn ngần này -> khách trước đã rời, mở phiên/giỏ mới.

    Đánh đổi: quá ngắn thì một khách quét chậm (ngập ngừng) bị tách làm hai
    giỏ; quá dài thì hai khách liền nhau bị gộp một giỏ. 25 giây là mặc định
    cân bằng; chỉnh bằng biến CHECKOUT_SESSION_GAP_SECONDS.
    """
    try:
        return float(os.getenv("CHECKOUT_SESSION_GAP_SECONDS", "25"))
    except ValueError:
        return 25.0


def _checkout_session_track(camera_key: str, now: float, has_products: bool) -> str:
    """track_id gửi backend cho quầy, xoay theo khoảng lặng để tách khách.

    Backend suy session giỏ từ track_id, nên đổi track_id = mở giỏ mới. Khoảng
    lặng đo bằng thời gian kể từ lần cuối quầy CÓ SẢN PHẨM, không phải kể từ
    khung trước — vì nhánh này chạy mỗi khung kể cả khung trống. Nếu cập nhật
    'last' mỗi khung thì 'now - last' luôn ~1 khung, KHÔNG BAO GIỜ vượt gap ->
    epoch không xoay -> mọi khách dồn chung một giỏ (đúng lỗi đang gặp). Vì thế
    chỉ chạm 'last' khi has_products: quầy trống đủ lâu (khách rời) thì lần đặt
    kế của khách sau mới vượt gap và mở giỏ mới.

    Chuỗi 'checkout-<epoch>' ngắn, an toàn với giới hạn cột session_id.
    """
    last, epoch = _CHECKOUT_SESSION.get(camera_key, (0.0, 0))
    if not has_products:
        # Khung trống: KHÔNG chạm 'last' để khoảng lặng tích luỹ. Trả epoch
        # hiện tại (không có sản phẩm nào để gán nên giá trị này không dùng tới).
        return f"checkout-{epoch}"
    gap = _checkout_gap_seconds()
    if now - last > gap:
        epoch += 1
    _CHECKOUT_SESSION[camera_key] = (now, epoch)
    return f"checkout-{epoch}"


def _return_missing_seconds() -> float:
    try:
        return float(os.getenv("PRODUCT_RETURN_MISSING_SECONDS", "3"))
    except ValueError:
        return 3.0


def _cleanup_stale_state(now: float) -> None:
    """Opportunistic GC for the module-level dicts above.

    None of `_COOLDOWN` / `_HELD` / `_TRACK_LAST_SEEN` ever had entries
    removed before — over a long-running ai-engine process watching many
    distinct tracks (a busy store, days of uptime) they'd grow without
    bound. Throttled to run at most once per `_CLEANUP_INTERVAL_SECONDS`
    since it's O(n) over all tracked keys.
    """
    global _LAST_CLEANUP_TS
    if now - _LAST_CLEANUP_TS < _CLEANUP_INTERVAL_SECONDS:
        return
    _LAST_CLEANUP_TS = now

    stale_tracks = [
        key
        for key, last_seen in _TRACK_LAST_SEEN.items()
        if now - last_seen > _STALE_TRACK_SECONDS
    ]
    for key in stale_tracks:
        _TRACK_LAST_SEEN.pop(key, None)
        _HELD.pop(key, None)

    stale_cooldowns = [
        key
        for key, last in _COOLDOWN.items()
        if now - last > _STALE_TRACK_SECONDS
    ]
    for key in stale_cooldowns:
        _COOLDOWN.pop(key, None)


async def _fetch_camera(camera_id: uuid.UUID) -> dict[str, Any] | None:
    key = str(camera_id)
    now = time.time()
    cached = _CAMERA_CACHE.get(key)
    if cached and (now - cached[0]) < _CAMERA_TTL_SECONDS:
        return cached[1]
    url = f"{_backend_base_url().rstrip('/')}/ai/cameras/{camera_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"X-AI-Engine-Key": _api_key()})
        if resp.status_code >= 400:
            return None
        data = resp.json()
        _CAMERA_CACHE[key] = (now, data)
        return data
    except httpx.HTTPError:
        logger.exception("fetch camera failed")
        return None


async def _lookup_customer_by_face(
    organization_id: uuid.UUID, ref: str
) -> uuid.UUID | None:
    url = f"{_backend_base_url().rstrip('/')}/ai/customers/by-face-ref"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                headers={"X-AI-Engine-Key": _api_key()},
                params={"organization_id": str(organization_id), "ref": ref},
            )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        if not data:
            return None
        return uuid.UUID(str(data["id"]))
    except (httpx.HTTPError, KeyError, ValueError):
        return None


async def _post_event(event: dict[str, Any]) -> dict[str, Any]:
    url = f"{_backend_base_url().rstrip('/')}/ai/cart-events"
    headers = {"X-AI-Engine-Key": _api_key(), "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=event, headers=headers)
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": resp.text}
    return {"status": resp.status_code, "body": body}


def _track_key(camera_key: str, local_track_id: int) -> str:
    """Build a track key that is unique across cameras.

    ByteTrack assigns small sequential integers *per tracker instance*
    (person_tracker.py keeps one tracker per camera_key), so a bare
    "person-3" collides whenever two different cameras happen to both be
    tracking a "track 3" at the same time — the backend would then treat
    two different shoppers on two different cameras as the same cart
    session (`session_id = f"track:{event.track_id}"`), merging their carts.
    Prefixing with camera_key makes the id unique across the whole store.
    """
    return f"{camera_key}:person-{local_track_id}"


def _collect_debug_steps(
    debug: "step_writer.DebugCollector",
    frame_bgr: Any,
    detections: list[TrackedObject],
    identified: dict[Any, Any],
    products: list[tuple[TrackedObject, str]],
) -> None:
    """Render the post-detection DEBUG_AI steps.

    Split out of the handler because it is pure diagnostics: keeping it here
    means the request path reads as the pipeline, not as the pipeline
    interleaved with drawing code. Every failure is swallowed — a debug
    render must never turn a good frame into a 500.
    """
    import cv2

    try:
        # 03 — what the detector found, boxed on the frame it actually saw.
        boxed = frame_bgr.copy()
        for det in detections:
            colour = (0, 200, 255) if det.class_name.lower() == "person" else (0, 220, 0)
            cv2.rectangle(
                boxed,
                (int(det.x1), int(det.y1)),
                (int(det.x2), int(det.y2)),
                colour,
                2,
            )
            cv2.putText(
                boxed,
                f"{det.class_name} {det.confidence:.2f}",
                (int(det.x1), max(12, int(det.y1) - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                colour,
                1,
                cv2.LINE_AA,
            )
        debug.add("detection", boxed, count=len(detections))

        # 04/06 — the crop the classifier was actually given, and the
        # classifier's verdict on it. One representative object rather than
        # all of them: the point is to answer "was the crop sane?", and
        # writing N crops per frame would multiply storage by the scene's
        # object count.
        first = next(
            (i for i in identified.values() if getattr(i, "crop", None) is not None),
            None,
        )
        if first is not None:
            debug.add(
                "crop",
                first.crop.image,
                box=[first.crop.x1, first.crop.y1, first.crop.x2, first.crop.y2],
            )
            debug.add(
                "classifier",
                first.crop.image,
                sku=first.match.sku,
                confidence=first.match.confidence,
                source=first.match.source,
                reason=first.match.reason,
            )

        # 08 — the final answer: only the objects that resolved to a SKU.
        result = frame_bgr.copy()
        for det, sku in products:
            cv2.rectangle(
                result,
                (int(det.x1), int(det.y1)),
                (int(det.x2), int(det.y2)),
                (255, 120, 0),
                2,
            )
            cv2.putText(
                result,
                sku,
                (int(det.x1), max(12, int(det.y1) - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 120, 0),
                2,
                cv2.LINE_AA,
            )
        debug.add("result", result, products=len(products))

        debug.meta(
            detection_count=len(detections),
            product_count=len(products),
            classified_count=len(identified),
            skus=[sku for _, sku in products],
        )
    except Exception:  # noqa: BLE001
        logger.exception("DEBUG_AI: step rendering failed")


async def _report_telemetry(
    *,
    camera_key: str,
    organization_id: Any,
    branch_id: Any,
    camera_id: Any,
    cfg: Any,
    tracking: Any,
    detections: list[TrackedObject],
    identified: dict[Any, Any],
    products: list[tuple[TrackedObject, str]],
    storage_prefix: str | None,
) -> None:
    """Assemble and buffer this frame's telemetry report.

    Kept out of the handler because it is pure reporting — the frame's
    result does not depend on any of it. Only ``ensure_session`` touches
    the network, and only once per camera per process.
    """
    session_id = await telemetry_client.ensure_session(
        camera_key,
        organization_id=str(organization_id),
        branch_id=str(branch_id) if branch_id else None,
        camera_id=str(camera_id) if camera_id else None,
        cfg=cfg,
    )
    if not session_id:
        return

    vision = get_last_vision_result(camera_key) or {}
    quality = vision.get("quality") or {}
    sku_by_track = {d.track_id: sku for d, sku in products}

    det_payload = []
    for det in detections:
        item = identified.get(det.track_id)
        classification = getattr(item, "classification", None) if item else None
        entry: dict[str, Any] = {
            "track_id": det.track_id,
            "class_name": det.class_name,
            "confidence": det.confidence,
            "x1": det.x1, "y1": det.y1, "x2": det.x2, "y2": det.y2,
            "sku": sku_by_track.get(det.track_id),
            "source": getattr(item.match, "source", None) if item else None,
            "combined_confidence": (
                getattr(item.match, "final_confidence", None) if item else None
            ),
        }
        if classification is not None:
            entry["classification"] = {
                "sku": classification.sku,
                "confidence": classification.confidence,
                "label_index": getattr(classification, "label_index", None),
                "runner_up_sku": getattr(classification, "runner_up_sku", None),
                "runner_up_confidence": getattr(
                    classification, "runner_up_confidence", None
                ),
                "margin": getattr(classification, "margin", None),
                "model_version": getattr(classification, "model_version", None),
            }
        det_payload.append(entry)

    frame_shape = getattr(tracking.frame_bgr, "shape", None)
    telemetry_client.report_frame(
        camera_key,
        {
            "organization_id": str(organization_id),
            "seq": telemetry_client.next_seq(camera_key),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "width": int(frame_shape[1]) if frame_shape else None,
            "height": int(frame_shape[0]) if frame_shape else None,
            "storage_prefix": storage_prefix,
            "brightness": quality.get("brightness"),
            "contrast": quality.get("contrast"),
            "blur_score": quality.get("blur_score"),
            "quality_score": quality.get("quality_score"),
            # `is_low_quality` is the pipeline's own verdict, so the
            # dashboard's reject count matches what actually happened
            # rather than re-deriving it from thresholds.
            "gate_passed": not bool(quality.get("is_low_quality")),
            "reject_reason": quality.get("reason"),
            "preprocess_ms": tracking.opencv_ms,
            "detect_ms": tracking.yolo_bytetrack_ms,
            "total_ms": vision.get("total_ms"),
            "detections": det_payload,
        },
    )


def _pair_products_with_persons(
    persons: list[TrackedObject],
    products: list[tuple[TrackedObject, str]],
    camera_key: str,
) -> list[tuple[str, TrackedObject, str]]:
    pairs: list[tuple[str, TrackedObject, str]] = []
    if not persons:
        return pairs
    for product, sku in products:
        best: tuple[float, TrackedObject] | None = None
        for person in persons:
            d = math.hypot(person.cx - product.cx, person.cy - product.cy)
            if best is None or d < best[0]:
                best = (d, person)
        if best is None:
            continue
        track_key = _track_key(camera_key, best[1].track_id)
        pairs.append((track_key, product, sku))
    return pairs


def _cooldown_ok(track_key: str, sku: str) -> bool:
    key = f"{track_key}:{sku}"
    now = time.time()
    last = _COOLDOWN.get(key, 0.0)
    if now - last < _cooldown_seconds():
        return False
    _COOLDOWN[key] = now
    return True


@router.post("/frame")
async def process_frame(
    organization_id: uuid.UUID = Form(...),
    branch_id: uuid.UUID = Form(...),
    camera_id: uuid.UUID | None = Form(None),
    recognize_face: bool = Form(False),
    min_confidence: float = Form(0.4),
    image: UploadFile = File(...),
) -> dict[str, Any]:
    content = await image.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty image upload")

    camera_key = str(camera_id) if camera_id else f"{organization_id}:{branch_id}"

    # DEBUG_AI: collects one image per pipeline step and hands the set to a
    # background queue at the end. A no-op object when the flag is off, so
    # the `.add(...)` calls below need no guards. Never awaited — see
    # app/vision/storage/step_writer.py for why storage must not block a
    # frame.
    debug = step_writer.DebugCollector(
        camera_key, enabled=step_writer.should_debug(get_vision_config())
    )
    if debug.enabled:
        # The raw frame as it arrived, before any enhancement. Requires a
        # second decode (the pipeline's own decode result is not returned
        # separately), which is why it is paid only while debugging.
        try:
            import cv2
            import numpy as np

            original = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
            debug.add("original", original, bytes=len(content))
        except Exception:  # noqa: BLE001
            logger.exception("DEBUG_AI: could not decode original frame")

    # Fetched here (rather than after track_frame, as before this Sprint)
    # only so `is_checkout_zone` can be forwarded into track_frame for a
    # more informative debug overlay label — the value itself and every
    # other use of `camera_info` below is unchanged.
    camera_info: dict[str, Any] | None = None
    if camera_id is not None:
        camera_info = await _fetch_camera(camera_id)

    try:
        # Detailed variant so the SKU-classifier stage below can crop from
        # the same preprocessed frame YOLO saw, without re-preprocessing.
        # Vung nhan dien ve tren Admin di kem camera_info (da duoc cache
        # 30s trong _fetch_camera) — khong them mot luot goi mang nao.
        roi_zones = zones_from_payload(
            (camera_info or {}).get("roi_zones")
        )
        tracking = await track_frame_detailed(
            content,
            camera_key,
            is_checkout_zone=bool(camera_info and camera_info.get("is_checkout_zone")),
            roi_zones=roi_zones,
        )
        detections = tracking.detections
        debug.add(
            "preprocess",
            tracking.frame_bgr,
            opencv_ms=tracking.opencv_ms,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("tracking failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    # Active learning: the detections dropped just below the threshold are
    # the ones a human label is worth the most on, so a rate-limited sample
    # is forwarded to the review queue. Fire-and-forget and disabled by
    # default — see app/services/review_capture.py.
    if review_capture.should_capture(camera_key):
        uncertain_det = review_capture.pick_uncertain(detections, min_confidence)
        if uncertain_det is not None:
            # Truyen frame DA tien xu ly (tracking.frame_bgr) chu khong phai
            # anh goc: bbox nam trong he toa do cua frame nay — ve khung do
            # len anh goc khi ROI/resize da chay se khoanh lech vung.
            review_capture.capture_async(
                content=content,
                organization_id=str(organization_id),
                camera_id=str(camera_id) if camera_id else None,
                predicted_class=str(uncertain_det.class_name),
                confidence=float(uncertain_det.confidence),
                frame_bgr=tracking.frame_bgr,
                detection=uncertain_det,
            )

    persons: list[TrackedObject] = []
    products: list[tuple[TrackedObject, str]] = []

    # Second model stage (crop -> SKU classifier -> match). Only runs when
    # ENABLE_SKU_CLASSIFIER is on; otherwise `identified` stays None and
    # the original class-map path below is used unchanged.
    identified: dict[Any, Any] = {}
    vision_cfg = get_vision_config()
    if vision_cfg.enable_sku_classifier:
        try:
            for item in sku_identifier.identify(
                tracking.frame_bgr,
                [d for d in detections if d.confidence >= min_confidence],
                camera_key=camera_key,
                organization_id=str(organization_id),
                branch_id=str(branch_id),
                cfg=vision_cfg,
            ):
                identified[item.detection.track_id] = item
        except Exception:  # noqa: BLE001 — never fail a frame over this
            logger.exception("SKU identification failed; using class map")
            identified = {}

    for det in detections:
        if det.confidence < min_confidence:
            continue
        if det.class_name.lower() == "person":
            persons.append(det)
            continue
        item = identified.get(det.track_id)
        if item is not None and item.match.sku:
            sku = item.match.sku
        else:
            sku = map_class_to_sku(
                str(organization_id), str(branch_id), det.class_name
            )
        if sku:
            products.append((det, sku))

    if debug.enabled:
        _collect_debug_steps(debug, tracking.frame_bgr, detections, identified, products)

    customer_id: uuid.UUID | None = None
    if recognize_face and persons:
        recognizer = get_face_recognizer()
        if recognizer.enabled:
            try:
                match = await recognizer.find_match(content)
            except Exception:  # noqa: BLE001
                match = None
            if match is not None:
                customer_id = await _lookup_customer_by_face(
                    organization_id, match.face_embedding_ref
                )

    now = time.time()
    _cleanup_stale_state(now)

    present_track_keys = {_track_key(camera_key, p.track_id) for p in persons}
    for key in present_track_keys:
        _TRACK_LAST_SEEN[key] = now

    pairs = _pair_products_with_persons(persons, products, camera_key)

    # Refresh "held" state for every pair seen this frame *before* running
    # pickup/return logic below, so a product paired for the first time this
    # frame is never mistaken for one that just disappeared.
    paired_now: dict[str, set[str]] = {}
    for track_key, _product, sku in pairs:
        paired_now.setdefault(track_key, set()).add(sku)
        _HELD.setdefault(track_key, {})[sku] = now

    emitted: list[dict[str, Any]] = []
    for track_key, product, sku in pairs:
        if not _cooldown_ok(track_key, sku):
            continue
        event = {
            "event_id": uuid.uuid4().hex,
            "event_type": "product_picked_up",
            "organization_id": str(organization_id),
            "branch_id": str(branch_id),
            "camera_id": str(camera_id) if camera_id else None,
            "track_id": track_key,
            "product_id": None,
            "product_sku": sku,
            "quantity": 1,
            "confidence": product.confidence,
            "customer_id": str(customer_id) if customer_id else None,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        result = await _post_event(event)
        emitted.append({"event": event, "backend": result})

    # Chế độ quầy thanh toán: sản phẩm đặt trước camera quầy được tự động
    # thêm vào đơn, KHÔNG cần một người trong khung. Đây là mô hình đúng
    # cho quầy — khác grab-and-go ("người X lấy sản phẩm Y") vốn cần ghép
    # người.
    #
    # Chỉ chạy khi CẢ HAI: camera được đánh dấu là checkout zone VÀ cờ
    # scan_mode bật. Thêm một nhánh riêng thay vì sửa logic ghép người ở
    # trên, để các camera kệ/cửa giữ nguyên hành vi cũ — không phá vỡ gì.
    if (
        camera_info
        and camera_info.get("is_checkout_zone")
        and getattr(vision_cfg, "checkout_scan_mode", False)
    ):
        # Một track_id cho cả khung này, xoay theo khoảng lặng giữa các khách.
        # Tính một lần dựa trên hoạt động của quầy (có sản phẩm nào không),
        # KHÔNG theo track từng sản phẩm — nếu mỗi sản phẩm một track_id thì
        # mỗi sản phẩm rơi vào một giỏ khác nhau. Còn cố định "checkout" như
        # trước thì mọi khách qua quầy dồn chung một giỏ (lỗi đang gặp).
        #
        # KHÔNG dùng _track_key ở đây: nó chèn camera_key (một UUID) vào, mà
        # backend LẠI thêm tiền tố "cam:{camera_id}:track:" khi dựng
        # session_id — camera UUID xuất hiện hai lần, session_id phình dài.
        # Chuỗi "checkout-<epoch>" đủ ngắn; backend đã bảo đảm duy nhất theo
        # camera bằng tiền tố của nó.
        checkout_track = _checkout_session_track(camera_key, now, bool(products))
        # Bộ SKU đã ghi nhận cho ĐÚNG phiên này. checkout_track đổi khi sang
        # khách mới -> key mới -> tập rỗng -> khách kế quét lại từ đầu. Dọn các
        # phiên cũ của chính camera này để dict không phình theo thời gian.
        session_key = f"{camera_key}:{checkout_track}"
        for old in [k for k in _CHECKOUT_SCANNED
                    if k.startswith(f"{camera_key}:") and k != session_key]:
            _CHECKOUT_SCANNED.pop(old, None)
        scanned = _CHECKOUT_SCANNED.setdefault(session_key, {})

        # SKU đang hiện trong khung này (giữ confidence cao nhất để gửi kèm).
        present: dict[str, float] = {}
        for product, sku in products:
            present[sku] = max(present.get(sku, 0.0), float(product.confidence))

        # 1) Thêm SKU mới; cập nhật "lần thấy cuối" cho SKU đang hiện.
        for sku, conf in present.items():
            if sku not in scanned:
                event = {
                    "event_id": uuid.uuid4().hex,
                    "event_type": "product_scanned",
                    "organization_id": str(organization_id),
                    "branch_id": str(branch_id),
                    "camera_id": str(camera_id) if camera_id else None,
                    "track_id": checkout_track,
                    "product_id": None,
                    "product_sku": sku,
                    "quantity": 1,
                    "confidence": conf,
                    "customer_id": str(customer_id) if customer_id else None,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
                result = await _post_event(event)
                emitted.append({"event": event, "backend": result})
            scanned[sku] = now

        # 2) Đối soát: SKU đã ghi nhận nhưng vắng mặt quá lâu -> GỠ khỏi giỏ.
        # Chạy cả khi quầy trống (present rỗng) nên nhấc hết sản phẩm ra thì giỏ
        # cũng được dọn theo. Dùng product_returned mà backend đã hỗ trợ sẵn.
        absent_sec = _checkout_absent_seconds()
        for sku in [s for s, last in scanned.items()
                    if s not in present and now - last > absent_sec]:
            event = {
                "event_id": uuid.uuid4().hex,
                "event_type": "product_returned",
                "organization_id": str(organization_id),
                "branch_id": str(branch_id),
                "camera_id": str(camera_id) if camera_id else None,
                "track_id": checkout_track,
                "product_id": None,
                "product_sku": sku,
                "quantity": 1,
                "confidence": 1.0,
                "customer_id": str(customer_id) if customer_id else None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            result = await _post_event(event)
            emitted.append({"event": event, "backend": result})
            scanned.pop(sku, None)

    # Product-returned detection: a sku that was picked up (has a cooldown
    # entry, i.e. we actually emitted product_picked_up for it) but hasn't
    # been paired with this same, still-visible person for more than
    # PRODUCT_RETURN_MISSING_SECONDS is treated as put back. The person
    # must still be in frame — if they simply left the camera's view we
    # don't know whether they kept the item (e.g. walked to checkout) or
    # put it down, so we stay silent and just let stale state expire (see
    # _cleanup_stale_state).
    missing_seconds = _return_missing_seconds()
    for track_key in present_track_keys:
        held = _HELD.get(track_key)
        if not held:
            continue
        currently_paired = paired_now.get(track_key, set())
        for sku in list(held.keys()):
            if sku in currently_paired:
                continue
            last_seen = held[sku]
            if now - last_seen < missing_seconds:
                continue
            pick_key = f"{track_key}:{sku}"
            if pick_key not in _COOLDOWN:
                # Was paired briefly but never actually resulted in a cart
                # addition (still within the original pickup cooldown) —
                # nothing to return.
                del held[sku]
                continue
            event = {
                "event_id": uuid.uuid4().hex,
                "event_type": "product_returned",
                "organization_id": str(organization_id),
                "branch_id": str(branch_id),
                "camera_id": str(camera_id) if camera_id else None,
                "track_id": track_key,
                "product_id": None,
                "product_sku": sku,
                "quantity": 1,
                "confidence": 1.0,
                "customer_id": str(customer_id) if customer_id else None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            result = await _post_event(event)
            emitted.append({"event": event, "backend": result})
            del held[sku]
            # Clear the cooldown too so picking the same item back up right
            # away emits a fresh product_picked_up instead of being
            # suppressed by the original cooldown window.
            _COOLDOWN.pop(pick_key, None)
        if not held:
            _HELD.pop(track_key, None)

    if camera_info and camera_info.get("is_checkout_zone") and persons:
        for person in persons:
            track_key = _track_key(camera_key, person.track_id)
            if not _cooldown_ok(track_key, "__checkout__"):
                continue
            event = {
                "event_id": uuid.uuid4().hex,
                "event_type": "checkout_initiated",
                "organization_id": str(organization_id),
                "branch_id": str(branch_id),
                "camera_id": str(camera_id) if camera_id else None,
                "track_id": track_key,
                "product_id": None,
                "product_sku": None,
                "quantity": 1,
                "confidence": person.confidence,
                "customer_id": str(customer_id) if customer_id else None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            result = await _post_event(event)
            emitted.append({"event": event, "backend": result})

    # Hand the debug set to the background queue. Returns immediately
    # whether or not it was accepted; a dropped sample is counted, not
    # raised. `debug_frame_uid` lets the admin UI jump straight to this
    # frame's artifacts, and is null when debugging is off or the sample
    # was dropped — existing clients ignore the extra key.
    debug_written = debug.flush()

    # Telemetry for the admin dashboard. Buffered and flushed in the
    # background — nothing here awaits the network. Entirely optional: when
    # ENABLE_TELEMETRY is off, `report_frame` returns immediately and the
    # response below is byte-for-byte what it was before this feature.
    if vision_cfg.enable_telemetry:
        try:
            await _report_telemetry(
                camera_key=camera_key,
                organization_id=organization_id,
                branch_id=branch_id,
                camera_id=camera_id,
                cfg=vision_cfg,
                tracking=tracking,
                detections=detections,
                identified=identified,
                products=products,
                storage_prefix=(
                    step_writer.build_prefix(camera_key, debug.frame_uid)
                    if debug_written
                    else None
                ),
            )
        except Exception:  # noqa: BLE001 — telemetry must never fail a frame
            logger.exception("telemetry reporting failed")

    return {
        "detections": [
            {
                "track_id": d.track_id,
                "class_name": d.class_name,
                "confidence": d.confidence,
                "bbox": {"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2},
            }
            for d in detections
        ],
        "persons": len(persons),
        "products": len(products),
        "is_checkout_zone": bool(camera_info and camera_info.get("is_checkout_zone")),
        "customer_id": str(customer_id) if customer_id else None,
        "emitted_events": emitted,
        # Additive/optional — present only when at least one vision/
        # ENABLE_* flag is on for this frame (see person_tracker.py). Old
        # clients that don't know this key simply ignore it; nothing above
        # this line changed shape or meaning.
        "vision": get_last_vision_result(camera_key),
        "debug_frame_uid": debug.frame_uid if debug_written else None,
    }
