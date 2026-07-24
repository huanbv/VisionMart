#!/usr/bin/env python
"""Huấn luyện classifier SKU (MobileNetV3) và xuất ONNX cho ai-engine.

Vị trí trong hệ thống
---------------------
Đây là tầng hai. Detector trả lời "chỗ này có một món hàng"; classifier
trả lời "món đó là SKU nào" trên ảnh đã được cắt ra và phóng lên 224px —
thay vì phải đọc nhãn ở 40px trong khung hình gốc.

Vì sao KHÔNG dùng đường huấn luyện YOLO có sẵn
----------------------------------------------
``app/services/trainer.py`` gán mọi ảnh nhãn ``0.5 0.5 1.0 1.0``, tức hộp
bao phủ trọn khung. Với detector, nhãn đó dạy "cả ảnh là sản phẩm X" và
xoá sạch khả năng định vị — triển khai lên sẽ làm hỏng cả việc phát hiện
người lẫn chai lọ mà mô hình COCO đang làm tốt.

Nhưng chính nhãn đó lại ĐÚNG cho classifier: một ảnh chụp riêng một sản
phẩm thì cả ảnh đúng là sản phẩm đó. Nên 30 ảnh/SKU đã tải lên là dữ liệu
tốt — chỉ cần đưa vào đúng mô hình.

Chuyển học, không huấn luyện từ đầu
-----------------------------------
Với vài chục ảnh mỗi lớp, huấn luyện từ đầu chắc chắn thất bại: mạng có
hàng triệu tham số còn dữ liệu thì không đủ để ràng buộc chúng, nên nó
ghi nhớ chứ không học. Ta lấy MobileNetV3 đã học trên ImageNet và chỉ dạy
lại lớp cuối. Backbone đã biết nhận cạnh, góc, hoa văn, chữ; việc còn lại
chỉ là ánh xạ những đặc trưng đó sang SKU của cửa hàng.

Tăng cường dữ liệu — chọn có chủ đích
-------------------------------------
Chỉ dùng những phép biến đổi phản ánh biến thiên CÓ THẬT giữa ảnh chụp và
ảnh camera. Xoay nhẹ, đổi sáng, đổi màu, cắt ngẫu nhiên: có thật. Lật dọc:
không — không ai bày gói mì lộn ngược, và dạy mô hình chấp nhận điều đó
chỉ làm nó dễ nhầm hơn.

Cách dùng
---------
    python scripts/train_classifier.py --data /app/training/classifier
    python scripts/train_classifier.py --data ... --epochs 30 --out /models
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("train-classifier")

# Dưới mức này thì kết quả không nói lên điều gì: mô hình có thể đạt độ
# chính xác cao trên tập kiểm tra vài ảnh chỉ nhờ may mắn.
MIN_IMAGES_PER_CLASS = 10
RECOMMENDED_PER_CLASS = 100


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", required=True, help="Thư mục ImageFolder: train/<SKU>/, val/<SKU>/")
    parser.add_argument("--out", default="/models")
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-onnx", action="store_true", help="Bỏ qua bước xuất ONNX")
    args = parser.parse_args()

    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader
        from torchvision import datasets, models, transforms
    except ImportError:
        logger.error("Thiếu torch/torchvision. Cài: pip install torch torchvision")
        return 2

    torch.manual_seed(args.seed)

    train_dir = os.path.join(args.data, "train")
    val_dir = os.path.join(args.data, "val")
    for d in (train_dir, val_dir):
        if not os.path.isdir(d):
            logger.error("Không thấy %s — chạy build_classifier_dataset.py trước.", d)
            return 2

    # Chuẩn hoá theo ImageNet vì backbone được huấn luyện với thống kê đó;
    # dùng số khác sẽ đưa đặc trưng ra ngoài dải mà backbone quen thuộc.
    normalize = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])

    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(args.image_size, scale=(0.7, 1.0)),
        # Lật ngang: có thật (sản phẩm quay trái hay phải đều gặp).
        # KHÔNG lật dọc: không ai bày gói mì lộn ngược.
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(12),
        # Dải màu/sáng rộng, vì đây là khác biệt lớn nhất giữa ảnh chụp
        # (đủ sáng, cân màu) và khung hình camera (ám đèn, thiếu sáng).
        transforms.ColorJitter(brightness=0.35, contrast=0.35, saturation=0.25, hue=0.03),
        transforms.ToTensor(),
        normalize,
    ])
    val_tf = transforms.Compose([
        transforms.Resize(int(args.image_size * 1.14)),
        transforms.CenterCrop(args.image_size),
        transforms.ToTensor(),
        normalize,
    ])

    train_ds = datasets.ImageFolder(train_dir, train_tf)
    val_ds = datasets.ImageFolder(val_dir, val_tf)
    classes = train_ds.classes

    if len(classes) < 2:
        logger.error("Cần ít nhất 2 lớp, hiện có %d.", len(classes))
        return 1

    logger.info("--- Dữ liệu ---")
    counts: dict[str, int] = {c: 0 for c in classes}
    for _, label in train_ds.samples:
        counts[classes[label]] += 1
    thin = []
    for cls in classes:
        note = ""
        if counts[cls] < MIN_IMAGES_PER_CLASS:
            note = "  QUÁ ÍT"
            thin.append(cls)
        elif counts[cls] < RECOMMENDED_PER_CLASS:
            note = f"  (mỏng, nên có {RECOMMENDED_PER_CLASS}+)"
        logger.info("  %-24s %4d ảnh%s", cls, counts[cls], note)
    if thin:
        logger.error("Các lớp %s có dưới %d ảnh — thu thập thêm.", thin, MIN_IMAGES_PER_CLASS)
        return 1

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Thiết bị: %s | %d lớp | %d train / %d val\n",
                device, len(classes), len(train_ds), len(val_ds))

    train_dl = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=2)
    val_dl = DataLoader(val_ds, batch_size=args.batch_size, num_workers=2)

    model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    # Đóng băng backbone: với vài chục ảnh mỗi lớp, cho toàn mạng học sẽ
    # phá hỏng đặc trưng ImageNet đã tốt sẵn, đổi lấy việc ghi nhớ đúng
    # những tấm ảnh này.
    for param in model.features.parameters():
        param.requires_grad = False
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, len(classes))
    model = model.to(device)

    # label_smoothing: mô hình huấn luyện trên ít dữ liệu hay trả 0.999 cho
    # mọi thứ, kể cả khi sai. Điều đó phá chuỗi confidence ở matcher và làm
    # hàng đợi duyệt vô dụng — nó xếp hạng theo độ KHÔNG chắc chắn, mà mô
    # hình lúc nào cũng "chắc chắn" thì không còn gì để xếp.
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    best_acc, best_state = 0.0, None
    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        for images, labels in train_dl:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * images.size(0)
        scheduler.step()

        model.eval()
        correct = 0
        per_class_ok: dict[int, int] = {}
        per_class_n: dict[int, int] = {}
        with torch.no_grad():
            for images, labels in val_dl:
                images, labels = images.to(device), labels.to(device)
                pred = model(images).argmax(1)
                correct += (pred == labels).sum().item()
                for lab, ok in zip(labels.tolist(), (pred == labels).tolist()):
                    per_class_n[lab] = per_class_n.get(lab, 0) + 1
                    per_class_ok[lab] = per_class_ok.get(lab, 0) + int(ok)

        acc = correct / max(len(val_ds), 1)
        logger.info("epoch %2d/%d  loss %.4f  val_acc %.3f%s",
                    epoch, args.epochs, total_loss / max(len(train_ds), 1), acc,
                    "  <- tốt nhất" if acc > best_acc else "")
        if acc > best_acc:
            best_acc = acc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    # Độ chính xác từng lớp, vì con số tổng che mất trường hợp nguy hiểm
    # nhất: mô hình đoán đúng lớp nhiều ảnh và trượt sạch lớp ít ảnh, mà
    # tổng vẫn trông đẹp.
    logger.info("\n--- Độ chính xác từng lớp (tập val) ---")
    for idx, cls in enumerate(classes):
        n = per_class_n.get(idx, 0)
        ok = per_class_ok.get(idx, 0)
        logger.info("  %-24s %3d/%-3d  %.0f%%", cls, ok, n, 100 * ok / n if n else 0)

    os.makedirs(args.out, exist_ok=True)
    labels_path = os.path.join(args.out, "sku_labels.json")
    with open(labels_path, "w", encoding="utf-8") as fh:
        json.dump(classes, fh, ensure_ascii=False, indent=2)
    # labels.json phải đi CÙNG model: inference trả về chỉ số, nên thứ tự
    # lệch giữa lúc train và lúc phục vụ sẽ khiến mọi dự đoán bị gán sai
    # tên mà không có lỗi nào được báo.
    logger.info("\nNhãn: %s", labels_path)

    torch_path = os.path.join(args.out, "sku_classifier.pt")
    torch.save({"state_dict": model.state_dict(), "classes": classes,
                "image_size": args.image_size, "arch": "mobilenet_v3_small"}, torch_path)
    logger.info("Checkpoint torch: %s", torch_path)

    if not args.no_onnx:
        onnx_path = os.path.join(args.out, "sku_classifier.onnx")
        try:
            model.eval().cpu()
            dummy = torch.randn(1, 3, args.image_size, args.image_size)
            torch.onnx.export(
                model, dummy, onnx_path,
                input_names=["input"], output_names=["logits"],
                # Trục batch động: ai-engine phân loại nhiều ảnh cắt cùng
                # lúc, mà model cố định batch=1 sẽ buộc phải chạy vòng lặp
                # từng ảnh và mất hết lợi ích của việc gộp lô.
                dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
                opset_version=13,
                dynamo=False,
            )
            logger.info("ONNX: %s", onnx_path)
        except Exception:
            logger.exception("Xuất ONNX thất bại — vẫn dùng được backend torch")
            logger.info("  Đặt CLASSIFIER_BACKEND=torch và CLASSIFIER_MODEL_PATH=%s", torch_path)

    logger.info("\n%s", "=" * 62)
    logger.info("Độ chính xác tốt nhất trên tập val: %.1f%%", 100 * best_acc)
    if best_acc < 0.7:
        logger.info("  THẤP. Nguyên nhân thường gặp: quá ít ảnh, hoặc các lớp")
        logger.info("  trông quá giống nhau ở kích thước này. Thu thập thêm.")
    logger.info("\nBật lên:")
    logger.info("  ENABLE_SKU_CLASSIFIER=true")
    logger.info("  CLASSIFIER_MODEL_PATH=%s/sku_classifier.onnx", args.out)
    logger.info("  CLASSIFIER_LABELS_PATH=%s", labels_path)
    logger.info("\nCẢNH BÁO: con số trên đo trên ẢNH CHỤP. Khung hình camera")
    logger.info("mờ hơn, tối hơn, xiên hơn — độ chính xác thực tế sẽ THẤP HƠN.")
    logger.info("Đo lại trên ảnh cắt từ camera trước khi tin.")
    logger.info("%s", "=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
