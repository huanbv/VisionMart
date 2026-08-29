"""OCR stage — read the label when the classifier cannot decide.

Why OCR is a *fallback* and not a stage that always runs
-------------------------------------------------------
It is the most expensive stage in the pipeline by a wide margin (tens to
hundreds of ms per crop, versus ~5 ms for the classifier) and the engines
weigh 300 MB - 1 GB on disk. Running it on every detection would dominate
the frame budget to answer a question the classifier has usually already
answered confidently.

So it runs only where it adds information: when the classifier's confidence
is below threshold, or when its top-2 margin is thin. Those are exactly the
lookalike cases — same bottle silhouette, same brand, different size — where
the discriminating evidence is *printed text* ("500ml" vs "1.5L") that a
whole-crop classifier tends to wash out at 224x224.

Engine choice
-------------
Two optional backends, neither installed by default:

* ``easyocr``    — simplest to install, decent on product labels, ~100 MB.
* ``paddleocr``  — better accuracy on small/curved text, heavier (~1 GB with
  its dependency chain), and notoriously fussy about versions.

Both are imported lazily and only when the stage is switched on, so a
deployment that never enables OCR does not pay the image size, the import
time, or the version conflicts. If the import fails the stage disables
itself permanently for the process (``_load_failed``) and the pipeline
degrades to classifier-only rather than retrying a failing import on every
frame.

Deployment note
---------------
TODO(ocr-service): if OCR is enabled on more than a couple of cameras,
move it behind its own container. It is CPU-hungry and its dependency tree
conflicts with ultralytics' pinned versions often enough that co-locating
them makes the ai-engine image fragile to rebuild.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("ai-engine.vision.ocr")


@dataclass(frozen=True)
class OcrResult:
    """What the OCR stage extracted from one crop."""

    raw_text: str
    confidence: float
    engine: str
    elapsed_ms: float
    # Parsed fields — the only parts the matcher consumes. Raw text is kept
    # so a parser bug can be diagnosed offline without re-reading images.
    brand: str | None = None
    volume_ml: int | None = None
    weight_g: int | None = None
    lines: list[str] = field(default_factory=list)

    @property
    def has_signal(self) -> bool:
        """Whether anything usable for matching came out.

        Text alone is not signal: a crop can OCR to "NEW" or a barcode's
        digits and still say nothing about which SKU this is. Only a parsed
        brand or size narrows the candidate set.
        """
        return self.brand is not None or self.volume_ml is not None or self.weight_g is not None


# --------------------------------------------------------------- parsing
# Vietnamese labels write sizes several ways; all of these appear on real
# shelf products, which is why the pattern is this permissive:
#   500ml  500 ML  0.5L  1,5 L  1.5 lít
_VOLUME_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(ml|mL|ML|l|L|lit|lít|LIT)\b",
    re.IGNORECASE,
)
_WEIGHT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(g|G|gr|GR|kg|KG)\b",
)


def parse_volume_ml(text: str) -> int | None:
    """Extract a volume in millilitres.

    Returns the *largest* plausible match rather than the first. Labels
    carry incidental numbers — batch codes, "no. 1", nutrition tables — and
    the headline size is almost always the biggest volume-shaped token on
    the pack.
    """
    best: int | None = None
    for raw, unit in _VOLUME_RE.findall(text):
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        unit_l = unit.lower()
        ml = value * 1000.0 if unit_l in ("l", "lit", "lít") else value
        ml_int = int(round(ml))
        # Reject implausible sizes: a "2024" from a date would otherwise
        # become a 2-litre bottle.
        if not (10 <= ml_int <= 20000):
            continue
        if best is None or ml_int > best:
            best = ml_int
    return best


def parse_weight_g(text: str) -> int | None:
    best: int | None = None
    for raw, unit in _WEIGHT_RE.findall(text):
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        grams = value * 1000.0 if unit.lower() == "kg" else value
        g_int = int(round(grams))
        if not (5 <= g_int <= 20000):
            continue
        if best is None or g_int > best:
            best = g_int
    return best


def match_brand(text: str, known_brands: list[str]) -> str | None:
    """Find a known brand inside OCR output.

    Matches against the tenant's own product brands rather than a fixed
    list, so it works for whatever a shop actually stocks. Comparison is
    case- and space-insensitive because OCR spacing is unreliable — it
    routinely returns "AQUA FINA" or "Aquafina" for the same label.
    """
    if not text or not known_brands:
        return None
    haystack = re.sub(r"[^a-z0-9]", "", text.lower())
    best: str | None = None
    for brand in known_brands:
        needle = re.sub(r"[^a-z0-9]", "", brand.lower())
        # Very short brand names would match inside unrelated words.
        if len(needle) < 3:
            continue
        if needle in haystack:
            # Longest match wins: "cocacolazero" should not resolve to
            # "coca" when "coca-cola zero" is also a stocked brand.
            if best is None or len(needle) > len(re.sub(r"[^a-z0-9]", "", best.lower())):
                best = brand
    return best


# ---------------------------------------------------------------- engine
class OcrReader:
    """Lazily-loaded OCR engine wrapper. Never raises into the pipeline."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._engine: Any = None
        self._load_failed = False
        self._backend = getattr(cfg, "ocr_backend", "easyocr")

    def _ensure_loaded(self) -> bool:
        if self._engine is not None:
            return True
        if self._load_failed:
            return False
        langs = [s.strip() for s in getattr(self.cfg, "ocr_languages", "en,vi").split(",") if s.strip()]
        try:
            if self._backend == "paddleocr":
                from paddleocr import PaddleOCR

                self._engine = PaddleOCR(
                    use_angle_cls=True,
                    lang=langs[0] if langs else "en",
                    show_log=False,
                )
            else:
                import easyocr

                self._engine = easyocr.Reader(
                    langs or ["en"],
                    gpu=bool(getattr(self.cfg, "ocr_use_gpu", False)),
                    verbose=False,
                )
            logger.info("OCR engine loaded: %s langs=%s", self._backend, langs)
            return True
        except Exception:
            # Marked permanently failed: without this, a missing package
            # would cost an import attempt (and a stack trace) on every
            # single frame for the life of the process.
            self._load_failed = True
            logger.exception(
                "OCR backend '%s' unavailable — stage disabled for this process. "
                "Install it or set ENABLE_OCR_FALLBACK=false.",
                self._backend,
            )
            return False

    def read(self, crop_bgr, known_brands: list[str] | None = None) -> OcrResult | None:
        """Read one crop. Returns ``None`` on any failure — never raises."""
        if crop_bgr is None or not self._ensure_loaded():
            return None

        t0 = time.perf_counter()
        try:
            prepared = preprocess_for_ocr(crop_bgr, self.cfg)
            lines, confidences = self._run_engine(prepared)
        except Exception:
            logger.exception("OCR read failed")
            return None

        elapsed = round((time.perf_counter() - t0) * 1000.0, 2)
        text = " ".join(lines)
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return OcrResult(
            raw_text=text,
            confidence=round(float(mean_conf), 4),
            engine=self._backend,
            elapsed_ms=elapsed,
            brand=match_brand(text, known_brands or []),
            volume_ml=parse_volume_ml(text),
            weight_g=parse_weight_g(text),
            lines=lines,
        )

    def _run_engine(self, image) -> tuple[list[str], list[float]]:
        lines: list[str] = []
        confs: list[float] = []
        min_conf = float(getattr(self.cfg, "ocr_min_text_confidence", 0.4))

        if self._backend == "paddleocr":
            result = self._engine.ocr(image, cls=True)
            for page in result or []:
                for entry in page or []:
                    try:
                        text, conf = entry[1][0], float(entry[1][1])
                    except (IndexError, TypeError, ValueError):
                        continue
                    if conf >= min_conf:
                        lines.append(str(text))
                        confs.append(conf)
        else:
            for entry in self._engine.readtext(image) or []:
                try:
                    text, conf = str(entry[1]), float(entry[2])
                except (IndexError, TypeError, ValueError):
                    continue
                if conf >= min_conf:
                    lines.append(text)
                    confs.append(conf)
        return lines, confs


def preprocess_for_ocr(crop_bgr, cfg):
    """Prepare a crop for text recognition.

    This is a *different* preprocessing goal from the detection pipeline,
    which is why it does not reuse ``enhance.py``. Detection wants a
    natural-looking image; OCR wants maximum stroke contrast and enough
    pixels per character. Concretely:

    * **Upscale small crops.** OCR engines have a minimum text height
      (roughly 20 px) below which recognition collapses. A distant bottle's
      crop is often 60 px tall, so it is upscaled with ``INTER_CUBIC`` —
      here interpolation is wanted, because smoothing the jaggies helps the
      recogniser more than preserving exact pixels does.
    * **CLAHE on the luminance channel only.** Label text is usually a
      local-contrast problem (glare on one side of a curved bottle), which
      global equalisation cannot fix.

    Deliberately *not* binarised: modern OCR models are trained on natural
    images, and thresholding a curved, glossy label destroys more strokes
    than it recovers.
    """
    import cv2

    target = int(getattr(cfg, "ocr_min_height", 160))
    img = crop_bgr
    h, w = img.shape[:2]
    if h < target and h > 0:
        scale = min(target / float(h), 4.0)  # cap: beyond 4x is invention
        img = cv2.resize(
            img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_CUBIC
        )

    if getattr(cfg, "ocr_apply_clahe", True):
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        img = cv2.cvtColor(cv2.merge((clahe.apply(l_ch), a_ch, b_ch)), cv2.COLOR_LAB2BGR)

    return img


def should_run_ocr(classification, cfg) -> bool:
    """Whether this detection is worth an OCR pass.

    Two independent triggers, because low confidence and a thin margin are
    different failure modes:

    * **Low top-1 confidence** — the model does not recognise this at all.
    * **Thin margin** — the model is *confident but torn* between two
      classes. This is the lookalike case (same brand, different size), and
      it is precisely where printed text decides the answer. A
      margin-triggered OCR pass can be worth more than a
      confidence-triggered one, which is why margin is checked even when
      top-1 confidence is high.
    """
    if not getattr(cfg, "enable_ocr_fallback", False):
        return False
    if classification is None:
        # Nothing to disambiguate but also nothing to lose: an unclassified
        # crop is exactly where reading the label may still identify it.
        return True
    if classification.confidence < float(getattr(cfg, "ocr_trigger_confidence", 0.75)):
        return True
    margin = getattr(classification, "margin", None)
    if margin is not None and margin < float(getattr(cfg, "ocr_trigger_margin", 0.15)):
        return True
    return False


_READER: OcrReader | None = None


def get_reader(cfg) -> OcrReader:
    global _READER
    if _READER is None:
        _READER = OcrReader(cfg)
    return _READER


def reset_reader() -> None:
    """Drop the cached engine so a backend change takes effect (tests/admin)."""
    global _READER
    _READER = None
