"""AUDIT (chỉ đọc) toàn bộ pipeline nhận diện AI — KHÔNG sửa gì.

Mục tiêu: xuất BẰNG CHỨNG cho từng bước để tìm bước ĐẦU TIÊN gây lỗi nhận
diện, đúng yêu cầu audit:

  1. YOLO đang load chính xác file nào (đường dẫn tuyệt đối + timestamp).
  2. Danh sách toàn bộ class trong model.
  3. Số lượng class.
  4. Với mỗi frame: ảnh gốc, ảnh sau preprocess, mọi bbox, confidence,
     class id, class name.
  5. Không detect được gì -> ghi rõ lý do.
  6. Detect sai (vd 'book') -> ghi rõ tầng nào sinh ra: YOLO / Classifier /
     OCR / Decision(mapper).
  7. Ghi toàn bộ vào audit.json.
  8. Kiểm tra có đang load nhầm COCO hay model cũ.
  9. Đường dẫn / file weight / timestamp file đang dùng.

Script này KHÔNG thay đổi hành vi pipeline: nó gọi lại chính các module
thật (person_tracker._get_model, preprocess_for_detection, get_classifier,
map_class_to_sku) và chỉ ĐỌC kết quả.

Chạy TRONG container ai-engine để đọc đúng biến môi trường và file weight
mà hệ thống thật đang dùng:

    docker compose exec ai-engine python scripts/audit_pipeline.py <ẢNH> \
        [--camera checkout-1] [--org <uuid>] [--branch <uuid>] \
        [--out /tmp/audit]

<ẢNH> là một khung hình chụp từ camera (jpg/png). Nếu không có sẵn, lưu một
snapshot từ luồng camera rồi truyền vào đây.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def _abs_weight_info(model: Any, raw_name: str) -> dict[str, Any]:
    """Lần ra file weight THẬT mà ultralytics đã nạp (không phải chuỗi env)."""
    candidates: list[str] = []
    for attr in ("ckpt_path", "pt_path"):
        val = getattr(model, attr, None)
        if val:
            candidates.append(str(val))
    inner = getattr(model, "model", None)
    for attr in ("pt_path", "yaml_file"):
        val = getattr(inner, attr, None)
        if val:
            candidates.append(str(val))
    candidates.append(raw_name)  # last resort: chuỗi truyền vào YOLO()

    resolved: str | None = None
    for c in candidates:
        p = Path(c)
        if p.exists():
            resolved = str(p.resolve())
            break
    if resolved is None:
        # ultralytics tự tải yolov8n.pt về CWD hoặc weights dir; thử tìm.
        for guess in (Path.cwd() / raw_name, Path("/app") / raw_name):
            if guess.exists():
                resolved = str(guess.resolve())
                break

    info: dict[str, Any] = {
        "env_YOLO_MODEL": os.getenv("YOLO_MODEL", "(unset -> mặc định yolov8n.pt)"),
        "raw_name_passed_to_YOLO": raw_name,
        "ckpt_candidates": candidates,
        "resolved_absolute_path": resolved,
    }
    if resolved and os.path.isfile(resolved):
        st = os.stat(resolved)
        info["file_exists"] = True
        info["file_size_bytes"] = st.st_size
        info["file_mtime_iso"] = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)
        )
    else:
        info["file_exists"] = False
    return info


def _classify_model_kind(names: dict[int, str]) -> dict[str, Any]:
    """COCO chuẩn? model 4-lớp tự train? hay khác?"""
    values = [str(v).lower() for v in names.values()]
    is_coco = len(names) == 80 and "person" in values and "bottle" in values
    looks_custom_detector = len(names) <= 20 and "person" not in values
    verdict = (
        "COCO_PRETRAINED (80 lớp, chung chung — 'book'/'bottle'/'cell phone'...)"
        if is_coco
        else "CUSTOM_DETECTOR (ít lớp, không có 'person' — weight tự train)"
        if looks_custom_detector
        else "KHÔNG RÕ / hỗn hợp"
    )
    return {
        "num_classes": len(names),
        "is_coco_80": is_coco,
        "looks_like_custom_detector": looks_custom_detector,
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="Đường dẫn ảnh khung hình cần audit")
    ap.add_argument("--camera", default="audit-cam")
    ap.add_argument("--org", default="00000000-0000-0000-0000-000000000000")
    ap.add_argument("--branch", default="00000000-0000-0000-0000-000000000000")
    ap.add_argument("--out", default="/tmp/audit")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    img_path = Path(args.image)
    if not img_path.is_file():
        print(f"[LỖI] Không thấy ảnh: {img_path}", file=sys.stderr)
        return 2
    image_bytes = img_path.read_bytes()

    import cv2
    import numpy as np

    from app.vision.config import get_vision_config
    from app.vision.pipeline import preprocess_for_detection
    from app.services import person_tracker
    from app.services.product_mapper import map_class_to_sku
    from app.vision.classify.classifier import get_classifier
    from app.vision.crop.cropper import crop_detection, is_degenerate_box

    cfg = get_vision_config()
    audit: dict[str, Any] = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # --- (8/9) Config & cờ bật/tắt đang thực sự có hiệu lực ---------------
    audit["config_flags"] = {
        "ENABLE_SKU_CLASSIFIER": cfg.enable_sku_classifier,
        "ENABLE_CLASSICAL_PROPOSALS": getattr(cfg, "enable_classical_proposals", None),
        "ENABLE_OCR_FALLBACK": getattr(cfg, "enable_ocr_fallback", None),
        "ENABLE_MULTIFRAME_VOTING": getattr(cfg, "enable_multiframe_voting", None),
        "classifier_min_confidence": getattr(cfg, "classifier_min_confidence", None),
        "classifier_model_path": getattr(cfg, "classifier_model_path", None),
        "classifier_labels_path": getattr(cfg, "classifier_labels_path", None),
        "classifier_backend": getattr(cfg, "classifier_backend", None),
        "YOLO_CONF_THRESHOLD": os.getenv("YOLO_CONF_THRESHOLD", "0.25"),
        "frame_min_confidence_default": 0.4,  # frame.py Form(0.4)
    }

    # --- (1/2/3/8/9) Model YOLO thật sự đang chạy ------------------------
    raw_name = os.getenv("YOLO_MODEL", "yolov8n.pt")
    model = person_tracker._get_model(args.camera)  # đúng model pipeline dùng
    names_raw = {}
    try:
        names_raw = dict(getattr(model, "names", {}) or {})
    except Exception:
        pass
    audit["yolo_model"] = _abs_weight_info(model, raw_name)
    audit["yolo_classes"] = {int(k): str(v) for k, v in names_raw.items()}
    audit["yolo_model_kind"] = _classify_model_kind(names_raw)

    # --- Classifier: có bật, có nạp được, nhãn gì -----------------------
    clf = get_classifier()
    clf_info: dict[str, Any] = {"enabled": cfg.enable_sku_classifier}
    if clf is None:
        clf_info["available"] = False
        clf_info["reason"] = "get_classifier() trả None — ENABLE_SKU_CLASSIFIER tắt"
    else:
        avail = clf.available
        clf_info["available"] = avail
        clf_info["model_path"] = clf.model_path
        clf_info["labels_path"] = clf.labels_path
        clf_info["backend"] = clf.backend
        if os.path.isfile(clf.model_path):
            st = os.stat(clf.model_path)
            clf_info["model_file_mtime_iso"] = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)
            )
            clf_info["model_file_size_bytes"] = st.st_size
        else:
            clf_info["model_file_exists"] = False
        if avail:
            clf_info["num_classes"] = clf.num_classes
            clf_info["labels"] = list(getattr(clf, "_labels", []))
        else:
            clf_info["reason"] = "bật nhưng KHÔNG nạp được weight/nhãn (xem log)"
    audit["classifier"] = clf_info

    # --- (4) Chạy detect thật trên frame, lưu ảnh gốc + ảnh preprocess ---
    cv2.imwrite(str(out_dir / "01_original.jpg"),
                cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR))

    vision_result = preprocess_for_detection(image_bytes, args.camera, cfg, roi_zones=None)
    frame_bgr = vision_result.frame
    cv2.imwrite(str(out_dir / "02_preprocessed.jpg"), frame_bgr)
    fh, fw = frame_bgr.shape[:2]
    audit["frame"] = {
        "original_saved": str(out_dir / "01_original.jpg"),
        "preprocessed_saved": str(out_dir / "02_preprocessed.jpg"),
        "preprocessed_size_wh": [int(fw), int(fh)],
    }

    # Chạy detector y như pipeline (model.track trên frame đã preprocess).
    results = model.track(source=frame_bgr, persist=True,
                          tracker="bytetrack.yaml", verbose=False)
    boxes_out: list[dict[str, Any]] = []
    first = results[0] if results else None
    names = (first.names if first is not None else {}) or names_raw

    raw_boxes = []
    if first is not None and first.boxes is not None:
        raw_boxes = list(first.boxes)

    # --- (5) Không detect được gì -> lý do -------------------------------
    if not raw_boxes:
        audit["detections"] = []
        audit["no_detection_reason"] = {
            "raw_box_count": 0,
            "khả_năng": [
                f"YOLO conf threshold ({os.getenv('YOLO_CONF_THRESHOLD','0.25')}) "
                "cao hơn confidence của mọi vật trong khung",
                "Vật trong khung không thuộc lớp nào của model (nếu là model "
                "4-lớp tự train thì mọi vật lạ đều bị bỏ)",
                "ROI cắt mất vùng có sản phẩm (kiểm tra 02_preprocessed.jpg)",
            ],
        }

    clf_min = float(getattr(cfg, "classifier_min_confidence", 0.55))
    frame_min = 0.4  # frame.py Form default

    for box in raw_boxes:
        cls_idx = int(box.cls[0]) if box.cls is not None else -1
        yolo_class = str(names.get(cls_idx, str(cls_idx)))
        yolo_conf = float(box.conf[0]) if box.conf is not None else 0.0
        xy = [float(v) for v in box.xyxy[0].tolist()]
        x1, y1, x2, y2 = xy

        rec: dict[str, Any] = {
            "class_id": cls_idx,
            "class_name_YOLO": yolo_class,
            "confidence_YOLO": round(yolo_conf, 4),
            "bbox_xyxy": [round(v, 1) for v in xy],
            "produced_by_stage": "YOLO(detector)",
            "passes_frame_min_conf": yolo_conf >= frame_min,
            "box_is_degenerate_full_frame": is_degenerate_box(x1, y1, x2, y2, fw, fh),
        }

        # (6) Tầng Classifier nói gì (nếu bật & nạp được)?
        if clf is not None and clf.available and yolo_class.lower() != "person":
            crop = crop_detection(frame_bgr, x1, y1, x2, y2)
            if crop is None:
                rec["classifier"] = {"result": None, "reason": "crop quá nhỏ/rỗng"}
            else:
                res = clf.classify(crop.image)
                if res is None:
                    rec["classifier"] = {"result": None, "reason": "classify trả None"}
                else:
                    rec["classifier"] = {
                        "sku": res.sku,
                        "confidence": round(res.confidence, 4),
                        "runner_up": res.runner_up_sku,
                        "passes_clf_min_conf": res.confidence >= clf_min,
                    }
        else:
            rec["classifier"] = {
                "result": None,
                "reason": ("classifier tắt/không nạp được -> nhãn cuối chỉ dựa "
                           "vào class YOLO + map_class_to_sku"),
            }

        # (6) Tầng Decision/Mapper: class YOLO -> SKU (đường fallback)
        mapped = map_class_to_sku(str(args.org), str(args.branch), yolo_class)
        rec["decision_mapper"] = {
            "map_class_to_sku(YOLO_class)": mapped,
            "note": ("Đây là đường dùng khi classifier tắt. Nếu class YOLO là "
                     "'book'/'bottle'... thì nhãn cuối đến từ COCO, KHÔNG phải "
                     "classifier."),
        }

        # Nhãn cuối cùng mà pipeline sẽ dùng (tái hiện logic frame.py:576-583)
        clf_block = rec.get("classifier", {})
        clf_sku = clf_block.get("sku") if clf_block.get("passes_clf_min_conf") else None
        if clf is not None and clf.available and clf_sku:
            rec["FINAL_label"] = {"sku": clf_sku, "source": "Classifier"}
        elif mapped:
            rec["FINAL_label"] = {"sku": mapped, "source": "Decision/Mapper(COCO class)"}
        else:
            rec["FINAL_label"] = {"sku": None, "source": "Không map được -> bỏ qua"}

        boxes_out.append(rec)

    if raw_boxes:
        audit["detections"] = boxes_out

    # --- (7) Ghi audit.json ---------------------------------------------
    out_json = out_dir / "audit.json"
    out_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    # In tóm tắt ra màn hình
    print("=" * 70)
    print("AUDIT PIPELINE AI — TÓM TẮT")
    print("=" * 70)
    print(f"[1] YOLO weight: {audit['yolo_model'].get('resolved_absolute_path')}")
    print(f"    mtime      : {audit['yolo_model'].get('file_mtime_iso')}")
    print(f"    env        : {audit['yolo_model'].get('env_YOLO_MODEL')}")
    print(f"[2/3] Số class : {audit['yolo_model_kind']['num_classes']}")
    print(f"      Loại     : {audit['yolo_model_kind']['verdict']}")
    print(f"[classifier] enabled={clf_info['enabled']} available="
          f"{clf_info.get('available')}")
    print(f"[detect] số box thô: {len(raw_boxes)}")
    for i, r in enumerate(boxes_out):
        print(f"   box{i}: YOLO='{r['class_name_YOLO']}' conf={r['confidence_YOLO']} "
              f"-> FINAL={r['FINAL_label']['sku']} ({r['FINAL_label']['source']})"
              + ("  [BOX TRÙM CẢ KHUNG!]" if r['box_is_degenerate_full_frame'] else ""))
    print("-" * 70)
    print(f"Đã ghi: {out_json}")
    print(f"Ảnh   : {out_dir/'01_original.jpg'} , {out_dir/'02_preprocessed.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
