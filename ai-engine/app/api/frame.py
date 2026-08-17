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
    prune_stale_trajectories,
    track_frame_detailed,
    trajectory_last_near_ts,
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
_CAMERA_TTL_SECONDS = 300.0

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

# TTL cho _CHECKOUT_PERSON_SESSIONS — xem _cleanup_stale_state. Dài hơn nhiều
# CHECKOUT_SESSION_GAP_SECONDS (30s) để không đụng khách đang trong phiên.
_STALE_PERSON_SESSION_SECONDS = 1800.0

# --- phiên checkout theo từng camera quầy ---
# camera_key -> (thời điểm quét gần nhất, số thứ tự phiên). Mỗi khách ở quầy
# là một "phiên": khi có khoảng lặng (không quét được sản phẩm nào) đủ dài,
# khách trước coi như đã rời, lần quét kế mở phiên mới -> giỏ mới. Nếu không,
# mọi khách qua quầy dồn chung một giỏ (lỗi "nhiều người thành một đơn").
_CHECKOUT_SESSION: dict[str, tuple[float, int]] = {}

# Khử trùng lặp + đối soát cho quầy: mỗi PHYSICAL PRODUCT (không phải mỗi
# lần thấy) đếm đúng MỘT lần, và tự gỡ khỏi giỏ khi vắng mặt khỏi khung đủ
# lâu. Key = "<camera_key>:<session_key>" — session_key giờ theo TỪNG NGƯỜI
# ("checkout-p<mapped_person_id>-<epoch>", xem _checkout_person_session) hoặc
# theo camera khi không xác định được người ("checkout-noperson-<epoch>",
# xem _checkout_session_track) — thay vì luôn 1 session/camera như thiết kế
# ban đầu. Value = { sku: {"logical_ids": set[str]} }, quantity = số phần tử
# của logical_ids (mỗi phần tử là MỘT sản phẩm vật lý — xem
# _PHYSICAL_PRODUCTS/_TRACK_ALIAS bên dưới cho cách một physical product
# được xác lập/bắc cầu qua occlusion trước khi được thêm vào set này).
_CHECKOUT_SCANNED: dict[str, dict[str, dict[str, Any]]] = {}

# --- Multi-person checkout: physical-product identity xuyên occlusion ngắn ---
#
# track_id thô từ ByteTrack có thể đổi khi vật bị che tay/chồng lấn một chút.
# Nếu dùng thẳng track_id để đếm số lượng, một Coca duy nhất bị che 1 giây rồi
# lộ lại (track_id mới) sẽ bị đếm thành 2. Lớp "physical product" bên dưới là
# một tầng gián tiếp thuần RAM (không phải bảng DB): mỗi sản phẩm thật có một
# `logical_product_id` ổn định, còn track_id chỉ là chi tiết kỹ thuật tạm thời
# trỏ vào nó.
#
# camera_key -> { raw_track_id: logical_product_id }
_TRACK_ALIAS: dict[str, dict[int, str]] = {}

# camera_key -> { logical_product_id: {
#     "sku": str, "current_track_id": int, "cx": float, "cy": float,
#     "first_seen": float, "last_seen": float,
#     "owner_person_id": int | None,   # mapped_id từ ReIDManager, sticky
#     "session_key": str | None,       # checkout-p<id>-<epoch> hoặc
#                                       # checkout-noperson-<epoch>, sticky
#     "state": "CANDIDATE" | "ASSOCIATED" | "FALLBACK",
#     "unassigned_since": float | None,
#     "counted": bool,                 # đã phát product_scanned chưa
# } }
_PHYSICAL_PRODUCTS: dict[str, dict[str, dict[str, Any]]] = {}

# Phiên checkout THEO TỪNG NGƯỜI (khác _CHECKOUT_SESSION vốn gộp cả camera).
# camera_key -> { mapped_person_id: (last_seen, epoch) }. Cùng cơ chế
# gap-timeout với _CHECKOUT_SESSION, nhưng áp riêng từng người để hai khách
# đứng chung quầy không bị dồn chung một order.
_CHECKOUT_PERSON_SESSIONS: dict[str, dict[int, tuple[float, int]]] = {}


def _checkout_absent_seconds() -> float:
    """Vắng mặt bao lâu (giây) thì gỡ SKU khỏi giỏ quầy. Để 120s để sản phẩm
    đặt trên quầy không bị mất giỏ do nhiễu camera hoặc bị che tay tạm thời.
    Chỉnh bằng CHECKOUT_ABSENT_SECONDS."""
    try:
        return float(os.getenv("CHECKOUT_ABSENT_SECONDS", "120"))
    except ValueError:
        return 120.0


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
    giỏ; quá dài thì hai khách liền nhau bị gộp một giỏ. 30 giây là mặc định
    cân bằng; chỉnh bằng biến CHECKOUT_SESSION_GAP_SECONDS.
    """
    try:
        return float(os.getenv("CHECKOUT_SESSION_GAP_SECONDS", "30"))
    except ValueError:
        return 30.0


def _reacquire_window_seconds() -> float:
    """Cửa sổ (giây) để coi một track_id mới là TIẾP DIỄN của một track vừa
    biến mất, thay vì một sản phẩm mới. Ngắn hơn nhiều so với
    CHECKOUT_ABSENT_SECONDS (120s, dùng để gỡ khỏi giỏ) — mục đích khác nhau:
    cái này chỉ bắc cầu qua occlusion/che tay thoáng qua.

    Đọc từ VisionConfig (runtime override, admin UI > Cấu hình xử lý ảnh)
    thay vì thẳng os.getenv — chỉnh có hiệu lực trong ~1s, không cần sửa
    .env/restart container như trước."""
    return float(get_vision_config().product_reacquire_window_seconds)


def _reacquire_max_dist_px() -> float:
    """Khoảng cách tối đa (px, trên khung đã tiền xử lý) giữa vị trí cuối của
    track cũ và track mới để coi là cùng vật lý. Hàng đặt trên quầy gần như
    đứng yên nên ngưỡng nhỏ là đủ; ngưỡng lớn dễ bắc cầu nhầm 2 vật khác nhau
    đặt gần nhau."""
    return float(get_vision_config().product_reacquire_max_dist_px)


def _unassigned_grace_seconds() -> float:
    """Sản phẩm chưa ghép được với người nào thì đợi bao lâu (giây) trước khi
    rơi về giỏ "không xác định người" (checkout-noperson). Tránh trường hợp
    người bị mất detection 1-2 khung khiến sản phẩm của họ bị gán nhầm session
    ngay lập tức."""
    return float(get_vision_config().checkout_unassigned_grace_seconds)


def _checkout_person_assoc_max_dist_px() -> float:
    """Khoảng cách tối đa (px) giữa tâm người và tâm sản phẩm để ghép chủ sở
    hữu tại quầy. Lớn hơn ngưỡng centroid của grab-and-go (180px) vì ở quầy
    hàng thường ĐẶT xuống chứ không cầm sát tay — người có thể đứng lùi ra
    một chút so với sản phẩm trên mặt quầy."""
    return float(get_vision_config().checkout_person_assoc_max_dist_px)


def _trajectory_window_seconds() -> float:
    """Quỹ đạo của một người trong ngần này giây gần đây được xét khi tìm
    xem họ có từng đi qua gần sản phẩm không — xem
    _nearest_person_for_product."""
    return float(get_vision_config().checkout_trajectory_window_seconds)


def _trajectory_reach_dist_px() -> float:
    """Bán kính (px) để coi một điểm trong quỹ đạo là "đã tới gần" sản
    phẩm. Cố tình nhỏ hơn hẳn _checkout_person_assoc_max_dist_px (bán kính
    ghép chủ rộng hơn) — đây là ngưỡng "đã chạm tới", không phải "đứng
    trong khu vực"."""
    return float(get_vision_config().checkout_trajectory_reach_dist_px)


def _checkout_person_session(
    camera_key: str, mapped_person_id: int, now: float
) -> tuple[str, str | None]:
    """Bản sao của `_checkout_session_track`, áp riêng cho TỪNG NGƯỜI thay vì
    gộp cả camera — đây là mảnh còn thiếu để nhiều khách đứng chung quầy có
    order riêng. Cùng ngữ nghĩa gap-timeout, cùng biến CHECKOUT_SESSION_GAP_SECONDS.

    Chỉ gọi hàm này cho người ĐANG THẤY trong khung hiện tại (từ `persons`),
    nên epoch chỉ xoay khi người đó thực sự quay lại sau một khoảng vắng mặt
    dài hơn gap — không phải khi họ đơn thuần rời khỏi khung một lúc.
    """
    per_cam = _CHECKOUT_PERSON_SESSIONS.setdefault(camera_key, {})
    last, epoch = per_cam.get(mapped_person_id, (0.0, 0))
    gap = _checkout_gap_seconds()
    old_session: str | None = None
    if now - last > gap and last > 0.0:
        old_session = f"checkout-p{mapped_person_id}-{epoch}"
        epoch += 1
    elif last == 0.0:
        epoch = 1
    per_cam[mapped_person_id] = (now, epoch)
    return f"checkout-p{mapped_person_id}-{epoch}", old_session


def _checkout_session_track(
    camera_key: str, now: float, has_products: bool
) -> tuple[str, str | None]:
    """track_id gửi backend cho quầy, xoay theo khoảng lặng để tách khách.

    Returns (current_track, previous_track_or_None).
    previous_track != None khi epoch vừa tăng — tức là khách cũ vừa được phát
    hiện rời đi và khách mới bắt đầu — caller nên gửi checkout_initiated cho
    previous_track để backend đóng giỏ cũ và sẵn sàng cho giỏ mới.

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
        # Khung trống: KHÔNG chạm 'last' để khoảng lặng tích luỹ.
        return f"checkout-{epoch}", None
    gap = _checkout_gap_seconds()
    old_track: str | None = None
    if now - last > gap:
        old_epoch = epoch
        epoch += 1
        # Chỉ thông báo phiên cũ nếu đã từng có ít nhất 1 phiên (epoch > 0 trước khi tăng).
        if old_epoch > 0 or last > 0.0:
            old_track = f"checkout-{old_epoch}"
    _CHECKOUT_SESSION[camera_key] = (now, epoch)
    return f"checkout-{epoch}", old_track


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

    # --- Multi-person checkout state (xem _TRACK_ALIAS/_PHYSICAL_PRODUCTS/
    # _CHECKOUT_PERSON_SESSIONS ở đầu file) ---
    #
    # _PHYSICAL_PRODUCTS tự dọn theo CHECKOUT_ABSENT_SECONDS ngay trong nhánh
    # checkout mỗi khung (không cần chạm ở đây). Hai chỗ CÒN LẠI thì không:
    #
    # 1. _CHECKOUT_PERSON_SESSIONS: một khi một mapped_person_id từng xuất
    #    hiện, entry của họ sống mãi trong dict (chỉ epoch đổi, key thì
    #    không) — khách rời hẳn quầy không bao giờ được dọn. Trên một
    #    camera chạy nhiều ngày với hàng nghìn khách khác nhau, dict này
    #    phình vô hạn. TTL dài hơn nhiều so với CHECKOUT_SESSION_GAP_SECONDS
    #    (30s) để không đụng vào một khách đang trong phiên hợp lệ.
    for cam_key, per_cam in list(_CHECKOUT_PERSON_SESSIONS.items()):
        stale_persons = [
            pid for pid, (last_seen, _epoch) in per_cam.items()
            if now - last_seen > _STALE_PERSON_SESSION_SECONDS
        ]
        for pid in stale_persons:
            per_cam.pop(pid, None)
        if not per_cam:
            _CHECKOUT_PERSON_SESSIONS.pop(cam_key, None)

    # 2. _TRACK_ALIAS: khi một physical product bị GC (hết CHECKOUT_ABSENT_
    #    SECONDS), chỉ track_id HIỆN TẠI của nó được gỡ khỏi alias (xem bước
    #    4 trong nhánh checkout). Nếu vật đó từng được bắc cầu qua nhiều
    #    track_id trong đời (103 -> 104 -> 105), các track_id CŨ (103, 104)
    #    vẫn còn trỏ tới một logical_id đã không còn trong _PHYSICAL_PRODUCTS
    #    — vô hại về hành vi (có guard `logical_id in phys` ở nơi đọc) nhưng
    #    là rác tích luỹ vô thời hạn. Quét bỏ mọi alias trỏ tới logical_id
    #    không còn tồn tại.
    for cam_key, alias_map in list(_TRACK_ALIAS.items()):
        live_ids = _PHYSICAL_PRODUCTS.get(cam_key, {})
        dangling = [tid for tid, lid in alias_map.items() if lid not in live_ids]
        for tid in dangling:
            alias_map.pop(tid, None)
        if not alias_map:
            _TRACK_ALIAS.pop(cam_key, None)

    # Quỹ đạo người (person_tracker.py) — người rời hẳn store, không quay
    # lại trong _TRAJECTORY_STALE_SECONDS thì dọn, tránh phình vô hạn.
    prune_stale_trajectories(now)


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
            return cached[1] if cached else None
        data = resp.json()
        _CAMERA_CACHE[key] = (now, data)
        return data
    except httpx.HTTPError:
        logger.exception("fetch camera failed")
        return cached[1] if cached else None


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
        best_hand: tuple[float, TrackedObject] | None = None
        best_centroid: tuple[float, TrackedObject] | None = None
        
        for person in persons:
            # Check hand wrist proximity if available
            has_hands = (getattr(person, "left_hand", None) is not None) or (getattr(person, "right_hand", None) is not None)
            if has_hands:
                dl = math.hypot(person.left_hand[0] - product.cx, person.left_hand[1] - product.cy) if person.left_hand else float('inf')
                dr = math.hypot(person.right_hand[0] - product.cx, person.right_hand[1] - product.cy) if person.right_hand else float('inf')
                min_hand_dist = min(dl, dr)
                if min_hand_dist < 80.0:  # Proximity threshold of 80px
                    if best_hand is None or min_hand_dist < best_hand[0]:
                        best_hand = (min_hand_dist, person)
            
            # Centroid fallback
            dc = math.hypot(person.cx - product.cx, person.cy - product.cy)
            if best_centroid is None or dc < best_centroid[0]:
                best_centroid = (dc, person)
                
        if best_hand is not None:
            chosen_person = best_hand[1]
        elif best_centroid is not None and best_centroid[0] < 180.0:
            chosen_person = best_centroid[1]
        else:
            continue
            
        track_key = _track_key(camera_key, chosen_person.track_id)
        pairs.append((track_key, product, sku))
    return pairs


def _nearest_person_for_product(
    camera_key: str,
    product_cx: float,
    product_cy: float,
    persons: list[TrackedObject],
    now: float,
    frame_w: float,
    frame_h: float,
) -> TrackedObject | None:
    """Chủ sở hữu ứng viên cho một sản phẩm ở quầy — xét theo QUỸ ĐẠO, không
    phải khoảng cách hiện tại.

    Xét CẢ người đang trong khung lẫn người ĐÃ BƯỚC RA ngoài khung — điều
    này rất quan trọng ở quầy thanh toán: người đặt sản phẩm thường đã
    BƯỚC SANG MỘT BÊN hoặc rời khỏi vùng nhìn của camera ngay sau đó.
    Nếu chỉ xét người hiện diện, hầu hết sản phẩm sẽ thành "noperson".

    Khi nhiều người đều từng đi qua khu vực này trong cửa sổ thời gian,
    chọn người có lần CHẠM GẦN NHẤT (mới nhất) — hợp lý hơn "ai đang gần
    nhất bây giờ", vì người chạm sau cùng nhiều khả năng là người vừa
    thao tác với sản phẩm."""
    from app.services.person_tracker import get_recent_trajectory_person_ids

    window = _trajectory_window_seconds()
    reach_radius = _trajectory_reach_dist_px()

    # Tập hợp person_ids cần xét: người hiện tại + người có quỹ đạo gần đây.
    current_ids: dict[int, TrackedObject] = {p.track_id: p for p in persons}
    recent_ids = get_recent_trajectory_person_ids(camera_key, now, window)
    all_ids = set(current_ids) | set(recent_ids)

    best_person: TrackedObject | None = None
    best_ts = -1.0
    best_id: int | None = None
    for pid in all_ids:
        touched_at = trajectory_last_near_ts(
            camera_key, pid, product_cx, product_cy,
            frame_w=frame_w, frame_h=frame_h,
            now=now, window_seconds=window, radius_px=reach_radius,
        )
        if touched_at is None:
            continue
        if touched_at > best_ts:
            best_ts = touched_at
            best_person = current_ids.get(pid)
            best_id = pid

    if best_id is None:
        return None
    # Trả TrackedObject nếu người vẫn trong khung, hoặc tạo một stub chỉ có
    # track_id (đủ để lấy session_key / chụp ảnh crop).
    if best_person is not None:
        return best_person
    return TrackedObject(
        track_id=best_id,
        class_name="person",
        confidence=0.0,
        x1=0.0, y1=0.0, x2=0.0, y2=0.0,
    )


def _find_bridge_match(
    camera_key: str, sku: str, cx: float, cy: float, now: float, claimed_this_frame: set[str]
) -> str | None:
    """Tìm một physical product ĐÃ TỒN TẠI (cùng SKU, vừa mất track gần đây,
    ở gần vị trí này) mà track_id mới có khả năng là chính nó tái xuất hiện
    sau occlusion ngắn. Trả về logical_product_id nếu tìm thấy, None nếu
    không có ứng viên đủ tin cậy — KHÔNG cố đoán khi không chắc, theo đúng
    yêu cầu tránh heuristic phức tạp hoá quá mức.

    `claimed_this_frame` chặn hai track_id mới trong CÙNG một khung tranh
    nhau bắc cầu vào cùng một physical product.
    """
    products = _PHYSICAL_PRODUCTS.get(camera_key)
    if not products:
        return None
    window = _reacquire_window_seconds()
    max_dist = _reacquire_max_dist_px()
    best_id: str | None = None
    best_d = max_dist
    for logical_id, pp in products.items():
        if logical_id in claimed_this_frame:
            continue
        if pp["sku"] != sku:
            continue
        # pp đang "sống" trong chính khung này (vừa cập nhật bởi track_id đã
        # biết) nằm trong claimed_this_frame nên đã bị loại ở trên — ở đây
        # last_seen luôn thuộc một khung TRƯỚC đó.
        age = now - pp["last_seen"]
        if age > window:
            continue
        d = math.hypot(pp["cx"] - cx, pp["cy"] - cy)
        if d < best_d:
            best_d = d
            best_id = logical_id
    return best_id


def _cooldown_ok(track_key: str, sku: str) -> bool:
    key = f"{track_key}:{sku}"
    now = time.time()
    last = _COOLDOWN.get(key, 0.0)
    if now - last < _cooldown_seconds():
        return False
    _COOLDOWN[key] = now
    return True


@router.post("/reset-session")
async def reset_checkout_session(
    camera_id: str | None = Form(None),
) -> dict[str, Any]:
    global _CHECKOUT_SESSION, _CHECKOUT_SCANNED, _HELD, _COOLDOWN
    global _TRACK_ALIAS, _PHYSICAL_PRODUCTS, _CHECKOUT_PERSON_SESSIONS
    if camera_id:
        found = False
        for cam_key in list(_CHECKOUT_SESSION.keys()):
            if camera_id in cam_key:
                last, epoch = _CHECKOUT_SESSION[cam_key]
                _CHECKOUT_SESSION[cam_key] = (0.0, epoch + 1)
                found = True
        if not found:
            _CHECKOUT_SESSION[camera_id] = (0.0, 1)
        for k in list(_CHECKOUT_SCANNED.keys()):
            if camera_id in k:
                _CHECKOUT_SCANNED.pop(k, None)
        for cam_key in list(_TRACK_ALIAS.keys()):
            if camera_id in cam_key:
                _TRACK_ALIAS.pop(cam_key, None)
                _PHYSICAL_PRODUCTS.pop(cam_key, None)
                _CHECKOUT_PERSON_SESSIONS.pop(cam_key, None)
        try:
            from app.services.person_tracker import reset_reid
            reset_reid(camera_id)
        except Exception:
            pass
    else:
        for cam_key, (last, epoch) in list(_CHECKOUT_SESSION.items()):
            _CHECKOUT_SESSION[cam_key] = (0.0, epoch + 1)
        _CHECKOUT_SCANNED.clear()
        _HELD.clear()
        _COOLDOWN.clear()
        _TRACK_ALIAS.clear()
        _PHYSICAL_PRODUCTS.clear()
        _CHECKOUT_PERSON_SESSIONS.clear()
        try:
            from app.services.person_tracker import reset_reid
            for cam_key in list(_CHECKOUT_SESSION.keys()):
                reset_reid(cam_key)
        except Exception:
            pass
    try:
        from app.services.sku_identifier import reset_cache as reset_sku_cache
        reset_sku_cache()
    except Exception:
        pass
    logger.info("Checkout session reset requested (camera_id=%s)", camera_id)
    return {"status": "ok", "message": "Checkout session reset successfully"}


@router.post("/frame")
async def process_frame(
    organization_id: uuid.UUID = Form(...),
    branch_id: uuid.UUID = Form(...),
    camera_id: uuid.UUID | None = Form(None),
    recognize_face: bool = Form(False),
    min_confidence: float = Form(0.3),
    manual_scan: bool = Form(False),
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
        # Quét thủ công (nút Phân tích khung hình, upload ảnh): bỏ ROI để phân
        # tích TOÀN ảnh — ảnh upload thường khác khung/ROI của camera live, áp
        # ROI sẽ che mất sản phẩm. Live path giữ nguyên ROI.
        roi_zones = [] if manual_scan else zones_from_payload(
            (camera_info or {}).get("roi_zones")
        )
        is_checkout = manual_scan or bool(
            camera_info and camera_info.get("is_checkout_zone")
        )
        tracking = await track_frame_detailed(
            content,
            camera_key,
            is_checkout_zone=is_checkout,
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
                tracking.raw_frame if tracking.raw_frame is not None else tracking.frame_bgr,
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
        logger.warning("DET: class=%s, conf=%.3f, track_id=%s", det.class_name, det.confidence, det.track_id)
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
    if not is_checkout:
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
    if manual_scan:
        # Nhập đơn thủ công từ ảnh upload: mỗi lần là một phiên RIÊNG (đơn mới),
        # emit MỌI sản phẩm nhận được, KHÔNG dedup/đối soát theo phiên live. Nhờ
        # phiên riêng nên không đụng vào giỏ đang chạy của luồng camera.
        manual_track = f"manual-{uuid.uuid4().hex[:8]}"
        present: dict[str, float] = {}
        for product, sku in products:
            present[sku] = max(present.get(sku, 0.0), float(product.confidence))
        for sku, conf in present.items():
            event = {
                "event_id": uuid.uuid4().hex,
                "event_type": "product_scanned",
                "organization_id": str(organization_id),
                "branch_id": str(branch_id),
                "camera_id": str(camera_id) if camera_id else None,
                "track_id": manual_track,
                "product_id": None,
                "product_sku": sku,
                "quantity": 1,
                "confidence": conf,
                "customer_id": str(customer_id) if customer_id else None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            result = await _post_event(event)
            emitted.append({"event": event, "backend": result})
    elif (
        camera_info
        and camera_info.get("is_checkout_zone")
        and getattr(vision_cfg, "checkout_scan_mode", False)
    ):
        # === Multi-person checkout ===
        # track_id (thô) --alias/bridge--> logical_product_id --sticky--> owner
        # person --sticky--> session_key --gửi backend làm-> track_id sự kiện.
        # Chi tiết từng bước xem docstring của _TRACK_ALIAS/_PHYSICAL_PRODUCTS
        # ở đầu file. Camera kệ hàng (grab-and-go, nhánh `if not is_checkout`
        # phía trên) không đụng tới nhánh này.
        alias = _TRACK_ALIAS.setdefault(camera_key, {})
        phys = _PHYSICAL_PRODUCTS.setdefault(camera_key, {})

        # 0) Giữ phiên của MỌI người đang thấy trong khung — kể cả người chưa
        # ghép được với sản phẩm nào ở khung này — để epoch của họ không xoay
        # chỉ vì khung này họ chưa cầm/đặt gì.
        person_sessions: dict[int, str] = {}
        for p in persons:
            session_key, prev_session = _checkout_person_session(camera_key, p.track_id, now)
            person_sessions[p.track_id] = session_key
            if prev_session:
                logger.warning(
                    "CHECKOUT PERSON SESSION CHANGE: person=%s prev=%s -> new=%s",
                    p.track_id, prev_session, session_key,
                )
                close_event = {
                    "event_id": uuid.uuid4().hex,
                    "event_type": "checkout_initiated",
                    "organization_id": str(organization_id),
                    "branch_id": str(branch_id),
                    "camera_id": str(camera_id) if camera_id else None,
                    "track_id": prev_session,
                    "product_id": None,
                    "product_sku": None,
                    "quantity": 1,
                    "confidence": 1.0,
                    "customer_id": str(customer_id) if customer_id else None,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
                close_result = await _post_event(close_event)
                emitted.append({"event": close_event, "backend": close_result})

        # 1) Aliasing physical product cho mọi sản phẩm thấy trong khung này.
        # Pass 1 (track_id đã biết) chạy trước và "claim" ngay, để pass 2
        # (bắc cầu occlusion) không nhận nhầm một pp vừa sống trong chính
        # khung này làm ứng viên track-mất.
        claimed_this_frame: set[str] = set()
        seen_logical_ids: set[str] = set()
        unresolved: list[tuple[Any, str]] = []
        for product, sku in products:
            logical_id = alias.get(product.track_id)
            if logical_id is not None and logical_id in phys:
                pp = phys[logical_id]
                pp["current_track_id"] = product.track_id
                pp["cx"], pp["cy"] = product.cx, product.cy
                pp["last_seen"] = now
                claimed_this_frame.add(logical_id)
                seen_logical_ids.add(logical_id)
            else:
                unresolved.append((product, sku))

        for product, sku in unresolved:
            # QUYẾT ĐỊNH "sản phẩm vật lý mới hay không" LUÔN đi qua bridge
            # trước — không có nhánh nào tăng quantity trước khi biết chắc
            # đây không phải một track vừa bị mất rồi tái xuất hiện.
            bridged_id = _find_bridge_match(
                camera_key, sku, product.cx, product.cy, now, claimed_this_frame
            )
            if bridged_id is not None:
                pp = phys[bridged_id]
                pp["current_track_id"] = product.track_id
                pp["cx"], pp["cy"] = product.cx, product.cy
                pp["last_seen"] = now
                alias[product.track_id] = bridged_id
                claimed_this_frame.add(bridged_id)
                seen_logical_ids.add(bridged_id)
                logger.warning(
                    "CHECKOUT BRIDGE: track=%s reconnected to physical=%s (sku=%s) — KHÔNG tăng quantity",
                    product.track_id, bridged_id, sku,
                )
                continue
            # Bridge không match được ứng viên đáng tin -> sản phẩm vật lý mới.
            logical_id = f"{sku}:{product.track_id}:{int(now * 1000)}"
            alias[product.track_id] = logical_id
            phys[logical_id] = {
                "sku": sku,
                "current_track_id": product.track_id,
                "cx": product.cx,
                "cy": product.cy,
                "first_seen": now,
                "last_seen": now,
                "owner_person_id": None,
                "session_key": None,
                "state": "CANDIDATE",
                "unassigned_since": now,
                "counted": False,
            }
            claimed_this_frame.add(logical_id)
            seen_logical_ids.add(logical_id)
            logger.warning(
                "CHECKOUT NEW PHYSICAL PRODUCT: logical=%s sku=%s track=%s",
                logical_id, sku, product.track_id,
            )

        # 2) Ghép chủ sở hữu — CHỈ cho sản phẩm CHƯA có session_key. Một khi
        # đã gán (sticky), các khung sau KHÔNG tính lại dù người khác đứng
        # gần hơn — trừ khi physical product này thực sự kết thúc lifecycle
        # (bị GC ở bước 4) và một logical_id mới được tạo.
        grace = _unassigned_grace_seconds()
        # Khung THẬT SỰ mà YOLO/pose thấy (raw_frame nếu có, khớp đúng cái
        # person_tracker.py dùng khi ghi quỹ đạo) — cx/cy của person lẫn pp
        # đều tính trên khung này, nên quy đổi quỹ đạo ngược lại cũng phải
        # dùng đúng kích thước này, không phải kích thước bất kỳ khung nào
        # khác (vd frame đã tiền xử lý/resize).
        _traj_frame = tracking.raw_frame if tracking.raw_frame is not None else tracking.frame_bgr
        _traj_fh, _traj_fw = _traj_frame.shape[:2]
        for logical_id in seen_logical_ids:
            pp = phys[logical_id]
            if pp["session_key"] is not None:
                continue
            nearest = _nearest_person_for_product(
                camera_key, pp["cx"], pp["cy"], persons, now, _traj_fw, _traj_fh
            )
            if nearest is not None:
                session_key = person_sessions.get(nearest.track_id)
                if session_key is None:
                    session_key, _ = _checkout_person_session(camera_key, nearest.track_id, now)
                    person_sessions[nearest.track_id] = session_key
                pp["owner_person_id"] = nearest.track_id
                pp["session_key"] = session_key
                pp["state"] = "ASSOCIATED"
                pp["unassigned_since"] = None
                logger.warning(
                    "CHECKOUT OWNER: logical=%s sku=%s -> person=%s session=%s",
                    logical_id, pp["sku"], nearest.track_id, session_key,
                )
                continue
            # Chưa thấy người nào đủ gần — CANDIDATE, thử ghép lại ở khung
            # sau thay vì rơi ngay về "không xác định người".
            if pp["unassigned_since"] is None:
                pp["unassigned_since"] = now
            if now - pp["unassigned_since"] < grace:
                continue
            fallback_track, _fb_prev = _checkout_session_track(camera_key, now, True)
            # fallback_track đã có dạng "checkout-<epoch>" (xem
            # _checkout_session_track) — KHÔNG nối thêm tiền tố "checkout-"
            # lần nữa, kẻo ra "checkout-noperson-checkout-3".
            pp["session_key"] = f"checkout-noperson-{fallback_track.removeprefix('checkout-')}"
            pp["state"] = "FALLBACK"
            logger.warning(
                "CHECKOUT FALLBACK: logical=%s sku=%s -> %s (không tìm được người sau %.0fs grace)",
                logical_id, pp["sku"], pp["session_key"], grace,
            )

        # 3) Phát product_scanned cho sản phẩm VỪA được gán session lần đầu
        # (pp["counted"] còn False). Mỗi physical product chỉ tạo đúng MỘT
        # cart-add event trong suốt lifecycle của nó — đúng yêu cầu mục 1.
        pending_events: list[dict[str, Any]] = []
        for logical_id in seen_logical_ids:
            pp = phys[logical_id]
            if pp["session_key"] is None or pp["counted"]:
                continue
            scanned_key = f"{camera_key}:{pp['session_key']}"
            scanned = _CHECKOUT_SCANNED.setdefault(scanned_key, {})
            bucket = scanned.setdefault(pp["sku"], {"logical_ids": set()})
            bucket["logical_ids"].add(logical_id)
            pp["counted"] = True

            # Ảnh khách (chủ giỏ hàng): chỉ upload khi biết được chủ sở hữu
            # (ASSOCIATED, không phải FALLBACK/noperson — không có ai để
            # chụp). Key theo session_key nên các lần upload sau của CÙNG
            # phiên ghi đè đúng 1 object thay vì tích rác trên MinIO. Không
            # bao giờ để lỗi upload làm hỏng cả khung — đúng triết lý các
            # tác vụ phụ khác trong file này (vd review_capture).
            customer_photo_key = None
            owner_id = pp.get("owner_person_id")
            if pp["state"] == "ASSOCIATED" and owner_id is not None:
                try:
                    from app.services.person_tracker import get_person_crop_bytes
                    crop = get_person_crop_bytes(camera_key, owner_id)
                    if crop:
                        from app.services import object_storage
                        key = f"carts/customer-photos/{organization_id}/{pp['session_key']}.jpg"
                        object_storage.put_bytes(key, crop, "image/jpeg")
                        customer_photo_key = key
                except Exception:  # noqa: BLE001
                    logger.exception("upload customer_photo_key failed for session=%s", pp["session_key"])

            event = {
                "event_id": uuid.uuid4().hex,
                "event_type": "product_scanned",
                "organization_id": str(organization_id),
                "branch_id": str(branch_id),
                "camera_id": str(camera_id) if camera_id else None,
                "track_id": pp["session_key"],
                "product_id": None,
                "product_sku": pp["sku"],
                "quantity": 1,
                "confidence": 1.0,
                "customer_id": str(customer_id) if customer_id else None,
                "customer_photo_key": customer_photo_key,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            pending_events.append(event)

        if pending_events:
            event_results = await asyncio.gather(*[_post_event(e) for e in pending_events])
            for e, r in zip(pending_events, event_results):
                logger.warning(
                    "CHECKOUT EVENT RESULT: sku=%s session=%s backend=%s",
                    e["product_sku"], e["track_id"], r,
                )
                emitted.append({"event": e, "backend": r})

        # 4) Đối soát + GC: physical product vắng mặt quá lâu (đã ra khỏi cả
        # cửa sổ bắc cầu từ lâu) -> coi là rời quầy thật sự. Gỡ khỏi giỏ nếu
        # đã tính, rồi xoá khỏi state để không phình bộ nhớ theo thời gian.
        absent_sec = _checkout_absent_seconds()
        expired = [lid for lid, pp in phys.items() if now - pp["last_seen"] > absent_sec]
        for logical_id in expired:
            pp = phys.pop(logical_id)
            alias.pop(pp["current_track_id"], None)
            if pp["counted"] and pp["session_key"]:
                scanned_key = f"{camera_key}:{pp['session_key']}"
                bucket = _CHECKOUT_SCANNED.get(scanned_key, {}).get(pp["sku"])
                if bucket and logical_id in bucket["logical_ids"]:
                    bucket["logical_ids"].discard(logical_id)
                    event = {
                        "event_id": uuid.uuid4().hex,
                        "event_type": "product_returned",
                        "organization_id": str(organization_id),
                        "branch_id": str(branch_id),
                        "camera_id": str(camera_id) if camera_id else None,
                        "track_id": pp["session_key"],
                        "product_id": None,
                        "product_sku": pp["sku"],
                        "quantity": 1,
                        "confidence": 1.0,
                        "customer_id": str(customer_id) if customer_id else None,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                    }
                    result = await _post_event(event)
                    emitted.append({"event": event, "backend": result})
                    if not bucket["logical_ids"]:
                        _CHECKOUT_SCANNED[scanned_key].pop(pp["sku"], None)

    # Product-returned detection: a sku that was picked up (has a cooldown
    # entry, i.e. we actually emitted product_picked_up for it) but hasn't
    # been paired with this same, still-visible person for more than
    # PRODUCT_RETURN_MISSING_SECONDS is treated as put back. The person
    # must still be in frame — if they simply left the camera's view we
    # don't know whether they kept the item (e.g. walked to checkout) or
    # put it down, so we stay silent and just let stale state expire (see
    # _cleanup_stale_state).
    if not is_checkout:
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

    # In checkout zone mode, DO NOT fire checkout_initiated automatically on every frame
    # for random person tracks, which freezes active carts into PENDING_CHECKOUT prematurely
    # and forces backend to spawn continuous duplicate carts. Checkout is initiated when
    # staff or customer clicks Checkout/QR.
    # if camera_info and camera_info.get("is_checkout_zone") and persons:
    #     ...

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
                "class_name": (
                    identified[d.track_id].match.sku
                    if (d.track_id in identified and identified[d.track_id].match and identified[d.track_id].match.sku)
                    else d.class_name
                ),
                "sku": (
                    identified[d.track_id].match.sku
                    if (d.track_id in identified and identified[d.track_id].match and identified[d.track_id].match.sku)
                    else map_class_to_sku(str(organization_id), str(branch_id), d.class_name)
                ),
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
