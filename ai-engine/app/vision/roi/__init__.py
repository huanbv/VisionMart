"""Module 2 — Region Of Interest (ROI) processing.

Zones are loaded from a YAML file (``ROI_CONFIG_PATH``), never hardcoded.
When ``ENABLE_ROI`` is off, or no zones are configured for a given camera,
``apply_roi`` is a no-op and returns the frame unchanged — the system
behaves exactly as before this Sprint.
"""

from __future__ import annotations

from app.vision.roi.zones import (
    RoiZone,
    apply_roi,
    load_roi_config,
    point_in_zones,
    zones_from_payload,
)

__all__ = ["RoiZone", "apply_roi", "load_roi_config",
    "point_in_zones", "zones_from_payload"]
