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
import json
import logging
import math
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.security import require_api_key
from app.services import review_capture, sku_identifier, telemetry_client
from app.services.det_nms import _center_in_box, box_iou, cluster_winner_take_all
from app.services.face_recognizer import get_face_recognizer
from app.services.lookalike import reset_slots as reset_lookalike_slots
from app.services.lookalike import skus_are_lookalikes, stabilize_lookalikes
from app.services.model_path import (
    ensure_try_weight,
    resolve_detection_weight,
    sanitize_try_weight_key,
)
from app.services.person_tracker import (
    TrackedObject,
    get_last_vision_result,
    prune_stale_trajectories,
    track_frame_detailed,
    trajectory_last_near_ts,
)
from app.services.product_mapper import map_class_to_sku
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

# YOLO miss on the pay zone must not empty the cart. Keep the last scanned
# bottles for a few seconds of n=0 frames (same idea as lookalike sticky).
_LAST_CHECKOUT_PRODUCTS: dict[str, tuple[float, list[tuple[TrackedObject, str]]]] = {}
_HOLD_CHECKOUT_SECONDS = 8.0

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
#     "x1","y1","x2","y2": float,      # bbox YOLO khung gần nhất — crop giỏ
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


def _checkout_hand_reach_px() -> float:
    """Wrist must be within this radius of a product to count as the placer."""
    return float(get_vision_config().checkout_hand_reach_px)


def _person_box_area(person: TrackedObject) -> float:
    return max(1.0, (person.x2 - person.x1) * (person.y2 - person.y1))


def _center_in_expanded_box(
    inner: TrackedObject, outer: TrackedObject, pad: float = 0.35
) -> bool:
    """Arm/hand boxes sit just outside the torso; a padded torso still owns them."""
    width = max(1.0, outer.x2 - outer.x1)
    height = max(1.0, outer.y2 - outer.y1)
    return (
        outer.x1 - width * pad <= inner.cx <= outer.x2 + width * pad
        and outer.y1 - height * pad <= inner.cy <= outer.y2 + height * pad
    )


def _reaching_arm_duplicate(a: TrackedObject, b: TrackedObject) -> bool:
    """Torso + arm reaching the counter often sit side-by-side with IoU ~0.

    Two full-size shoppers standing close stay separate: similar box area
    plus a gap is a second person, not a ghost ReID id.
    """
    y_overlap = min(a.y2, b.y2) - max(a.y1, b.y1)
    min_h = min(a.y2 - a.y1, b.y2 - b.y1)
    if min_h <= 0.0 or y_overlap < 0.35 * min_h:
        return False
    x_gap = max(0.0, max(a.x1, b.x1) - min(a.x2, b.x2))
    max_w = max(a.x2 - a.x1, b.x2 - b.x1)
    if x_gap > 0.45 * max_w:
        return False
    smaller, larger = sorted((_person_box_area(a), _person_box_area(b)))
    return smaller / larger < 0.55


def _same_shopper_person_boxes(a: TrackedObject, b: TrackedObject) -> bool:
    return (
        box_iou(a, b) >= 0.22
        or _center_in_box(a, b)
        or _center_in_box(b, a)
        or _center_in_expanded_box(a, b)
        or _center_in_expanded_box(b, a)
        or _reaching_arm_duplicate(a, b)
    )


def _collapse_duplicate_persons(persons: list[TrackedObject]) -> list[TrackedObject]:
    """Pose/ReID often emits two boxes on one shopper (torso + arm).

    Two track ids → two carts (Khách hàng #2 vs Phiên quầy). Merge overlapping
    or reaching-arm person boxes before opening checkout sessions.
    """
    if len(persons) < 2:
        return list(persons)
    ordered = sorted(
        persons,
        key=lambda p: _person_box_area(p),
        reverse=True,
    )
    kept: list[TrackedObject] = []
    for person in ordered:
        if any(_same_shopper_person_boxes(person, other) for other in kept):
            continue
        kept.append(person)
    return kept


def _closest_visible_person(
    product_cx: float,
    product_cy: float,
    persons: list[TrackedObject],
    max_dist: float | None = None,
) -> TrackedObject | None:
    """Nearest shopper in the current frame, including legs-over-counter boxes."""
    if max_dist is None:
        max_dist = _checkout_person_assoc_max_dist_px()
    best: TrackedObject | None = None
    best_d = float("inf")
    for person in persons:
        dist = math.hypot(person.cx - product_cx, person.cy - product_cy)
        if dist > max_dist or dist >= best_d:
            continue
        best_d = dist
        best = person
    return best


def _resolve_checkout_owner(
    camera_key: str,
    product_cx: float,
    product_cy: float,
    persons: list[TrackedObject],
    now: float,
    frame_w: float,
    frame_h: float,
) -> TrackedObject | None:
    """One visible shopper at the counter owns every SKU in that frame.

    `_nearest_person_for_product` used to return a synthetic box for a ReID
    id that already left the frame (trajectory ghost). That opened
    `checkout-p2-*` while the real bottle fell through to `checkout-noperson`
    because the remaining torso box was tagged legs-only.
    """
    nearest = _nearest_person_for_product(
        camera_key, product_cx, product_cy, persons, now, frame_w, frame_h
    )
    visible = {p.track_id: p for p in persons}
    if nearest is not None and nearest.track_id not in visible:
        nearest = None
    if nearest is None and persons:
        nearest = _closest_person_by_centroid(product_cx, product_cy, persons)
    if nearest is None and len(persons) == 1:
        return persons[0]
    if nearest is None and persons:
        nearest = _closest_visible_person(product_cx, product_cy, persons)
    return nearest


def _sanitize_scan_session(raw: str | None) -> str | None:
    """Stable cart session for Phân tích Video (reuse across frames, isolate from live)."""
    if not raw:
        return None
    s = raw.strip()
    if not s or len(s) > 80:
        return None
    if not re.fullmatch(r"[A-Za-z0-9:_-]+", s):
        return None
    return s


def _roi_zones_for_frame(
    *,
    skip_roi: bool,
    override_json: str | None,
    camera_info: dict[str, Any] | None,
) -> list:
    """ROI for one /ai/frame call.

    Video analysis draws a pay zone on the uploaded file (different framing
    than the live camera). That JSON wins over ``cameras.roi_zones``. Empty
    override + skip_roi scans the whole still.
    """
    if skip_roi:
        return []
    if override_json and override_json.strip():
        try:
            raw = json.loads(override_json)
        except (ValueError, TypeError):
            logger.warning("frame roi_zones form JSON invalid — falling back to camera")
        else:
            if isinstance(raw, list) and raw:
                return zones_from_payload(raw)
    return zones_from_payload((camera_info or {}).get("roi_zones"))


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
            # CropResult exposes the padded box as a single `bbox` tuple
            # (x1, y1, x2, y2) — there are no separate .x1/.y1 attributes,
            # so referencing them raised AttributeError and lost the whole
            # DEBUG_AI step set for every frame while DEBUG_AI was on.
            debug.add(
                "crop",
                first.crop.image,
                box=list(first.crop.bbox),
            )
            debug.add(
                "classifier",
                first.crop.image,
                sku=first.match.sku,
                # MatchResult's field is `final_confidence`; `.confidence`
                # doesn't exist and would raise the same AttributeError.
                confidence=first.match.final_confidence,
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


def _hand_dist_to_product(
    person: Any, product_cx: float, product_cy: float
) -> float | None:
    left = getattr(person, "left_hand", None)
    right = getattr(person, "right_hand", None)
    if left is None and right is None:
        return None
    dl = (
        math.hypot(left[0] - product_cx, left[1] - product_cy)
        if left is not None
        else float("inf")
    )
    dr = (
        math.hypot(right[0] - product_cx, right[1] - product_cy)
        if right is not None
        else float("inf")
    )
    return min(dl, dr)


def _person_overlap_is_legs_only(person: Any, product_cy: float) -> bool:
    """True when the product sits at this person's hips/feet, not their hands.

    A bystander whose legs enter the pay zone gets a huge bbox covering the
    counter; treating them as the payer is the usual mis-ID.
    """
    y1 = getattr(person, "y1", None)
    y2 = getattr(person, "y2", None)
    if y1 is None or y2 is None:
        return False
    height = max(1.0, float(y2) - float(y1))
    rel_y = (product_cy - float(y1)) / height
    return rel_y >= 0.62


def _closest_person_by_centroid(
    product_cx: float,
    product_cy: float,
    persons: list[TrackedObject],
    max_dist: float | None = None,
) -> TrackedObject | None:
    """Nearest shopper within the admin association radius.

    ``CHECKOUT_PERSON_ASSOC_MAX_DIST_PX`` is the ceiling — a wide-angle
    camera needs a larger value, but we still must not assign a guest
    standing across the aisle.
    """
    if max_dist is None:
        max_dist = _checkout_person_assoc_max_dist_px()
    best: TrackedObject | None = None
    best_d = float("inf")
    for person in persons:
        if _person_overlap_is_legs_only(person, product_cy):
            continue
        dist = math.hypot(person.cx - product_cx, person.cy - product_cy)
        if dist > max_dist or dist >= best_d:
            continue
        best_d = dist
        best = person
    return best


def _person_by_hand_near_product(
    persons: list[Any], product_cx: float, product_cy: float
) -> Any | None:
    """Who actually placed the item — wrist closest to the product center."""
    reach = _checkout_hand_reach_px()
    best_person = None
    best_dist = float("inf")
    for person in persons:
        hand_dist = _hand_dist_to_product(person, product_cx, product_cy)
        if hand_dist is None or hand_dist >= reach or hand_dist >= best_dist:
            continue
        best_dist = hand_dist
        best_person = person
    return best_person


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
            hand_dist = _hand_dist_to_product(person, product.cx, product.cy)
            if hand_dist is not None and hand_dist < _checkout_hand_reach_px():
                if best_hand is None or hand_dist < best_hand[0]:
                    best_hand = (hand_dist, person)

            dc = math.hypot(person.cx - product.cx, person.cy - product.cy)
            if best_centroid is None or dc < best_centroid[0]:
                best_centroid = (dc, person)
                
        if best_hand is not None:
            chosen_person = best_hand[1]
        elif (
            best_centroid is not None
            and best_centroid[0] < 180.0
            and not _person_overlap_is_legs_only(best_centroid[1], product.cy)
        ):
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
    """Chủ sở hữu ở quầy: cổ tay → quỹ đạo của người ĐANG thấy → một mình.

    Quỹ đạo chỉ xét id còn trong ``persons`` (sau collapse). Id ReID ma đã
    rời khung không được bịa box giả — caller checkout sẽ mở giỏ #2.
    Khi >= 2 người, không đoán theo tâm bbox nếu không có cổ tay/quỹ đạo —
    khách đứng cạnh hay bị nhận nhầm. Fallback tâm có trần
    ``CHECKOUT_PERSON_ASSOC_MAX_DIST_PX`` nằm ở vòng gọi
    ``_closest_person_by_centroid``.
    """
    by_hand = _person_by_hand_near_product(persons, product_cx, product_cy)
    if by_hand is not None:
        return by_hand

    window = _trajectory_window_seconds()
    reach_radius = _trajectory_reach_dist_px()
    current_ids: dict[int, TrackedObject] = {p.track_id: p for p in persons}

    best_person: TrackedObject | None = None
    best_ts = -1.0
    for pid, visible in current_ids.items():
        if _person_overlap_is_legs_only(visible, product_cy):
            continue
        touched_at = trajectory_last_near_ts(
            camera_key,
            pid,
            product_cx,
            product_cy,
            frame_w=frame_w,
            frame_h=frame_h,
            now=now,
            window_seconds=window,
            radius_px=reach_radius,
        )
        if touched_at is None:
            continue
        if touched_at > best_ts:
            best_ts = touched_at
            best_person = visible

    if best_person is not None:
        return best_person

    if len(persons) == 1:
        person = persons[0]
        if _person_overlap_is_legs_only(person, product_cy):
            return None
        dc = math.hypot(person.cx - product_cx, person.cy - product_cy)
        if dc <= _checkout_person_assoc_max_dist_px():
            return person

    return None


def _maybe_flip_lookalike_sku(
    camera_key: str,
    logical_id: str,
    pp: dict[str, Any],
    sku: str,
) -> None:
    """When YOLO/color revises 7Up vs Sting on the SAME track, update the cart.

    Lookalike SKU used to change only on ByteTrack reconnect (new track_id).
    A bottle that stays tracked as Sting then becomes 7Up on the HUD never
    emitted product_returned + product_scanned, so the live label and the
    open cart disagreed for several seconds.
    """
    old_sku = pp.get("sku")
    if not sku or sku == old_sku:
        return
    if not skus_are_lookalikes(str(old_sku or ""), sku):
        return
    logger.warning(
        "CHECKOUT LOOKALIKE SKU: %s -> %s logical=%s (cap nhat gio, khong giu Sting khi da la 7Up)",
        old_sku, sku, logical_id,
    )
    if pp.get("counted") and pp.get("session_key"):
        scanned_key = f"{camera_key}:{pp['session_key']}"
        bucket = _CHECKOUT_SCANNED.get(scanned_key, {}).get(old_sku)
        if bucket and logical_id in bucket.get("logical_ids", ()):
            bucket["logical_ids"].discard(logical_id)
        pp["pending_return_sku"] = old_sku
        pp["counted"] = False
    pp["sku"] = sku


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
        if pp["sku"] != sku and not skus_are_lookalikes(pp["sku"], sku):
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
                reset_lookalike_slots(cam_key)
                _LAST_CHECKOUT_PRODUCTS.pop(cam_key, None)
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
        reset_lookalike_slots()
        _LAST_CHECKOUT_PRODUCTS.clear()
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


def _reuse_recent_checkout_products(
    camera_key: str,
    products: list[tuple[TrackedObject, str]],
    now: float,
) -> list[tuple[TrackedObject, str]]:
    """Keep last pay-zone SKUs through a few missed frames."""
    if products:
        _LAST_CHECKOUT_PRODUCTS[camera_key] = (now, products)
        return products
    held = _LAST_CHECKOUT_PRODUCTS.get(camera_key)
    if not held:
        return products
    ts, prev = held
    if not prev or now - ts > _HOLD_CHECKOUT_SECONDS:
        return products
    logger.warning(
        "FRAME PRODUCTS held: n=%d skus=%s age=%.1fs",
        len(prev),
        [s for _, s in prev],
        now - ts,
    )
    return prev


def _aggregate_manual_products(
    products: list[tuple[TrackedObject, str]],
) -> dict[str, tuple[int, float]]:
    """Aggregate physical detections by SKU while preserving their quantity."""
    aggregated: dict[str, tuple[int, float]] = {}
    for product, sku in products:
        count, confidence = aggregated.get(sku, (0, 0.0))
        aggregated[sku] = (count + 1, max(confidence, float(product.confidence)))
    return aggregated


def _remember_product_box(pp: dict[str, Any], product: TrackedObject) -> None:
    """Keep the latest YOLO box so checkout can crop a close-up for the cart."""
    pp["x1"] = float(product.x1)
    pp["y1"] = float(product.y1)
    pp["x2"] = float(product.x2)
    pp["y2"] = float(product.y2)


def _best_product_for_sku(
    products: list[tuple[TrackedObject, str]], sku: str
) -> TrackedObject | None:
    matches = [p for p, s in products if s == sku]
    if not matches:
        return None
    return max(matches, key=lambda p: float(p.confidence))


def product_crop_jpeg(
    frame_bgr: Any,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> bytes | None:
    """Close-up JPEG of one detection. None if the box is unusable."""
    import cv2

    from app.vision.crop.cropper import crop_detection, is_degenerate_box

    if frame_bgr is None or getattr(frame_bgr, "size", 0) == 0:
        return None
    h, w = frame_bgr.shape[:2]
    if is_degenerate_box(x1, y1, x2, y2, w, h):
        return None
    crop = crop_detection(frame_bgr, x1, y1, x2, y2, padding=0.12, min_size=24)
    if crop is None:
        return None
    ok, buf = cv2.imencode(".jpg", crop.image, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return None
    return buf.tobytes()


def _upload_product_crop(
    frame_bgr: Any,
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    organization_id: uuid.UUID,
    event_id: str,
) -> str | None:
    jpeg = product_crop_jpeg(frame_bgr, x1, y1, x2, y2)
    if not jpeg:
        return None
    try:
        from app.services import object_storage

        key = f"carts/product-crops/{organization_id}/{event_id}.jpg"
        object_storage.put_bytes(key, jpeg, "image/jpeg")
        return key
    except Exception:  # noqa: BLE001
        logger.exception("upload product_photo_key failed for event=%s", event_id)
        return None


def _attach_product_photo(
    event: dict[str, Any],
    frame_bgr: Any,
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> None:
    """Attach MinIO key of a close-up crop; never fail the cart event."""
    if frame_bgr is None:
        return
    key = _upload_product_crop(
        frame_bgr,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        organization_id=uuid.UUID(str(event["organization_id"])),
        event_id=str(event["event_id"]),
    )
    if key:
        event["product_photo_key"] = key


@router.post("/frame")
async def process_frame(
    organization_id: uuid.UUID = Form(...),
    branch_id: uuid.UUID = Form(...),
    camera_id: uuid.UUID | None = Form(None),
    recognize_face: bool = Form(False),
    min_confidence: float = Form(0.3),
    manual_scan: bool = Form(False),
    skip_roi: bool = Form(False),
    roi_zones_json: str | None = Form(None, alias="roi_zones"),
    weight_key: str | None = Form(None),
    scan_session: str | None = Form(None),
    image: UploadFile = File(...),
) -> dict[str, Any]:
    frame_started = time.perf_counter()
    content = await image.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty image upload")

    camera_key = str(camera_id) if camera_id else f"{organization_id}:{branch_id}"
    scan_session_key = _sanitize_scan_session(scan_session)
    if scan_session_key:
        # Don't share ByteTrack / checkout RAM with the live till camera.
        camera_key = f"{camera_key}::video::{scan_session_key}"
    det_weight_path: str | None = None

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
        # Quét thủ công từ ảnh upload: bỏ ROI (khung ảnh ≠ camera) trừ khi
        # client gửi roi_zones (Phân tích Video vẽ vùng trên file).
        # Chụp & Quét từ camera live: GIỮ ROI để contour/mì gói chạy trong vùng quầy.
        parsed_roi = _roi_zones_for_frame(
            skip_roi=skip_roi,
            override_json=roi_zones_json,
            camera_info=camera_info,
        )
        is_checkout = manual_scan or bool(
            camera_info and camera_info.get("is_checkout_zone")
        )
        if weight_key:
            safe_key = sanitize_try_weight_key(weight_key)
            if not safe_key:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "weight_key must be models/<job>.pt",
                )
            try:
                det_weight_path = ensure_try_weight(safe_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("try-weight download failed key=%s: %s", safe_key, exc)
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"Không tải được weight: {exc}",
                ) from exc
        tracking = await track_frame_detailed(
            content,
            camera_key,
            is_checkout_zone=is_checkout,
            roi_zones=parsed_roi,
            # Checkout / manual scan: dense product pass. Stock weights use
            # blob→crop; deployed bbox weights use full-frame predict.
            dense_detect=is_checkout,
            product_min_confidence=min_confidence,
            det_weight_path=det_weight_path,
        )
        detections = tracking.detections
        detections = stabilize_lookalikes(
            camera_key, detections, tracking.frame_bgr
        )
        debug.add(
            "preprocess",
            tracking.frame_bgr,
            opencv_ms=tracking.opencv_ms,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("tracking failed")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc

    # Active learning: crop a product blob in the pay zone so admin can
    # assign the catalog SKU. Do not gate on YOLO class names — furniture
    # guesses on empty wood, or a miss on a real bottle, both fail that
    # filter. Rate-limit only after a real product crop is found.
    if review_capture.is_enabled():
        review_det = review_capture.pick_product_for_review(
            tracking.frame_bgr, detections, min_confidence
        )
        if review_det is not None and review_capture.should_capture(camera_key):
            cls = str(getattr(review_det, "class_name", "") or "").strip() or None
            conf = getattr(review_det, "confidence", None)
            review_capture.capture_async(
                content=content,
                organization_id=str(organization_id),
                camera_id=str(camera_id) if camera_id else None,
                predicted_class=cls,
                confidence=float(conf) if conf is not None else None,
                frame_bgr=tracking.frame_bgr,
                detection=review_det,
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
        # Custom YOLO classes from /ai-training already map to SKUs
        # (du_7u → DU-7U). Prefer that over the SKU classifier, which
        # confuses similar packs (Gấu Đỏ vs Hảo Hảo) and generic COCO crops.
        mapped = map_class_to_sku(
            str(organization_id), str(branch_id), det.class_name
        )
        if mapped:
            sku = mapped
        elif item is not None and item.match.sku:
            sku = item.match.sku
        else:
            sku = None
        if sku:
            products.append((det, sku))
        else:
            logger.warning("DET unmapped class=%s (no SKU in class_to_sku.json)", det.class_name)

    # Tiled scan yields several boxes on the same bottle. Collapse to one
    # physical object (by SKU + position) before emitting cart events so
    # "3 món trên bàn" không thành 7 dòng giỏ / toast.
    if products and (manual_scan or is_checkout):
        tagged = [
            TrackedObject(
                track_id=det.track_id,
                class_name=sku,
                confidence=det.confidence,
                x1=det.x1,
                y1=det.y1,
                x2=det.x2,
                y2=det.y2,
            )
            for det, sku in products
        ]
        unique = cluster_winner_take_all(tagged)
        keep_ids = {d.track_id for d in unique}
        by_id = {det.track_id: (det, sku) for det, sku in products}
        products = [by_id[d.track_id] for d in unique if d.track_id in by_id]
        detections = [
            d
            for d in detections
            if d.class_name.lower() == "person"
            or d.track_id in keep_ids
            or d.track_id not in by_id
        ]
        logger.warning(
            "FRAME PRODUCTS clustered: n=%d skus=%s (dropped duplicates)",
            len(products),
            [s for _, s in products],
        )

    now = time.time()
    if is_checkout:
        products = _reuse_recent_checkout_products(camera_key, products, now)

    if is_checkout:
        from app.services.person_tracker import _cache_latest_product_boxes

        fh, fw = tracking.frame_bgr.shape[:2]
        # Overlay previously showed raw blob/YOLO hits (wood, jacket, 7Up+Sting
        # on one bottle). Publish the clustered cart SKUs instead.
        overlay_dets = [
            TrackedObject(
                track_id=det.track_id,
                class_name=sku,
                confidence=det.confidence,
                x1=det.x1,
                y1=det.y1,
                x2=det.x2,
                y2=det.y2,
            )
            for det, sku in products
            if float(det.confidence) >= 0.30
        ]
        _cache_latest_product_boxes(camera_key, overlay_dets, fw, fh)

    logger.warning(
        "FRAME PRODUCTS: n=%d skus=%s checkout_zone=%s scan_mode=%s manual=%s",
        len(products),
        [s for _, s in products],
        bool(camera_info and camera_info.get("is_checkout_zone")),
        getattr(vision_cfg, "checkout_scan_mode", False),
        manual_scan,
    )

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

    persons_for_cart = _collapse_duplicate_persons(persons) if is_checkout else list(persons)
    kept_person_ids = {p.track_id for p in persons_for_cart}
    for person in persons:
        key = _track_key(camera_key, person.track_id)
        if (not is_checkout) or person.track_id in kept_person_ids:
            _TRACK_LAST_SEEN[key] = now
        else:
            _TRACK_LAST_SEEN.pop(key, None)

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
            _attach_product_photo(
                event,
                tracking.frame_bgr,
                x1=product.x1,
                y1=product.y1,
                x2=product.x2,
                y2=product.y2,
            )
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
        manual_track = scan_session_key or f"manual-{uuid.uuid4().hex[:8]}"
        present = _aggregate_manual_products(products)
        for sku, (quantity, conf) in present.items():
            event = {
                "event_id": uuid.uuid4().hex,
                "event_type": "product_scanned",
                "organization_id": str(organization_id),
                "branch_id": str(branch_id),
                "camera_id": str(camera_id) if camera_id else None,
                "track_id": manual_track,
                "product_id": None,
                "product_sku": sku,
                "quantity": quantity,
                # Operator clicked scan / uploaded a frame — do not forward
                # a low YOLO score that CART_AI_MIN_CONFIDENCE would drop.
                "confidence": max(float(conf), 0.99),
                "customer_id": str(customer_id) if customer_id else None,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
            best = _best_product_for_sku(products, sku)
            if best is not None:
                _attach_product_photo(
                    event,
                    tracking.frame_bgr,
                    x1=best.x1,
                    y1=best.y1,
                    x2=best.x2,
                    y2=best.y2,
                )
            result = await _post_event(event)
            logger.warning(
                "CHECKOUT EVENT RESULT: sku=%s session=%s backend=%s",
                sku, manual_track, result,
            )
            emitted.append({"event": event, "backend": result})
        if not products:
            logger.warning(
                "MANUAL SCAN: detections present but no mapped SKU — nothing to add to cart"
            )
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

        if len(persons_for_cart) < len(persons):
            logger.warning(
                "CHECKOUT PERSON COLLAPSE: %d -> %d ids=%s",
                len(persons),
                len(persons_for_cart),
                [p.track_id for p in persons_for_cart],
            )

        # 0) Giữ phiên của người còn lại sau khi gộp box trùng — không mở
        # session cho ghost ReID (ID 1 + ID 2 cùng một khách).
        person_sessions: dict[int, str] = {}
        for p in persons_for_cart:
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
                _maybe_flip_lookalike_sku(camera_key, logical_id, pp, sku)
                pp["current_track_id"] = product.track_id
                pp["cx"], pp["cy"] = product.cx, product.cy
                pp["last_seen"] = now
                _remember_product_box(pp, product)
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
                _maybe_flip_lookalike_sku(camera_key, bridged_id, pp, sku)
                pp["current_track_id"] = product.track_id
                pp["cx"], pp["cy"] = product.cx, product.cy
                pp["last_seen"] = now
                _remember_product_box(pp, product)
                alias[product.track_id] = bridged_id
                claimed_this_frame.add(bridged_id)
                seen_logical_ids.add(bridged_id)
                logger.warning(
                    "CHECKOUT BRIDGE: track=%s reconnected to physical=%s (sku=%s yolo=%s) — KHÔNG tăng quantity",
                    product.track_id, bridged_id, pp["sku"], sku,
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
                "x1": float(product.x1),
                "y1": float(product.y1),
                "x2": float(product.x2),
                "y2": float(product.y2),
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
            nearest = _resolve_checkout_owner(
                camera_key,
                pp["cx"],
                pp["cy"],
                persons_for_cart,
                now,
                _traj_fw,
                _traj_fh,
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
            # Không có người trong khung — vào giỏ quầy ngay, không đợi grace.
            if pp["unassigned_since"] is None:
                pp["unassigned_since"] = now
            logger.warning(
                "CHECKOUT NO PERSON: logical=%s sku=%s — vào giỏ ngay",
                logical_id, pp["sku"],
            )
            fallback_track, _fb_prev = _checkout_session_track(camera_key, now, True)
            pp["session_key"] = f"checkout-noperson-{fallback_track.removeprefix('checkout-')}"
            pp["state"] = "FALLBACK"
            logger.warning(
                "CHECKOUT FALLBACK: logical=%s sku=%s -> %s",
                logical_id, pp["sku"], pp["session_key"],
            )

        # 3) Phát product_scanned cho sản phẩm VỪA được gán session lần đầu
        # (pp["counted"] còn False). Mỗi physical product chỉ tạo đúng MỘT
        # cart-add event trong suốt lifecycle của nó — đúng yêu cầu mục 1.
        pending_events: list[dict[str, Any]] = []
        for logical_id in seen_logical_ids:
            pp = phys[logical_id]
            old_sku = pp.pop("pending_return_sku", None)
            if old_sku and pp.get("session_key"):
                pending_events.append(
                    {
                        "event_id": uuid.uuid4().hex,
                        "event_type": "product_returned",
                        "organization_id": str(organization_id),
                        "branch_id": str(branch_id),
                        "camera_id": str(camera_id) if camera_id else None,
                        "track_id": pp["session_key"],
                        "product_id": None,
                        "product_sku": old_sku,
                        "quantity": 1,
                        "confidence": 1.0,
                        "customer_id": str(customer_id) if customer_id else None,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
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
            if all(k in pp for k in ("x1", "y1", "x2", "y2")):
                _attach_product_photo(
                    event,
                    tracking.frame_bgr,
                    x1=float(pp["x1"]),
                    y1=float(pp["y1"]),
                    x2=float(pp["x2"]),
                    y2=float(pp["y2"]),
                )
            pending_events.append(event)

        if pending_events:
            returns = [e for e in pending_events if e["event_type"] == "product_returned"]
            rest = [e for e in pending_events if e["event_type"] != "product_returned"]
            ordered = returns + rest
            for e in ordered:
                r = await _post_event(e)
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
    elif products and not emitted:
        logger.warning(
            "CHECKOUT SKIPPED: %d product(s) %s not emitted "
            "(is_checkout_zone=%s checkout_scan_mode=%s manual_scan=%s) — "
            "close-up scan needs checkout-zone camera + CHECKOUT_SCAN_MODE, "
            "or the upload Analyze path (manual_scan)",
            len(products),
            [s for _, s in products],
            bool(camera_info and camera_info.get("is_checkout_zone")),
            getattr(vision_cfg, "checkout_scan_mode", False),
            manual_scan,
        )

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

    metadata_frame = (
        tracking.raw_frame
        if tracking.raw_frame is not None
        else tracking.frame_bgr
    )
    image_height, image_width = metadata_frame.shape[:2]
    image_format = (image.content_type or "image/unknown").rsplit("/", 1)[-1].upper()

    return {
        "model": det_weight_path or resolve_detection_weight(),
        "image": {
            "width": int(image_width),
            "height": int(image_height),
            "format": image_format,
            "size_bytes": len(content),
        },
        "elapsed_ms": round((time.perf_counter() - frame_started) * 1000.0, 2),
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
