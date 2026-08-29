"""SKU classifier — the second model stage.

Why this stage exists at all
----------------------------
The detector is COCO-pretrained, so its vocabulary is generic: it can say
"bottle" but never "Aquafina 500ml". Mapping that single ``bottle`` class
to a SKU (which ``product_mapper`` does today) therefore collapses every
bottled product in the store onto one product — the root cause of the
"AI nhận diện sai nhiều" reports.

Fine-tuning the detector on SKUs looks like the obvious fix, but the
existing trainer labels each uploaded image with a box covering the whole
image, which teaches the detector "this entire picture is class X". That
destroys localisation: it can no longer separate two products in one
frame. Keeping detection generic and adding a dedicated classifier on the
crop keeps each model doing what it is good at.

Backends
--------
* ``onnx``  — ONNX Runtime. The production inference path: no torchvision
  dependency, several times faster than eager PyTorch on CPU (which is
  what this deployment runs), and loadable in environments where only
  ``onnxruntime`` is installed.
* ``torch`` — torchvision MobileNetV3. Used for training and as a fallback
  when only a ``.pt`` checkpoint exists.

MobileNetV3-Small is the default rather than EfficientNet because this
service runs on CPU (``YOLO_DEVICE=cpu``); at the 20–50 class scale of a
store catalogue it reaches comparable accuracy for a fraction of the
latency.

Failure behaviour
-----------------
Every failure path returns ``None`` instead of raising. A missing or
broken classifier must degrade the system to "detector-only" (i.e. today's
behaviour), never break frame processing.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger("ai-engine.vision.classifier")

# Standard ImageNet normalisation — MobileNetV3 weights expect it, and the
# training script must use the identical values or accuracy silently drops.
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass(frozen=True)
class ClassificationResult:
    sku: str
    confidence: float
    label_index: int
    model_version: str
    # Runner-up, so the caller can tell "confident" from "coin flip between
    # two lookalike SKUs" — two very different situations that a single
    # top-1 score hides.
    runner_up_sku: str | None = None
    runner_up_confidence: float | None = None
    # Penultimate-layer features, when the backend exposes them. Reused as
    # the similarity embedding so no second model is needed.
    embedding: list[float] | None = None

    @property
    def margin(self) -> float:
        """Gap to the runner-up. A small margin means the two classes were
        nearly tied even if top-1 looks high."""
        if self.runner_up_confidence is None:
            return self.confidence
        return self.confidence - self.runner_up_confidence


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def preprocess_crop(crop_bgr: np.ndarray, size: int = 224) -> np.ndarray:
    """BGR crop -> NCHW float32 batch of 1, ImageNet-normalised.

    Uses ``INTER_AREA`` when shrinking: crops are usually larger than the
    network input, and area interpolation preserves label text far better
    than the default bilinear, which matters because the label *is* the
    distinguishing feature between SKUs.
    """
    import cv2

    h, w = crop_bgr.shape[:2]
    interp = cv2.INTER_AREA if (h > size or w > size) else cv2.INTER_LINEAR
    resized = cv2.resize(crop_bgr, (size, size), interpolation=interp)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    normalised = (rgb - _IMAGENET_MEAN) / _IMAGENET_STD
    return np.transpose(normalised, (2, 0, 1))[np.newaxis, ...].astype(np.float32)


class SkuClassifier:
    """Lazily-loaded SKU classifier. Thread-safe, load-once."""

    def __init__(
        self,
        model_path: str,
        labels_path: str,
        *,
        backend: str = "onnx",
        input_size: int = 224,
    ) -> None:
        self.model_path = model_path
        self.labels_path = labels_path
        self.backend = backend
        self.input_size = input_size
        self._session: Any = None
        self._labels: list[str] = []
        self._version: str = "unloaded"
        self._load_failed = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------- loading

    def _load_labels(self) -> list[str]:
        """Labels file maps output index -> SKU.

        Accepts either a plain list or ``{"labels": [...]}`` so a file
        written by the training script or by hand both work.
        """
        with open(self.labels_path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            raw = raw.get("labels", [])
        if not isinstance(raw, list) or not raw:
            raise ValueError("labels file must contain a non-empty list")
        return [str(x) for x in raw]

    def _ensure_loaded(self) -> bool:
        if self._session is not None:
            return True
        if self._load_failed:
            return False  # don't retry a broken path on every single frame
        with self._lock:
            if self._session is not None:
                return True
            if self._load_failed:
                return False
            try:
                self._labels = self._load_labels()
                if self.backend == "onnx":
                    import onnxruntime as ort

                    self._session = ort.InferenceSession(
                        self.model_path, providers=["CPUExecutionProvider"]
                    )
                else:
                    import torch

                    model = torch.load(self.model_path, map_location="cpu", weights_only=False)
                    model.eval()
                    self._session = model
                self._version = os.path.basename(self.model_path)
                logger.info(
                    "SKU classifier loaded backend=%s classes=%d model=%s",
                    self.backend,
                    len(self._labels),
                    self._version,
                )
                return True
            except Exception:
                # Missing model is the normal state before the first
                # training run, so this must not be fatal — the pipeline
                # falls back to detector-only behaviour.
                logger.warning(
                    "SKU classifier unavailable (backend=%s, model=%s) — "
                    "falling back to detector-only classification",
                    self.backend,
                    self.model_path,
                    exc_info=True,
                )
                self._load_failed = True
                return False

    @property
    def available(self) -> bool:
        return self._ensure_loaded()

    @property
    def num_classes(self) -> int:
        return len(self._labels) if self._ensure_loaded() else 0

    # ----------------------------------------------------------- inference

    def _forward(self, batch: np.ndarray) -> np.ndarray:
        if self.backend == "onnx":
            name = self._session.get_inputs()[0].name
            out = self._session.run(None, {name: batch})[0]
            return np.asarray(out)
        import torch

        with torch.no_grad():
            out = self._session(torch.from_numpy(batch))
        return out.detach().cpu().numpy()

    def classify(self, crop_bgr: np.ndarray) -> ClassificationResult | None:
        """Identify one crop. ``None`` when the classifier is unavailable."""
        results = self.classify_batch([crop_bgr])
        return results[0] if results else None

    def classify_batch(
        self, crops: list[np.ndarray]
    ) -> list[ClassificationResult | None]:
        """Classify several crops in one forward pass.

        Batching matters on CPU: per-call overhead dominates at this model
        size, so classifying the 3 products in a frame together is close to
        the cost of classifying one.
        """
        if not crops:
            return []
        if not self._ensure_loaded():
            return [None] * len(crops)

        try:
            batch = np.concatenate(
                [preprocess_crop(c, self.input_size) for c in crops], axis=0
            )
            logits = self._forward(batch)
        except Exception:
            logger.exception("SKU classification failed")
            return [None] * len(crops)

        out: list[ClassificationResult | None] = []
        for row in logits:
            row = np.asarray(row).reshape(-1)
            if row.size != len(self._labels):
                # Model and labels disagree — using it anyway would emit
                # confident but wrongly-named SKUs, which is worse than
                # emitting nothing.
                logger.error(
                    "classifier output size %d != labels %d; check the model/labels pair",
                    row.size,
                    len(self._labels),
                )
                out.append(None)
                continue
            probs = _softmax(row.astype(np.float32))
            order = np.argsort(probs)[::-1]
            top = int(order[0])
            second = int(order[1]) if probs.size > 1 else None
            out.append(
                ClassificationResult(
                    sku=self._labels[top],
                    confidence=float(probs[top]),
                    label_index=top,
                    model_version=self._version,
                    runner_up_sku=self._labels[second] if second is not None else None,
                    runner_up_confidence=(
                        float(probs[second]) if second is not None else None
                    ),
                )
            )
        return out


# ------------------------------------------------------------------ module

_CLASSIFIER: SkuClassifier | None = None
_CLASSIFIER_LOCK = threading.Lock()


def get_classifier() -> SkuClassifier | None:
    """Process-wide classifier, or ``None`` when disabled by config."""
    global _CLASSIFIER
    from app.vision.config import get_vision_config

    cfg = get_vision_config()
    if not cfg.enable_sku_classifier:
        return None
    if _CLASSIFIER is not None:
        return _CLASSIFIER
    with _CLASSIFIER_LOCK:
        if _CLASSIFIER is None:
            _CLASSIFIER = SkuClassifier(
                cfg.classifier_model_path,
                cfg.classifier_labels_path,
                backend=cfg.classifier_backend,
                input_size=cfg.classifier_input_size,
            )
    return _CLASSIFIER


def reset_classifier() -> None:
    """Drop the cached instance so a newly deployed model is picked up."""
    global _CLASSIFIER
    with _CLASSIFIER_LOCK:
        _CLASSIFIER = None
