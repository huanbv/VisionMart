"""Annotate a still (Tải ảnh / Chụp & Quét) with product names and attach it to the cart."""

from __future__ import annotations

import io
import logging
import os
import uuid
from functools import lru_cache
from typing import Any

from app.modules.sales.application.cart_service import CartService
from app.services.object_storage import MinioStorage, ObjectStorageError

logger = logging.getLogger(__name__)

_PALETTE = (
    (60, 180, 75),
    (255, 127, 14),
    (31, 119, 180),
    (214, 39, 40),
    (148, 103, 189),
    (140, 86, 75),
    (227, 119, 194),
    (44, 160, 44),
)

_FONT_CANDIDATES = (
    os.environ.get("VISIONMART_OVERLAY_FONT") or "",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
)


@lru_cache(maxsize=1)
def _font_path() -> str | None:
    for path in _FONT_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def _font(size: int):
    from PIL import ImageFont

    path = _font_path()
    if not path:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def detection_label(det: dict[str, Any]) -> str:
    name = str(det.get("name") or "").strip()
    sku = str(det.get("sku") or "").strip()
    if name and sku and name.casefold() != sku.casefold():
        return f"{name} ({sku})"
    return name or sku or str(det.get("class_name") or "Sản phẩm")


def _color_for(key: str) -> tuple[int, int, int]:
    if not key:
        return _PALETTE[0]
    return _PALETTE[sum(ord(ch) for ch in key) % len(_PALETTE)]


def session_id_from_emitted(camera_id: uuid.UUID, pipeline: dict[str, Any] | None) -> str | None:
    """Cart session created by a manual product_scanned burst (same track_id)."""
    for item in (pipeline or {}).get("emitted_events") or []:
        if not isinstance(item, dict):
            continue
        event = item.get("event") if isinstance(item.get("event"), dict) else item
        if not isinstance(event, dict):
            continue
        if str(event.get("event_type") or "") != "product_scanned":
            continue
        track_id = str(event.get("track_id") or "").strip()
        if track_id:
            return f"cam:{camera_id}:track:{track_id}"
    return None


def annotate_scan_jpeg(
    image_bytes: bytes,
    detections: list[Any],
    *,
    source_width: int = 0,
    source_height: int = 0,
) -> bytes | None:
    """Draw boxes + catalog names onto the uploaded/captured still.

    ``source_width`` / ``source_height`` are the frame the bboxes were
    measured on (ai-engine ``image`` meta). When they differ from the
    original file, boxes are scaled so labels land on the right products.
    """
    from PIL import Image, ImageDraw

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:  # noqa: BLE001
        logger.exception("scan photo: could not decode still")
        return None

    draw = ImageDraw.Draw(image)
    img_w, img_h = image.size
    sx = (img_w / source_width) if source_width > 0 else 1.0
    sy = (img_h / source_height) if source_height > 0 else 1.0
    font_size = max(14, min(28, img_w // 42))
    font = _font(font_size)
    stroke = max(2, img_w // 480)

    drawn = 0
    for det in detections:
        if not isinstance(det, dict):
            continue
        bbox = det.get("bbox")
        if not isinstance(bbox, dict):
            continue
        try:
            x1 = int(round(float(bbox["x1"]) * sx))
            y1 = int(round(float(bbox["y1"]) * sy))
            x2 = int(round(float(bbox["x2"]) * sx))
            y2 = int(round(float(bbox["y2"]) * sy))
        except (KeyError, TypeError, ValueError):
            continue
        x1, x2 = max(0, min(x1, x2)), min(img_w - 1, max(x1, x2))
        y1, y2 = max(0, min(y1, y2)), min(img_h - 1, max(y1, y2))
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        label = detection_label(det)
        color = _color_for(str(det.get("sku") or det.get("name") or label))
        draw.rectangle((x1, y1, x2, y2), outline=color, width=stroke)
        text_bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
        pad = 4
        lx = max(0, min(x1, img_w - tw - pad * 2 - 1))
        ly = y1 - th - pad * 2 - 2
        if ly < 0:
            ly = min(y1 + 2, img_h - th - pad * 2 - 1)
        draw.rectangle(
            (lx, ly, lx + tw + pad * 2, ly + th + pad * 2),
            fill=color,
        )
        draw.text((lx + pad, ly + pad), label, fill=(255, 255, 255), font=font)
        drawn += 1

    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=88)
    if drawn == 0:
        logger.warning("scan photo: no product boxes drawn on still")
    return buf.getvalue()


async def attach_scan_photo_to_cart(
    *,
    carts: CartService,
    organization_id: uuid.UUID,
    branch_id: uuid.UUID,
    camera_id: uuid.UUID,
    image_bytes: bytes,
    detections: list[Any],
    pipeline: dict[str, Any] | None,
    source_width: int = 0,
    source_height: int = 0,
) -> str | None:
    """Best-effort: never fail Tải ảnh / Chụp & Quét if overlay or MinIO fails."""
    session_id = session_id_from_emitted(camera_id, pipeline)
    if not session_id:
        return None
    try:
        cart = await carts.get_open_cart_for_session(
            organization_id, branch_id, session_id
        )
    except Exception:  # noqa: BLE001
        logger.exception("scan photo: lookup cart failed session=%s", session_id)
        return None
    if cart is None:
        return None

    jpeg = annotate_scan_jpeg(
        image_bytes,
        detections,
        source_width=source_width,
        source_height=source_height,
    )
    if not jpeg:
        return None

    key = f"carts/scan-frames/{organization_id}/{cart.id}.jpg"
    try:
        storage = MinioStorage()
        await storage.put(key, jpeg, content_type="image/jpeg")
        await carts.set_scan_photo_key(organization_id, cart.id, key)
    except ObjectStorageError:
        logger.exception("scan photo: MinIO put failed cart=%s", cart.id)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("scan photo: attach failed cart=%s", cart.id)
        return None
    return key
