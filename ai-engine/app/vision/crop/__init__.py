"""Object cropping — turns YOLO boxes into per-object images."""

from app.vision.crop.cropper import CropResult, crop_detection, crop_detections

__all__ = ["CropResult", "crop_detection", "crop_detections"]
