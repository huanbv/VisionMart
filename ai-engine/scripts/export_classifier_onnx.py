#!/usr/bin/env python
"""Xuất checkpoint classifier đã huấn luyện sang ONNX.

Tách khỏi train_classifier.py vì hai việc này hỏng vì lý do khác nhau và
tốn kém khác nhau. Huấn luyện mất nhiều phút; xuất mất một giây. Khi bước
xuất thất bại (thiếu gói, sai phiên bản opset), bắt người dùng huấn luyện
lại từ đầu là lãng phí thuần tuý — checkpoint torch đã nằm sẵn trên đĩa
và không có gì thay đổi.

Dùng:
    python scripts/export_classifier_onnx.py --checkpoint /models/sku_classifier.pt
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("export-onnx")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--checkpoint", default="/models/sku_classifier.pt")
    p.add_argument("--out", default=None, help="Mặc định: cùng thư mục, đuôi .onnx")
    p.add_argument("--opset", type=int, default=13)
    args = p.parse_args()

    try:
        import torch
        import torch.nn as nn
        from torchvision import models
    except ImportError:
        logger.error("Thiếu torch/torchvision.")
        return 2
    try:
        import onnx  # noqa: F401
    except ImportError:
        logger.error("Thiếu gói `onnx` (khác `onnxruntime`).")
        logger.error("  pip install onnx")
        logger.error("Hoặc dùng backend torch thay thế:")
        logger.error("  CLASSIFIER_BACKEND=torch")
        logger.error("  CLASSIFIER_MODEL_PATH=%s", args.checkpoint)
        return 2

    if not os.path.isfile(args.checkpoint):
        logger.error("Không thấy checkpoint: %s", args.checkpoint)
        return 2

    ckpt = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    classes = ckpt["classes"]
    size = ckpt.get("image_size", 224)

    model = models.mobilenet_v3_small()
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()

    out = args.out or os.path.splitext(args.checkpoint)[0] + ".onnx"
    torch.onnx.export(
        model, torch.randn(1, 3, size, size), out,
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=args.opset, dynamo=False,
    )
    logger.info("ONNX: %s (%d lớp, %dpx)", out, len(classes), size)

    labels = os.path.join(os.path.dirname(out), "sku_labels.json")
    if not os.path.isfile(labels):
        with open(labels, "w", encoding="utf-8") as fh:
            json.dump(classes, fh, ensure_ascii=False, indent=2)
        logger.info("Nhãn: %s", labels)

    # Kiểm tra ngay bằng chính runtime sẽ phục vụ, chứ không tin file đã
    # ghi ra là dùng được: sai opset hay trục động lỗi chỉ lộ ra lúc nạp.
    try:
        import numpy as np
        import onnxruntime as ort

        sess = ort.InferenceSession(out, providers=["CPUExecutionProvider"])
        y = sess.run(None, {"input": np.random.randn(2, 3, size, size).astype(np.float32)})[0]
        assert y.shape == (2, len(classes)), f"Hình dạng sai: {y.shape}"
        logger.info("Kiểm tra nạp: OK — batch 2 trả về %s", y.shape)
    except Exception:
        logger.exception("File đã ghi nhưng KHÔNG nạp được")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
