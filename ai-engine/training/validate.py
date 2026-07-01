"""Quick validation of a trained weight against a folder of test images."""

from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help="Path to trained .pt")
    parser.add_argument("--source", required=True, help="Folder of test images")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()

    model = YOLO(args.model)
    results = model.predict(
        source=args.source, conf=args.conf, imgsz=args.imgsz, save=True
    )
    for r in results:
        img = Path(r.path).name
        detections = [
            f"{r.names[int(b.cls[0])]}({float(b.conf[0]):.2f})"
            for b in r.boxes
        ]
        print(f"{img}: {detections or 'no detections'}")


if __name__ == "__main__":
    main()
