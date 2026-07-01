"""Training worker for the AI Engine.

Runs YOLOv8 fine-tuning in a background thread. Each training run:

1. Downloads all training images from MinIO into a scratch directory.
2. Writes a YOLO dataset (images/, labels/, data.yaml) with auto-generated
   full-image bounding boxes — one class per uploaded-product bucket.
3. Trains a YOLOv8 detection model on top of the base weight.
4. Uploads the resulting ``best.pt`` back to MinIO under ``models/{job_id}.pt``.

The training progress is tracked in an in-memory registry that the API layer
polls via ``GET /ai/train/{job_id}``.
"""

from __future__ import annotations

import logging
import os
import random
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import yaml

from app.services import object_storage as storage
from app.services import product_mapper

logger = logging.getLogger("ai-engine.training")

_JOBS: dict[str, "JobState"] = {}
_LOCK = threading.Lock()

_TRAIN_ROOT = os.getenv("TRAINING_ROOT", "/app/training")


@dataclass
class JobState:
    job_id: str
    status: str = "pending"  # pending | running | succeeded | failed
    organization_id: str = ""
    branch_id: str | None = None
    class_map: dict[str, list[str]] = field(default_factory=dict)
    class_to_sku: dict[str, str] = field(default_factory=dict)
    epochs: int = 30
    image_size: int = 640
    started_at: float = 0.0
    finished_at: float = 0.0
    current_epoch: int = 0
    total_epochs: int = 0
    metrics: dict[str, Any] | None = None
    weight_key: str | None = None
    error: str | None = None
    progress: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "metrics": self.metrics,
            "weight_key": self.weight_key,
            "error": self.error,
            "progress": self.progress,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "current_epoch": self.current_epoch,
            "total_epochs": self.total_epochs,
        }


def get_state(job_id: str) -> JobState | None:
    with _LOCK:
        return _JOBS.get(job_id)


def start(
    *,
    job_id: str,
    organization_id: str,
    branch_id: str | None,
    class_map: dict[str, list[str]],
    class_to_sku: dict[str, str],
    epochs: int,
    image_size: int,
) -> JobState:
    with _LOCK:
        if job_id in _JOBS and _JOBS[job_id].status in {"pending", "running"}:
            return _JOBS[job_id]
        state = JobState(
            job_id=job_id,
            organization_id=organization_id,
            branch_id=branch_id,
            class_map=class_map,
            class_to_sku=class_to_sku,
            epochs=epochs,
            image_size=image_size,
        )
        _JOBS[job_id] = state
    thread = threading.Thread(
        target=_run, args=(state,), name=f"train-{job_id}", daemon=True
    )
    thread.start()
    return state


def _run(state: JobState) -> None:
    state.status = "running"
    state.started_at = time.time()
    workdir = os.path.join(_TRAIN_ROOT, state.job_id)
    try:
        _prepare_dataset(state, workdir)
        state.progress = "training"
        best_pt = _train_yolo(state, workdir)
        state.progress = "uploading"
        weight_key = f"models/{state.job_id}.pt"
        storage.upload(weight_key, best_pt, content_type="application/octet-stream")
        state.weight_key = weight_key
        _update_sku_mapping(state)
        state.status = "succeeded"
        state.progress = "done"
    except Exception as exc:  # noqa: BLE001
        logger.exception("training job %s failed", state.job_id)
        state.status = "failed"
        state.error = str(exc)
    finally:
        state.finished_at = time.time()
        _cleanup(workdir)


def _prepare_dataset(state: JobState, workdir: str) -> None:
    state.progress = "downloading images"
    if os.path.isdir(workdir):
        shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)

    class_names = sorted(state.class_map.keys())
    images_train = os.path.join(workdir, "images", "train")
    images_val = os.path.join(workdir, "images", "val")
    labels_train = os.path.join(workdir, "labels", "train")
    labels_val = os.path.join(workdir, "labels", "val")
    for d in (images_train, images_val, labels_train, labels_val):
        os.makedirs(d, exist_ok=True)

    rng = random.Random(42)
    total_train = 0
    total_val = 0

    for class_index, class_name in enumerate(class_names):
        keys = list(state.class_map[class_name])
        rng.shuffle(keys)
        raw_dir = os.path.join(workdir, "raw", class_name)
        os.makedirs(raw_dir, exist_ok=True)
        local_paths = storage.download_many(keys, raw_dir)
        if not local_paths:
            raise RuntimeError(f"No images downloaded for class {class_name}")

        split = max(1, int(len(local_paths) * 0.8))
        train_files = local_paths[:split]
        val_files = local_paths[split:] or local_paths[-1:]

        for path in train_files:
            _place(path, class_index, class_name, images_train, labels_train)
        for path in val_files:
            _place(path, class_index, class_name, images_val, labels_val)
        total_train += len(train_files)
        total_val += len(val_files)

    yaml_path = os.path.join(workdir, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {
                "path": workdir,
                "train": "images/train",
                "val": "images/val",
                "nc": len(class_names),
                "names": class_names,
            },
            f,
            sort_keys=False,
        )

    state.progress = (
        f"dataset ready: {total_train} train / {total_val} val, "
        f"{len(class_names)} classes"
    )


def _place(
    src_path: str,
    class_index: int,
    class_name: str,
    images_dir: str,
    labels_dir: str,
) -> None:
    base = f"{class_name}_{os.path.basename(src_path)}"
    stem, _ = os.path.splitext(base)
    dst_image = os.path.join(images_dir, base)
    shutil.copyfile(src_path, dst_image)
    label_path = os.path.join(labels_dir, f"{stem}.txt")
    with open(label_path, "w", encoding="utf-8") as f:
        # Full-image bbox in YOLO format (cx cy w h) — normalised.
        f.write(f"{class_index} 0.5 0.5 1.0 1.0\n")


def _train_yolo(state: JobState, workdir: str) -> str:
    from ultralytics import YOLO

    base_weight = os.getenv("TRAINING_BASE_MODEL", "yolov8n.pt")
    device = os.getenv("YOLO_DEVICE", "cpu")
    project = os.path.join(workdir, "runs")
    name = "run"

    model = YOLO(base_weight)
    state.total_epochs = state.epochs
    state.current_epoch = 0

    def _on_epoch_end(trainer: Any) -> None:
        try:
            state.current_epoch = int(getattr(trainer, "epoch", state.current_epoch) or 0) + 1
        except Exception:  # noqa: BLE001
            pass

    try:
        model.add_callback("on_train_epoch_end", _on_epoch_end)
    except Exception:  # noqa: BLE001
        pass
    results = model.train(
        data=os.path.join(workdir, "data.yaml"),
        epochs=state.epochs,
        imgsz=state.image_size,
        batch=int(os.getenv("TRAINING_BATCH", "8")),
        device=device,
        project=project,
        name=name,
        exist_ok=True,
        verbose=False,
    )
    try:
        metrics = results.results_dict if hasattr(results, "results_dict") else {}
        state.metrics = {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))}
    except Exception:  # noqa: BLE001
        state.metrics = None

    best_pt = os.path.join(project, name, "weights", "best.pt")
    if not os.path.isfile(best_pt):
        raise RuntimeError("training finished but best.pt not found")
    return best_pt


def _update_sku_mapping(state: JobState) -> None:
    """Merge the new class->SKU pairs into ``class_to_sku.json``."""
    if not state.class_to_sku:
        return
    path = os.getenv("CLASS_TO_SKU_PATH", "/app/config/class_to_sku.json")
    data: dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            import json

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:  # noqa: BLE001
            logger.warning("could not read %s, starting fresh", path)
            data = {}

    org_key = str(state.organization_id)
    branch_key = str(state.branch_id) if state.branch_id else "_default"
    org_map = data.setdefault(org_key, {})
    if not isinstance(org_map, dict):
        org_map = {}
        data[org_key] = org_map
    branch_map = org_map.setdefault(branch_key, {})
    if not isinstance(branch_map, dict):
        branch_map = {}
        org_map[branch_key] = branch_map
    for class_name, sku in state.class_to_sku.items():
        branch_map[class_name] = sku

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    import json

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    # Force product_mapper to reload next call.
    product_mapper._CACHE["mtime"] = 0.0  # type: ignore[attr-defined]


def _cleanup(workdir: str) -> None:
    if os.getenv("TRAINING_KEEP_WORKDIR", "false").lower() == "true":
        return
    shutil.rmtree(workdir, ignore_errors=True)
