"""ROI zone definitions + loading + application.

Config file format (YAML, path given by ``ROI_CONFIG_PATH``)::

    cameras:
      "<camera_key>":              # matches the camera_key used elsewhere
        zones:                     # in person_tracker.py / frame.py
          - name: checkout_1
            type: checkout          # entrance | shelf | checkout | exit
            points:                 # fractional (0-1) polygon, so it's
              - [0.55, 0.0]          # resolution-independent
              - [1.0, 0.0]
              - [1.0, 1.0]
              - [0.55, 1.0]
      default:                     # optional fallback used when a camera
        zones: []                  # has no entry of its own

If ``ROI_CONFIG_PATH`` is unset, unreadable, or has no entry for a given
camera (and no ``default``), ``load_roi_config`` returns an empty zone list
and ``apply_roi`` is a no-op — this is the "ROI disabled" behaviour, and is
also what happens whenever ``ENABLE_ROI`` itself is off (checked by the
caller in ``pipeline.py``, not in here).
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger("ai-engine.vision.roi")

_VALID_ZONE_TYPES = {"entrance", "shelf", "checkout", "exit"}

_CACHE_LOCK = threading.Lock()
# path -> (mtime, parsed_yaml)
_FILE_CACHE: dict[str, tuple[float, dict]] = {}


@dataclass(frozen=True)
class RoiZone:
    name: str
    zone_type: str
    # Fractional (0.0-1.0) polygon points, resolution-independent.
    points: tuple[tuple[float, float], ...]

    def to_pixel_polygon(self, width: int, height: int) -> np.ndarray:
        return np.array(
            [[int(x * width), int(y * height)] for x, y in self.points],
            dtype=np.int32,
        )


def _load_yaml_cached(path: str) -> dict:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    with _CACHE_LOCK:
        cached = _FILE_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
    try:
        import yaml  # PyYAML — already a dependency (requirements.txt)

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:  # noqa: BLE001
        logger.exception("failed to load ROI config from %s", path)
        data = {}
    with _CACHE_LOCK:
        _FILE_CACHE[path] = (mtime, data)
    return data


def _parse_zones(raw_zones: list) -> list[RoiZone]:
    zones: list[RoiZone] = []
    for raw in raw_zones or []:
        try:
            name = str(raw["name"])
            zone_type = str(raw.get("type", "shelf")).lower()
            if zone_type not in _VALID_ZONE_TYPES:
                logger.warning(
                    "ROI zone %r has unknown type %r, defaulting to 'shelf'",
                    name,
                    zone_type,
                )
                zone_type = "shelf"
            points = tuple((float(p[0]), float(p[1])) for p in raw["points"])
            if len(points) < 3:
                logger.warning("ROI zone %r has < 3 points, skipping", name)
                continue
            zones.append(RoiZone(name=name, zone_type=zone_type, points=points))
        except (KeyError, TypeError, ValueError, IndexError):
            logger.exception("skipping malformed ROI zone entry: %r", raw)
    return zones


def load_roi_config(config_path: str, camera_key: str) -> list[RoiZone]:
    """Load the zone list for one camera. Returns ``[]`` (= ROI is a no-op)
    if the path is empty/unreadable, or neither ``camera_key`` nor
    ``default`` has an entry."""
    if not config_path:
        return []
    data = _load_yaml_cached(config_path)
    cameras = data.get("cameras") or {}
    entry = cameras.get(camera_key) or data.get("default")
    if not entry:
        return []
    return _parse_zones(entry.get("zones"))


def zones_from_payload(raw_zones: list | None) -> list[RoiZone]:
    """Dung RoiZone tu payload JSON (vung ve tren Admin, luu trong DB).

    Ton tai song song voi load_roi_config (doc file YAML) vi hai nguon co
    vong doi khac han: YAML la cau hinh van hanh sua bang tay va deploy,
    con vung ve tren UI thay doi bat cu luc nao nguoi dung keo chuot. Dung
    lai _parse_zones nen moi kiem tra (it nhat 3 diem, zone_type hop le)
    ap dung y het cho ca hai nguon — mot vung ve loi khong the lot qua chi
    vi no den tu duong khac.
    """
    if not raw_zones:
        return []
    return _parse_zones(raw_zones)


def apply_roi(frame_bgr: np.ndarray, zones: list[RoiZone]) -> np.ndarray:
    """Mask out everything not inside the union of ``zones``.

    Masking (blacking out pixels) rather than cropping preserves the
    frame's original dimensions and aspect ratio, so it doesn't change
    YOLO's input resolution/letterboxing behaviour — only which pixels
    carry real image data. If ``zones`` is empty this is a no-op (returns
    ``frame_bgr`` unchanged, not even a copy, to avoid a pointless
    allocation on the hot path when ROI is disabled or unconfigured).
    """
    if not zones:
        return frame_bgr

    import cv2  # local import: keep vision/ submodules cheap to import in isolation

    height, width = frame_bgr.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    for zone in zones:
        polygon = zone.to_pixel_polygon(width, height)
        cv2.fillPoly(mask, [polygon], 255)

    masked = cv2.bitwise_and(frame_bgr, frame_bgr, mask=mask)
    return masked


def point_in_zones(
    zones: list[RoiZone], x: float, y: float, width: int, height: int
) -> bool:
    """True khi điểm pixel (x, y) nằm trong hợp của các vùng.

    Dùng cho lớp phủ xem-trực-tiếp: chỉ VẼ box của vật có tâm nằm trong vùng
    để hình khớp với hành vi thêm-vào-giỏ (vốn dựa trên mặt nạ ROI). Vùng
    rỗng => coi như không giới hạn (trả True), giữ nguyên hành vi cũ khi camera
    chưa vẽ vùng.
    """
    if not zones:
        return True

    import cv2

    for zone in zones:
        polygon = zone.to_pixel_polygon(width, height)
        if cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0:
            return True
    return False


def zone_union_bbox(
    zones: list[RoiZone], width: int, height: int
) -> tuple[int, int, int, int] | None:
    """Axis-aligned bounding rect of the union of zones, in pixels."""
    if not zones:
        return None
    xs: list[int] = []
    ys: list[int] = []
    for zone in zones:
        for x, y in zone.points:
            xs.append(int(round(x * width)))
            ys.append(int(round(y * height)))
    if not xs:
        return None
    return (
        max(0, min(xs)),
        max(0, min(ys)),
        min(width, max(xs)),
        min(height, max(ys)),
    )


def box_fraction_in_zones(
    zones: list[RoiZone],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: int,
    height: int,
) -> float:
    """How much of the detection box (by area) lies inside the ROI union.

    A giant box whose label sits on a statue to the left of the pay zone
    can still have its *center* inside the polygon. Requiring most of the
    box to overlap the zone drops those false positives.
    """
    if not zones:
        return 1.0
    import cv2

    w, h = max(1, int(width)), max(1, int(height))
    bx1 = int(max(0, min(w, x1)))
    by1 = int(max(0, min(h, y1)))
    bx2 = int(max(0, min(w, x2)))
    by2 = int(max(0, min(h, y2)))
    box_area = float(max(1, bx2 - bx1) * max(1, by2 - by1))
    mask = np.zeros((h, w), dtype=np.uint8)
    for zone in zones:
        cv2.fillPoly(mask, [zone.to_pixel_polygon(w, h)], 255)
    box = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(box, (bx1, by1), (bx2, by2), 255, -1)
    inter = cv2.countNonZero(cv2.bitwise_and(mask, box))
    return float(inter) / box_area


def box_mostly_in_zones(
    zones: list[RoiZone],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: int,
    height: int,
    min_frac: float = 0.5,
) -> bool:
    """True when the box is a product sitting in the pay zone, not spilling out."""
    if not zones:
        return True
    return box_fraction_in_zones(zones, x1, y1, x2, y2, width, height) >= min_frac
