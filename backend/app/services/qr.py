"""QR code rendering for customer-facing checkout confirmation.

Renders straight to an inline SVG string (via qrcode's SVG image factory)
so the frontend can drop it into the DOM with no extra JS dependency and
the backend doesn't need Pillow just to draw a PNG.
"""

from __future__ import annotations

import io

import qrcode
import qrcode.image.svg


def render_qr_svg(data: str) -> str:
    """Return a standalone `<svg>...</svg>` string encoding `data`."""
    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(data, image_factory=factory, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")
