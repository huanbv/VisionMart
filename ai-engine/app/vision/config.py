"""Configuration for the vision/ package — environment defaults with a
runtime override layer that the admin UI can edit.

Two sources, in precedence order:

1. **Runtime overrides** — a JSON file at ``VISION_RUNTIME_CONFIG_PATH``
   (default ``/app/config/vision_runtime.json``, which docker-compose
   already mounts as a volume so it survives restarts). Written by
   ``PUT /ai/vision-config``; this is what the admin screen edits.
2. **Environment variables** — the deployment defaults, unchanged.

Anything absent from both falls back to the hard-coded default, which
makes `pipeline.py` behave exactly like the pre-Sprint code path (plain
decode, no ROI, no enhancement).

Why a file rather than an in-memory value: the config has to survive a
container restart *and* stay correct if the service is ever run with more
than one uvicorn worker. A process-local variable would silently diverge
per worker — an operator would flip a toggle and see it apply to only some
frames. Every worker watching the same file's mtime avoids that without
adding Redis (which this service doesn't currently depend on).

The mtime check is throttled to at most once per ``_MTIME_CHECK_SECONDS``
so the hot path doesn't ``stat()`` on every single frame.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, fields

logger = logging.getLogger("ai-engine.vision.config")

DEFAULT_RUNTIME_CONFIG_PATH = "/app/config/vision_runtime.json"
_MTIME_CHECK_SECONDS = 1.0

# Overrides loaded from the runtime file, keyed by the same names as the
# environment variables (e.g. "ENABLE_CLAHE"). Values are stored as strings
# so the same parsing helpers handle both sources.
_OVERRIDES: dict[str, str] = {}


def runtime_config_path() -> str:
    return os.getenv("VISION_RUNTIME_CONFIG_PATH", DEFAULT_RUNTIME_CONFIG_PATH)


def _read_override_file() -> dict[str, str]:
    path = runtime_config_path()
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        # A corrupt or unreadable override file must not take the service
        # down — fall back to environment defaults and say so.
        logger.exception("Could not read vision runtime config at %s", path)
        return {}
    if not isinstance(raw, dict):
        logger.warning("Vision runtime config at %s is not an object; ignoring", path)
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _get_raw(name: str) -> str | None:
    """Runtime override first, then environment."""
    if name in _OVERRIDES:
        return _OVERRIDES[name]
    return os.getenv(name)


def _bool(name: str, default: bool) -> bool:
    raw = _get_raw(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    raw = _get_raw(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    return int(_float(name, float(default)))


def _str(name: str, default: str) -> str:
    raw = _get_raw(name)
    return default if raw is None else raw


@dataclass(frozen=True)
class VisionConfig:
    # ---- Module 2: ROI ----
    enable_roi: bool = field(default_factory=lambda: _bool("ENABLE_ROI", False))
    roi_config_path: str = field(default_factory=lambda: _str("ROI_CONFIG_PATH", ""))

    # ---- Module 3: Enhancement (each independently toggleable, all off by default) ----
    enable_clahe: bool = field(default_factory=lambda: _bool("ENABLE_CLAHE", False))
    clahe_clip_limit: float = field(default_factory=lambda: _float("CLAHE_CLIP_LIMIT", 2.0))
    clahe_tile_grid_size: int = field(default_factory=lambda: _int("CLAHE_TILE_GRID_SIZE", 8))

    enable_hist_eq: bool = field(default_factory=lambda: _bool("ENABLE_HIST_EQ", False))

    enable_brightness: bool = field(
        default_factory=lambda: _bool("ENABLE_BRIGHTNESS_ADJUST", False)
    )
    # Additive delta in [-255, 255] applied to every pixel.
    brightness_delta: float = field(default_factory=lambda: _float("BRIGHTNESS_DELTA", 0.0))

    enable_contrast: bool = field(
        default_factory=lambda: _bool("ENABLE_CONTRAST_ADJUST", False)
    )
    # Multiplicative gain; 1.0 = no change.
    contrast_alpha: float = field(default_factory=lambda: _float("CONTRAST_ALPHA", 1.0))

    enable_gamma: bool = field(default_factory=lambda: _bool("ENABLE_GAMMA", False))
    gamma_value: float = field(default_factory=lambda: _float("GAMMA_VALUE", 1.0))

    enable_gaussian_blur: bool = field(
        default_factory=lambda: _bool("ENABLE_GAUSSIAN_BLUR", False)
    )
    gaussian_kernel_size: int = field(
        default_factory=lambda: _int("GAUSSIAN_KERNEL_SIZE", 5)
    )

    enable_median_blur: bool = field(
        default_factory=lambda: _bool("ENABLE_MEDIAN_BLUR", False)
    )
    median_kernel_size: int = field(default_factory=lambda: _int("MEDIAN_KERNEL_SIZE", 5))

    # ---- Module 3b: Sprint 2 enhancement additions (all off by default) ----
    # Edge-preserving denoise. Keeps object edges sharp, unlike Gaussian/median.
    enable_bilateral: bool = field(default_factory=lambda: _bool("ENABLE_BILATERAL", False))
    bilateral_diameter: int = field(default_factory=lambda: _int("BILATERAL_DIAMETER", 9))
    bilateral_sigma_color: float = field(
        default_factory=lambda: _float("BILATERAL_SIGMA_COLOR", 75.0)
    )
    bilateral_sigma_space: float = field(
        default_factory=lambda: _float("BILATERAL_SIGMA_SPACE", 75.0)
    )

    # Unsharp masking / highboost. amount=1.0 is textbook unsharp masking.
    enable_unsharp_mask: bool = field(
        default_factory=lambda: _bool("ENABLE_UNSHARP_MASK", False)
    )
    unsharp_amount: float = field(default_factory=lambda: _float("UNSHARP_AMOUNT", 0.6))
    unsharp_radius: int = field(default_factory=lambda: _int("UNSHARP_RADIUS", 3))
    # 0 disables the threshold (sharpen everywhere); >0 avoids amplifying noise.
    unsharp_threshold: int = field(default_factory=lambda: _int("UNSHARP_THRESHOLD", 5))

    # Auto gamma: derives the exponent per frame from measured brightness.
    # Takes precedence over ENABLE_GAMMA when both are on (see enhance_frame).
    enable_auto_gamma: bool = field(default_factory=lambda: _bool("ENABLE_AUTO_GAMMA", False))
    auto_gamma_target_brightness: float = field(
        default_factory=lambda: _float("AUTO_GAMMA_TARGET_BRIGHTNESS", 120.0)
    )
    auto_gamma_min: float = field(default_factory=lambda: _float("AUTO_GAMMA_MIN", 0.5))
    auto_gamma_max: float = field(default_factory=lambda: _float("AUTO_GAMMA_MAX", 3.0))

    # Adaptive median (Gonzalez & Woods Ch.5) for impulse noise.
    enable_adaptive_median: bool = field(
        default_factory=lambda: _bool("ENABLE_ADAPTIVE_MEDIAN", False)
    )
    adaptive_median_max_kernel: int = field(
        default_factory=lambda: _int("ADAPTIVE_MEDIAN_MAX_KERNEL", 7)
    )

    # ---- Module 4: Quality analysis ----
    enable_image_quality: bool = field(
        default_factory=lambda: _bool("ENABLE_IMAGE_QUALITY", False)
    )
    enable_blur_analysis: bool = field(
        default_factory=lambda: _bool("ENABLE_BLUR_ANALYSIS", False)
    )
    # Variance-of-Laplacian below this is flagged as "blurry". Tuned for
    # 720p-ish retail camera frames; recalibrate per camera if needed.
    blur_threshold: float = field(default_factory=lambda: _float("BLUR_THRESHOLD", 100.0))
    # Overall 0-1 quality_score below this is flagged as "poor quality".
    image_quality_threshold: float = field(
        default_factory=lambda: _float("IMAGE_QUALITY_THRESHOLD", 0.5)
    )

    # ---- Module 5: Performance metrics ----
    enable_performance_metrics: bool = field(
        default_factory=lambda: _bool("ENABLE_PERFORMANCE_METRICS", False)
    )

    # ---- Module 6: Debug overlay ----
    enable_debug_overlay: bool = field(
        default_factory=lambda: _bool("ENABLE_DEBUG_OVERLAY", False)
    )

    # ---- Module 7: Per-stage pipeline trace (admin "see every step") ----
    # Stores a JPEG per preprocessing stage — far costlier than the
    # preprocessing itself, so it stays off unless explicitly requested.
    enable_pipeline_trace: bool = field(
        default_factory=lambda: _bool("ENABLE_PIPELINE_TRACE", False)
    )
    # Fraction of frames auto-traced when the master switch is on. 0.0 means
    # "only when the caller explicitly asks" (the admin trace-now button).
    trace_sample_rate: float = field(
        default_factory=lambda: _float("TRACE_SAMPLE_RATE", 0.0)
    )

    # ---- Module 8: DEBUG_AI — per-step artifacts via the background writer ----
    # Distinct from `enable_pipeline_trace`, which flushes synchronously and
    # is meant for one-off "trace this frame now" inspection. DEBUG_AI is the
    # *continuous* mode: artifacts go to a bounded queue and are written by
    # background workers, so a frame never waits on storage. See
    # app/vision/storage/step_writer.py.
    debug_ai: bool = field(default_factory=lambda: _bool("DEBUG_AI", False))
    # Hard cap on queued jobs. When full, samples are dropped rather than
    # blocking the pipeline or growing memory without limit — dropping
    # diagnostics is always preferable to degrading detection.
    debug_ai_queue_size: int = field(
        default_factory=lambda: _int("DEBUG_AI_QUEUE_SIZE", 64)
    )
    debug_ai_workers: int = field(default_factory=lambda: _int("DEBUG_AI_WORKERS", 2))
    debug_ai_jpeg_quality: int = field(
        default_factory=lambda: _int("DEBUG_AI_JPEG_QUALITY", 85)
    )
    # Fraction of frames that produce a debug set while DEBUG_AI is on.
    # 1.0 writes every frame — correct on a test bench, ruinous on a busy
    # camera, hence a separate knob from the master switch.
    debug_ai_sample_rate: float = field(
        default_factory=lambda: _float("DEBUG_AI_SAMPLE_RATE", 1.0)
    )

    # ---- Module 9: SKU classifier (second model stage) ----
    # Off by default: with no trained model present the pipeline must keep
    # behaving exactly as it does today (detector + class_to_sku mapping).
    enable_sku_classifier: bool = field(
        default_factory=lambda: _bool("ENABLE_SKU_CLASSIFIER", False)
    )
    # "onnx" (production inference) or "torch" (torchvision checkpoint).
    classifier_backend: str = field(
        default_factory=lambda: _str("CLASSIFIER_BACKEND", "onnx")
    )
    classifier_model_path: str = field(
        default_factory=lambda: _str("CLASSIFIER_MODEL_PATH", "/models/sku_classifier.onnx")
    )
    classifier_labels_path: str = field(
        default_factory=lambda: _str("CLASSIFIER_LABELS_PATH", "/models/sku_labels.json")
    )
    classifier_input_size: int = field(
        default_factory=lambda: _int("CLASSIFIER_INPUT_SIZE", 224)
    )
    # Below this the classifier's answer is treated as unreliable — the
    # matcher falls back, and (later) OCR is triggered.
    classifier_min_confidence: float = field(
        default_factory=lambda: _float("CLASSIFIER_MIN_CONFIDENCE", 0.55)
    )
    # Khoảng cách tối thiểu giữa lớp top-1 và top-2 (margin) để CHẤP NHẬN
    # nhãn của classifier. Classifier chỉ có N lớp SKU và KHÔNG có lớp
    # "unknown", nên một vật lạ (cốc, sách, điện thoại COCO khoanh được) vẫn
    # bị softmax ép về một SKU. Vật thật thì một lớp trội hẳn (margin lớn);
    # vật lạ thì xác suất chia đều giữa các lớp (margin nhỏ). Đòi hỏi margin
    # tối thiểu là cách rẻ để loại phần lớn dương-tính-giả này mà không cần
    # train lại. Đặt 0.0 để tắt (giữ hành vi cũ). Lưu ý: đây là biện pháp
    # giảm thiểu, không thay được việc train một lớp nền/other cho classifier.
    classifier_min_margin: float = field(
        default_factory=lambda: _float("CLASSIFIER_MIN_MARGIN", 0.20)
    )
    # Crop padding as a fraction of box size; label edges carry the brand.
    crop_padding: float = field(default_factory=lambda: _float("CROP_PADDING", 0.08))
    crop_min_size: int = field(default_factory=lambda: _int("CROP_MIN_SIZE", 24))

    # Đề xuất vùng bằng contour (xử lý ảnh cổ điển) để lấp chỗ detector COCO
    # bỏ sót — chủ yếu là gói mì mà yolov8n không có lớp nào để nhận. Chỉ có
    # tác dụng khi camera đã vẽ ROI (nền ngoài vùng bị che); nếu không có ROI
    # thì cách cổ điển sinh rác nên tracker tự bỏ qua dù cờ có bật. Tắt mặc
    # định: đây là đường tạm thời cho tới khi có detector train bằng cắt-dán.
    enable_classical_proposals: bool = field(
        default_factory=lambda: _bool("ENABLE_CLASSICAL_PROPOSALS", False)
    )

    # ---- Chế độ quầy thanh toán ----
    # Khi bật VÀ camera được đánh dấu là checkout zone: sản phẩm nhận diện
    # được sẽ tự thêm vào đơn, KHÔNG cần một người trong khung. Đúng mô
    # hình quầy thanh toán (đặt sản phẩm → thêm giỏ). Các camera kệ/cửa
    # không đánh dấu checkout vẫn chạy grab-and-go (người cầm sản phẩm) như
    # cũ — nhánh này hoàn toàn tách biệt.
    checkout_scan_mode: bool = field(
        default_factory=lambda: _bool("CHECKOUT_SCAN_MODE", False)
    )

    # ---- Bỏ phiếu nhiều khung (phân biệt sản phẩm giống nhau) ----
    # Bật mặc định: đây là cách tăng độ chính xác trên các cặp lookalike
    # (Hảo Hảo/Gấu Đỏ, 7up/Sting) mà không cần đổi mô hình. Một track được
    # phân loại qua nhiều khung rồi bỏ phiếu, thay vì tin một khung.
    enable_multiframe_voting: bool = field(
        default_factory=lambda: _bool("ENABLE_MULTIFRAME_VOTING", True)
    )
    # Số khung tối thiểu trước khi được phép chốt danh tính một track.
    voting_min_votes: int = field(default_factory=lambda: _int("VOTING_MIN_VOTES", 3))
    # Tỉ lệ đồng thuận tối thiểu để chốt (0.6 = SKU dẫn đầu chiếm ≥60%
    # tổng trọng số phiếu). Dưới ngưỡng nghĩa là các khung cãi nhau — hai
    # sản phẩm quá giống, đẩy sang OCR thay vì đoán bừa.
    voting_agreement_ratio: float = field(
        default_factory=lambda: _float("VOTING_AGREEMENT_RATIO", 0.6)
    )

    # ---- Module 10: OCR fallback (read the label when unsure) ----
    # Off by default and heavy (300 MB - 1 GB depending on backend), so it
    # must be a deliberate choice. Runs only on detections the classifier
    # could not settle — see app/vision/ocr/reader.py.
    enable_ocr_fallback: bool = field(
        default_factory=lambda: _bool("ENABLE_OCR_FALLBACK", False)
    )
    ocr_backend: str = field(default_factory=lambda: _str("OCR_BACKEND", "easyocr"))
    ocr_languages: str = field(default_factory=lambda: _str("OCR_LANGUAGES", "en,vi"))
    ocr_use_gpu: bool = field(default_factory=lambda: _bool("OCR_USE_GPU", False))
    # Trigger when the classifier is under this confidence...
    ocr_trigger_confidence: float = field(
        default_factory=lambda: _float("OCR_TRIGGER_CONFIDENCE", 0.75)
    )
    # ...or when top-1 and top-2 are this close, which is the lookalike
    # case (same brand, different size) that text actually resolves.
    ocr_trigger_margin: float = field(
        default_factory=lambda: _float("OCR_TRIGGER_MARGIN", 0.15)
    )
    # Discard individual text boxes the engine is unsure of; a mis-read
    # "1.5L" is worse than no reading at all, because it decides the SKU.
    ocr_min_text_confidence: float = field(
        default_factory=lambda: _float("OCR_MIN_TEXT_CONFIDENCE", 0.4)
    )
    # Crops shorter than this are upscaled: OCR collapses below ~20 px of
    # text height, and a distant bottle's crop is routinely 60 px tall.
    ocr_min_height: int = field(default_factory=lambda: _int("OCR_MIN_HEIGHT", 160))
    ocr_apply_clahe: bool = field(
        default_factory=lambda: _bool("OCR_APPLY_CLAHE", True)
    )
    # Hard ceiling per frame. OCR is the one stage that can blow the frame
    # budget outright, so a crowded shelf must not turn into a 2-second
    # frame just because 20 objects were all uncertain.
    ocr_max_per_frame: int = field(default_factory=lambda: _int("OCR_MAX_PER_FRAME", 3))

    # ---- Module 11: Embeddings (open-set matching) ----
    enable_embeddings: bool = field(
        default_factory=lambda: _bool("ENABLE_EMBEDDINGS", False)
    )
    # Best match must reach this, or the object is reported as unknown
    # rather than forced onto the nearest trained class.
    embedding_min_similarity: float = field(
        default_factory=lambda: _float("EMBEDDING_MIN_SIMILARITY", 0.75)
    )
    # ...and must beat the runner-up by this, or OCR decides instead.
    embedding_min_margin: float = field(
        default_factory=lambda: _float("EMBEDDING_MIN_MARGIN", 0.05)
    )

    # ---- Module 12: Model sharing / memory ----
    # One YOLO weight shared by every camera instead of one per camera.
    # See app/services/person_tracker.py for why tracker state stays
    # per-camera even when the weights are shared.
    share_yolo_weights: bool = field(
        default_factory=lambda: _bool("SHARE_YOLO_WEIGHTS", True)
    )

    # ---- Module 13: Telemetry push to the backend dashboard ----
    enable_telemetry: bool = field(
        default_factory=lambda: _bool("ENABLE_TELEMETRY", False)
    )
    # Frames are buffered and flushed in batches; one HTTP call per frame
    # at 30 fps would be pure overhead.
    telemetry_batch_size: int = field(
        default_factory=lambda: _int("TELEMETRY_BATCH_SIZE", 20)
    )
    telemetry_flush_seconds: float = field(
        default_factory=lambda: _float("TELEMETRY_FLUSH_SECONDS", 5.0)
    )
    telemetry_max_queue: int = field(
        default_factory=lambda: _int("TELEMETRY_MAX_QUEUE", 500)
    )

    # ---- Module 8: Active-learning capture ----
    # Lives here rather than in review_capture.py's own os.getenv calls so
    # it is tunable from the admin screen like every other vision setting —
    # the capture threshold is exactly the kind of value an operator needs
    # to adjust after seeing how many junk frames reach the review queue.
    enable_review_capture: bool = field(
        default_factory=lambda: _bool("ENABLE_REVIEW_CAPTURE", False)
    )
    # Detections below this are usually noise, not mislabelled products.
    review_capture_min_confidence: float = field(
        default_factory=lambda: _float("REVIEW_CAPTURE_MIN_CONFIDENCE", 0.15)
    )
    # At most one capture per camera per window, so a camera staring at one
    # ambiguous object can't bury the reviewer in near-identical frames.
    review_capture_cooldown_seconds: float = field(
        default_factory=lambda: _float("REVIEW_CAPTURE_COOLDOWN_SECONDS", 60.0)
    )

    @property
    def any_enhancement_enabled(self) -> bool:
        return (
            self.enable_clahe
            or self.enable_hist_eq
            or self.enable_brightness
            or self.enable_contrast
            or self.enable_gamma
            or self.enable_gaussian_blur
            or self.enable_median_blur
            or self.enable_bilateral
            or self.enable_unsharp_mask
            or self.enable_auto_gamma
            or self.enable_adaptive_median
        )


_CONFIG: VisionConfig | None = None
_LOADED_MTIME: float | None = None
_LAST_MTIME_CHECK: float = 0.0


# Env-var name -> dataclass field name, derived once. Used to validate and
# serialise runtime overrides without hand-maintaining a second list.
def _field_by_env_name() -> dict[str, str]:
    # Most fields mirror their env var exactly (enable_clahe ->
    # ENABLE_CLAHE); these two don't, so the generated name is replaced
    # rather than kept alongside — accepting a key the pipeline never
    # reads would let an operator "set" a flag that does nothing.
    aliases = {
        "enable_brightness": "ENABLE_BRIGHTNESS_ADJUST",
        "enable_contrast": "ENABLE_CONTRAST_ADJUST",
    }
    mapping: dict[str, str] = {}
    for f in fields(VisionConfig):
        mapping[aliases.get(f.name, f.name.upper())] = f.name
    return mapping


ENV_TO_FIELD: dict[str, str] = _field_by_env_name()


def _current_mtime() -> float | None:
    try:
        return os.path.getmtime(runtime_config_path())
    except OSError:
        return None


def get_vision_config() -> VisionConfig:
    """Effective config, reloading if the runtime override file changed.

    The mtime check is throttled so a busy frame loop doesn't stat() the
    file thousands of times a second.
    """
    global _CONFIG, _LAST_MTIME_CHECK, _LOADED_MTIME
    now = time.monotonic()
    if _CONFIG is None:
        return reload_vision_config()
    if now - _LAST_MTIME_CHECK >= _MTIME_CHECK_SECONDS:
        _LAST_MTIME_CHECK = now
        if _current_mtime() != _LOADED_MTIME:
            return reload_vision_config()
    return _CONFIG


def reload_vision_config() -> VisionConfig:
    """Re-read the runtime override file *and* the environment.

    Called automatically when the override file changes, and directly by
    tests / tools that mutate env vars at runtime.
    """
    global _CONFIG, _LOADED_MTIME, _LAST_MTIME_CHECK, _OVERRIDES
    _OVERRIDES = _read_override_file()
    _LOADED_MTIME = _current_mtime()
    _LAST_MTIME_CHECK = time.monotonic()
    _CONFIG = VisionConfig()
    return _CONFIG


def get_runtime_overrides() -> dict[str, str]:
    """The override file's current contents (what the admin UI has set)."""
    return dict(_read_override_file())


def save_runtime_overrides(overrides: dict[str, object]) -> dict[str, str]:
    """Persist runtime overrides and apply them immediately.

    Unknown keys are rejected rather than silently stored: a typo'd flag
    that quietly does nothing is worse than an error, because the operator
    would believe a setting is active when it isn't.

    Passing a key with value ``None`` removes that override, falling back
    to the environment/default value.
    """
    current = _read_override_file()

    for key, value in overrides.items():
        env_key = str(key).upper()
        if env_key not in ENV_TO_FIELD:
            raise KeyError(f"Unknown vision setting: {key}")
        if value is None:
            current.pop(env_key, None)
        elif isinstance(value, bool):
            current[env_key] = "true" if value else "false"
        else:
            current[env_key] = str(value)

    path = runtime_config_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # Write-then-rename so a reader never sees a half-written file.
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(current, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)

    reload_vision_config()
    return current
    return _CONFIG
