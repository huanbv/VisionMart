"""Orchestrates the second model stage: crop -> classify -> match.

Sits between `person_tracker` (which produces boxes) and the cart logic
(which needs SKUs). Keeping it in its own module means `frame.py` gains a
few lines rather than a second pipeline inlined into an already long
endpoint.

The per-track cache is the reason this is affordable on CPU
-----------------------------------------------------------
A tracked object persists for dozens of frames. Classifying it on every
one of them would multiply the classifier cost by the frame rate for no
new information — the object's identity does not change while ByteTrack
holds the same id. So a track is classified once, and re-classified only
when:

* the cached answer was *not* confident (worth another look from a new
  angle — the shopper may have rotated the label toward the camera), or
* the cache entry has aged out (guards against a recycled track id
  silently inheriting the previous object's SKU).

With the cache, added cost is roughly one classifier call per new track
instead of one per detection per frame.

Disabled by default: with `ENABLE_SKU_CLASSIFIER` off this module is never
called, and `frame.py` keeps using the class-map path exactly as before.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.services.product_mapper import list_known_brands
from app.vision.classify import get_classifier
from app.vision.crop import CropResult, crop_detections
from app.vision.embedding.extractor import extract_from_classifier
from app.vision.matching import MatchResult, match_product
from app.vision.ocr.reader import get_reader, should_run_ocr
from app.vision.voting.vote import TrackVoteBox, tally_votes

logger = logging.getLogger("ai-engine.sku_identifier")

# Hòm phiếu cho mỗi track. Thay cho cache "chốt một khung" trước đây: một
# track được phân loại lại qua nhiều khung và bỏ phiếu, thay vì khoá cứng
# kết quả của khung đầu (vốn có thể là khung mờ đoán sai). Xem
# app/vision/voting/vote.py.
# track_key -> (TrackVoteBox, monotonic_ts của phiếu gần nhất)
_TRACK_VOTES: dict[str, tuple[TrackVoteBox, float]] = {}
# Track đã chốt: (MatchResult, ts). Sau khi bỏ phiếu đủ đồng thuận thì
# không phân loại lại nữa — đây là chỗ giữ lại lợi ích hiệu năng của cache
# cũ, chỉ khác là chỉ khoá SAU khi nhiều khung đã đồng ý.
_TRACK_SETTLED: dict[str, tuple[MatchResult, float]] = {}
_CACHE_TTL_SECONDS = 30.0
# Bounded so a long-running process with churning track ids can't grow it
# without limit.
_CACHE_MAX_ENTRIES = 2000


class _VotedClassification:
    """Kết quả phân loại đã qua bỏ phiếu, hình dạng giống ClassificationResult.

    Matcher đọc classification bằng ``getattr`` (duck typing), nên một đối
    tượng mang đủ ``sku``/``confidence``/``margin`` thay thế được kết quả
    một-khung mà không phải sửa matcher. Đây là cách đưa quyết định-nhiều-
    khung vào chuỗi confidence sẵn có mà không phá vỡ gì.
    """

    __slots__ = ("sku", "confidence", "margin", "runner_up_sku",
                 "runner_up_confidence", "label_index", "model_version", "embedding")

    def __init__(self, vote, base) -> None:
        self.sku = vote.sku
        # Giữ nguyên độ tin cậy gốc từ mô hình phân loại để không đẩy nhầm ảnh nhiễu/điện thoại thành 100%
        self.confidence = getattr(base, "confidence", vote.agreement)
        self.runner_up_sku = vote.runner_up_sku
        # margin theo tỉ lệ đồng thuận: dẫn đầu trừ á quân trong hòm phiếu.
        second = 0.0
        if vote.runner_up_sku and vote.tally:
            total = sum(vote.tally.values()) or 1.0
            second = vote.tally.get(vote.runner_up_sku, 0.0) / total
        self.margin = round(max(0.0, vote.agreement - second), 4)
        self.runner_up_confidence = round(second, 4)
        # Giữ các trường phụ từ lần phân loại gần nhất để dashboard/embedding
        # vẫn dùng được.
        self.label_index = getattr(base, "label_index", None)
        self.model_version = getattr(base, "model_version", None)
        self.embedding = getattr(base, "embedding", None)


@dataclass(frozen=True)
class IdentifiedObject:
    """One detection with its resolved SKU and per-stage confidences.

    The per-stage results (``classification``, ``ocr``, ``embedding``) are
    carried alongside the final ``match`` rather than folded into it,
    because the dashboard's whole purpose is showing *how* the answer was
    reached — a single resolved SKU cannot explain itself. They are all
    ``None`` when the corresponding stage is disabled, which is the default.
    """

    detection: Any                 # TrackedObject
    match: MatchResult
    crop: CropResult | None
    from_cache: bool
    classification: Any = None
    ocr: Any = None
    embedding: Any = None


def _track_key(camera_key: str, track_id: Any) -> str:
    return f"{camera_key}:{track_id}"


def _prune_cache(now: float) -> None:
    for store in (_TRACK_VOTES, _TRACK_SETTLED):
        if len(store) <= _CACHE_MAX_ENTRIES:
            continue
        stale = [k for k, (_, ts) in store.items() if now - ts > _CACHE_TTL_SECONDS]
        for key in stale:
            store.pop(key, None)
        if len(store) > _CACHE_MAX_ENTRIES:
            for key, _ in sorted(store.items(), key=lambda kv: kv[1][1])[:500]:
                store.pop(key, None)


def reset_cache() -> None:
    """Clear cached identities — call after deploying a new classifier."""
    _TRACK_VOTES.clear()
    _TRACK_SETTLED.clear()


def identify(
    frame_bgr: np.ndarray,
    detections: list[Any],
    *,
    camera_key: str,
    organization_id: str,
    branch_id: str,
    cfg: Any,
) -> list[IdentifiedObject]:
    """Resolve SKUs for every product-like detection in this frame."""
    now = time.monotonic()
    _prune_cache(now)

    classifier = get_classifier()
    min_conf = getattr(cfg, "classifier_min_confidence", 0.55)

    # 1) Track đã CHỐT phiếu (nhiều khung đã đồng thuận) thì tái sử dụng —
    # đây là chỗ giữ lợi ích hiệu năng của cache cũ. Track chưa chốt vẫn
    # được đưa xuống phân loại để thêm một phiếu nữa, thay vì khoá cứng
    # kết quả khung đầu như trước.
    pending: list[Any] = []
    results: list[IdentifiedObject] = []
    for det in detections:
        if str(getattr(det, "class_name", "")).lower() == "person":
            continue
        key = _track_key(camera_key, getattr(det, "track_id", None))
        settled = _TRACK_SETTLED.get(key)
        if settled is not None:
            match, ts = settled
            if now - ts <= _CACHE_TTL_SECONDS:
                results.append(
                    IdentifiedObject(detection=det, match=match, crop=None, from_cache=True)
                )
                continue
            # Hết hạn: bỏ chốt cũ, bỏ phiếu lại từ đầu cho góc nhìn mới.
            _TRACK_SETTLED.pop(key, None)
            _TRACK_VOTES.pop(key, None)
        pending.append(det)

    if not pending:
        return results

    # 2) Crop everything still pending, then classify in one batch.
    crops = crop_detections(
        frame_bgr,
        pending,
        padding=getattr(cfg, "crop_padding", 0.08),
        min_size=getattr(cfg, "crop_min_size", 24),
    )
    crop_by_track = {c.track_id: c for c in crops}

    classifications: dict[Any, Any] = {}
    if classifier is not None and crops:
        try:
            batch = classifier.classify_batch([c.image for c in crops])
            for crop, result in zip(crops, batch):
                if result is not None:
                    classifications[crop.track_id] = result
        except Exception:
            # Classification is an enhancement; never let it fail the frame.
            logger.exception("SKU classification batch failed")

    # 3) Decide a SKU per detection and cache the outcome.
    # 2b) OCR only where the classifier could not settle. Budgeted per
    # frame: OCR is the one stage that can blow the frame time outright,
    # so a crowded shelf where 20 objects are all uncertain must not turn
    # into a two-second frame. The budget is spent on the *least* confident
    # detections first, because that is where reading the label pays most.
    ocr_results: dict[Any, Any] = {}
    if getattr(cfg, "enable_ocr_fallback", False) and crops:
        candidates = [
            c for c in crops
            if should_run_ocr(classifications.get(c.track_id), cfg)
        ]
        candidates.sort(
            key=lambda c: getattr(classifications.get(c.track_id), "confidence", 0.0)
        )
        budget = int(getattr(cfg, "ocr_max_per_frame", 3))
        if candidates[budget:]:
            logger.debug(
                "OCR budget %d reached; %d uncertain crops skipped this frame",
                budget, len(candidates) - budget,
            )
        reader = get_reader(cfg)
        brands = list_known_brands(organization_id)
        for crop in candidates[:budget]:
            try:
                out = reader.read(crop.image, brands)
            except Exception:
                logger.exception("OCR failed for track %s", crop.track_id)
                continue
            if out is not None and out.has_signal:
                ocr_results[crop.track_id] = out

    # 3) Bỏ phiếu qua nhiều khung, rồi quyết định SKU.
    use_voting = getattr(cfg, "enable_multiframe_voting", True)
    min_votes = int(getattr(cfg, "voting_min_votes", 3))
    agreement = float(getattr(cfg, "voting_agreement_ratio", 0.6))

    for det in pending:
        track_id = getattr(det, "track_id", None)
        classification = classifications.get(track_id)
        ocr = ocr_results.get(track_id)
        key = _track_key(camera_key, track_id)

        # Kết quả dùng cho matcher: mặc định là phân loại một-khung, nhưng
        # được thay bằng kết quả bỏ phiếu khi đã tích đủ khung. Nhờ đó một
        # khung mờ đoán lệch không tự mình quyết định cả track.
        effective = classification
        vote_settled = False
        if use_voting and track_id is not None and classification is not None:
            box, _ = _TRACK_VOTES.get(key, (TrackVoteBox(), now))
            box.add(classification.sku, classification.confidence, now)
            _TRACK_VOTES[key] = (box, now)
            vote = tally_votes(box, min_votes=min_votes, agreement_ratio=agreement)
            # Chỉ để phiếu ghi đè khi nó đã hội tụ; trước đó vẫn dùng kết
            # quả khung hiện tại để không làm chậm phản hồi ban đầu.
            if vote.sku:
                effective = _VotedClassification(vote, classification)
            vote_settled = vote.settled

        match = match_product(
            organization_id=organization_id,
            branch_id=branch_id,
            class_name=str(getattr(det, "class_name", "")),
            yolo_confidence=float(getattr(det, "confidence", 0.0) or 0.0),
            classification=effective,
            classifier_min_confidence=min_conf,
            classifier_min_margin=float(getattr(cfg, "classifier_min_margin", 0.0)),
            ocr=ocr,
        )

        logger.warning("IDENTIFY: track_id=%s, class_name=%s, pred_sku=%s, pred_conf=%s, match_sku=%s, reason=%s",
                       track_id, getattr(det, "class_name", ""),
                       getattr(effective, "sku", None) if effective else None,
                       getattr(effective, "confidence", None) if effective else None,
                       match.sku, match.reason)

        # Chỉ CHỐT (ngừng phân loại lại) khi phiếu đã đồng thuận và kết quả
        # đủ mạnh. Track còn lưỡng lự sẽ tiếp tục được bỏ phiếu ở khung sau
        # — đúng chỗ ta chấp nhận trả thêm chi phí để đổi lấy độ chính xác.
        if track_id is not None and vote_settled and match.final_confidence >= min_conf:
            _TRACK_SETTLED[key] = (match, now)

        results.append(
            IdentifiedObject(
                detection=det,
                match=match,
                crop=crop_by_track.get(track_id),
                from_cache=False,
                classification=classification,
                ocr=ocr,
                embedding=(
                    extract_from_classifier(classification)
                    if getattr(cfg, "enable_embeddings", False)
                    else None
                ),
            )
        )
    return results
