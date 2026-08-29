# ADR-008 — YOLOv8 as the default object detector

- **Status:** Accepted
- **Date:** 2026-06-30
- **Supersedes:** —
- **Superseded by:** —

## Context

Every higher-level vision feature in VisionMart — person counting, queue
detection, smart cart, theft detection, heatmap — depends on a reliable
per-frame object detector. The detector must:

- Run in real time (≥ 15 FPS) on each camera, on the hardware customers can
  afford (mid-range CPU, consumer GPU, or edge accelerators).
- Be trainable on per-tenant product datasets.
- Have a healthy ecosystem (pretrained weights, fine-tuning tools, model
  zoo).
- Export cleanly to ONNX / TensorRT for production inference (paired with
  ADR-009, ADR-015).

## Decision

Adopt **YOLOv8** (Ultralytics) as the default object-detection model.

- COCO-pretrained checkpoints are used out of the box for person and generic
  object detection.
- Per-tenant **product recognition** uses fine-tuned YOLOv8 variants
  registered through the model registry (story `VM-AI-PROD-01`).
- We standardise on **ONNX Runtime** for production inference, with optional
  TensorRT backend on NVIDIA hardware.
- The detector is hot-swappable via configuration so we can adopt newer
  YOLO generations (or alternative architectures) without code changes.

## Consequences

**Positive**

- Strong baseline accuracy with minimal effort.
- Active community, frequent releases, abundant tutorials.
- Built-in training, validation, and export tooling shortens our R&D loop.
- ONNX export gives us a hardware-portability story (CPU, CUDA, TensorRT,
  even some edge NPUs).

**Negative**

- Ultralytics' **AGPL-3.0** license requires care: any modification we ship
  must be source-available. We will *use* the framework as-is and keep
  application code separate; revisit if we ever modify the library itself.
- Tight coupling to the Ultralytics release cadence; we pin versions and
  re-evaluate on each minor bump.

**Neutral**

- The model-registry abstraction (ADR-014 + story `VM-AI-CORE-06`) lets us
  swap to RT-DETR, YOLO-NAS, or DETR-style models if benchmarks justify it.

## Alternatives Considered

- **YOLOv5 / YOLOv7** — Older; weaker out-of-the-box accuracy. Rejected.
- **Detectron2 / Mask R-CNN** — Higher accuracy ceiling, much heavier
  inference cost. Not suitable for per-camera real-time. Rejected as default;
  may be used for offline analytics.
- **RT-DETR** — Promising real-time transformer detector. Tracked as a
  potential replacement once tooling and benchmarks stabilise.
- **A managed Vision API (AWS Rekognition, GCP Vision)** — Conflicts with
  the on-premise deployment requirement and tenant data-sovereignty needs.
  Rejected.
