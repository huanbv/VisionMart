"""Train a YOLOv8 model on a custom dataset.

Usage (inside ai-engine container or a Python 3.12 venv with ultralytics installed):

    python training/train.py --data /app/training/datasets/vm_v1/data.yaml \
        --epochs 100 --imgsz 640 --model yolov8n.pt --name vm_v1

The trained best weight ends up under runs/detect/<name>/weights/best.pt.
Copy it to /models/ so ai-engine can load it via YOLO_MODEL env.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Path to dataset yaml")
    parser.add_argument("--model", default="yolov8n.pt", help="Base weight")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default="cpu", help="cpu, 0, 0,1, ...")
    parser.add_argument("--name", default="vm_v1")
    parser.add_argument(
        "--publish-to",
        default="/models",
        help="If the directory exists, copy best.pt there after training",
    )
    args = parser.parse_args()

    model = YOLO(args.model)
    results = model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        name=args.name,
    )
    best = Path(results.save_dir) / "weights" / "best.pt"
    print(f"[train] best weight: {best}")

    publish = Path(args.publish_to)
    if publish.is_dir():
        target = publish / f"{args.name}.pt"
        shutil.copy2(best, target)
        print(f"[train] published to: {target}")


if __name__ == "__main__":
    main()
