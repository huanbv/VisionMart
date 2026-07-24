#!/usr/bin/env python
"""Sinh dữ liệu huấn luyện detector bằng cách cắt-dán sản phẩm lên bối cảnh.

Bài toán
--------
Detector cần hộp bao CÓ TOẠ ĐỘ THẬT trên cảnh thật. COCO không có lớp nào
cho gói mì, nên phải tự huấn luyện; nhưng gán tay vài trăm khung hình mất
nhiều ngày, và ``trainer.py`` hiện chỉ sinh được nhãn phủ trọn khung
(``0.5 0.5 1.0 1.0``) — nhãn đó dạy mô hình "cả ảnh là sản phẩm X", tức
xoá sạch khả năng định vị, đúng thứ detector sinh ra để làm.

Cách giải
---------
Chụp từng sản phẩm trên NỀN TRƠN, tách nền tự động, rồi dán ngẫu nhiên lên
ảnh bối cảnh. Vì ta tự đặt sản phẩm vào đâu nên toạ độ hộp bao là thứ ta
BIẾT CHÍNH XÁC, không phải thứ phải đoán hay gán tay. Số lượng ảnh sinh ra
không giới hạn.

Kỹ thuật này có tên trong tài liệu: *Cut, Paste and Learn* (Dwibedi et al.,
ICCV 2017), và được dùng thật trong sản xuất khi thiếu dữ liệu gán nhãn.

Một lớp, không phải bốn
-----------------------
Mặc định sinh nhãn MỘT LỚP ``product``. Detector chỉ cần trả lời "chỗ này
có một món hàng"; việc phân biệt Hảo Hảo với Gấu Đỏ giao cho classifier,
nơi ảnh đã được cắt ra và phóng lên 224px thay vì đọc ở 40px. Chia việc
như vậy còn khiến thêm SKU mới chỉ phải train lại classifier, không đụng
tới detector.

Hạn chế phải biết trước
-----------------------
Ảnh dán trông "dán": viền không hoà với nền, bóng đổ không khớp, hướng
sáng có thể ngược. Mô hình học từ đây sẽ kém hơn mô hình học từ ảnh gán
tay trên cảnh thật. Nó dùng để KHỞI ĐỘNG khi chưa có gì, không phải để
thay thế dữ liệu thật — và nên được thay dần bằng khung hình camera đã
qua hàng đợi duyệt.

Cách dùng
---------
Sắp ảnh sản phẩm chụp trên nền trơn:

    products/
      hao-hao/    img1.jpg img2.jpg ...
      gau-do/     ...
      7up/        ...
      sting/      ...

Ảnh bối cảnh (chụp kệ/bàn TRỐNG, không có sản phẩm):

    backgrounds/  bg1.jpg bg2.jpg ...

Chạy:

    python scripts/synthesize_detector_data.py \\
        --products products --backgrounds backgrounds \\
        --out /app/training/detector --count 800
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("synth")

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def list_images(folder: str) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(IMG_EXT)
    )


def segment_on_plain_background(img, tolerance: int = 30):
    """Tách sản phẩm khỏi nền trơn, trả về mặt nạ.

    Màu nền suy ra từ VIỀN ẢNH chứ không giả định trắng: người dùng có thể
    chụp trên nền đen, xanh, hay tấm bìa xám, và ép một màu cố định sẽ
    hỏng lặng lẽ — cho ra mặt nạ rỗng mà không báo gì.

    Sau khi ngưỡng theo màu, ta giữ THÀNH PHẦN LIÊN THÔNG LỚN NHẤT. Đây là
    bước quan trọng: bóng đổ, vết bẩn trên nền, hay logo in trên tấm lót
    đều vượt ngưỡng màu và sẽ trở thành những mảnh rác nằm rải rác trong
    mặt nạ, kéo hộp bao rộng ra sai lệch.
    """
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    border = np.concatenate([
        img[0, :].reshape(-1, 3), img[h - 1, :].reshape(-1, 3),
        img[:, 0].reshape(-1, 3), img[:, w - 1].reshape(-1, 3),
    ])
    bg_color = np.median(border, axis=0)

    diff = np.abs(img.astype(np.int16) - bg_color.astype(np.int16)).sum(axis=2)
    mask = (diff > tolerance).astype(np.uint8) * 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    # Thứ tự ba bước dưới đây quan trọng, và làm sai thì hỏng lặng lẽ.
    #
    # OPEN trước để xoá đốm nhiễu lẻ. Rồi CHỌN THÀNH PHẦN LỚN NHẤT. Chỉ
    # sau đó mới CLOSE để lấp lỗ thủng bên trong vật thể.
    #
    # Bản đầu chạy CLOSE trước, và nó nối bóng đổ vào vật thể qua khe hở
    # vài pixel — sau đó lọc thành phần liên thông không cứu được nữa, vì
    # bóng đã trở thành một phần của cùng một khối. Đo được: hộp bao rộng
    # thêm 31px, tức mô hình được dạy rằng gói mì to hơn thực tế.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (labels == largest).astype(np.uint8) * 255

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Mặt nạ quá nhỏ nghĩa là tách hỏng — nền không đủ trơn, hoặc sản phẩm
    # trùng màu nền. Trả None để bỏ ảnh này còn hơn dán một mảnh vụn vào
    # tập huấn luyện và dạy mô hình một hộp bao sai.
    if mask.sum() / 255 < 0.02 * h * w:
        return None
    return mask


def paste(bg, obj, mask, x: int, y: int):
    """Dán obj lên bg tại (x, y), làm mềm viền.

    Làm mềm viền bằng blur trên mặt nạ, vì viền cắt sắc lẻm là dấu hiệu
    nhân tạo rõ nhất mà mạng học rất nhanh: nó sẽ học "vật thể = chỗ có
    viền sắc" thay vì học hình dáng sản phẩm, và trên camera thật không có
    viền nào như vậy nên mô hình trượt sạch.
    """
    import cv2
    import numpy as np

    oh, ow = obj.shape[:2]
    roi = bg[y : y + oh, x : x + ow]
    if roi.shape[:2] != (oh, ow):
        return
    alpha = cv2.GaussianBlur(mask, (5, 5), 0).astype(np.float32) / 255.0
    alpha = alpha[:, :, None]
    bg[y : y + oh, x : x + ow] = (obj * alpha + roi * (1 - alpha)).astype(np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--products", required=True, help="Thư mục cha, mỗi SKU một thư mục con")
    parser.add_argument("--backgrounds", required=True, help="Ảnh kệ/bàn TRỐNG")
    parser.add_argument("--out", default="/app/training/detector")
    parser.add_argument("--count", type=int, default=800, help="Số ảnh sinh ra")
    parser.add_argument("--min-objects", type=int, default=2)
    parser.add_argument("--max-objects", type=int, default=8)
    parser.add_argument("--val-split", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--per-class",
        action="store_true",
        help="Sinh nhãn nhiều lớp thay vì một lớp 'product'. KHÔNG khuyến nghị — "
             "xem phần đầu tài liệu: phân biệt thương hiệu là việc của classifier.",
    )
    parser.add_argument("--debug-masks", default=None, help="Ghi mặt nạ tách được ra đây để kiểm tra")
    args = parser.parse_args()

    import cv2
    import numpy as np

    random.seed(args.seed)
    np.random.seed(args.seed)

    # Kiểm tra hai thư mục đầu vào trước khi làm gì khác. Thiếu thư mục là
    # tình huống thường gặp nhất khi chạy lần đầu (/app/training là named
    # volume nên phải chép ảnh vào bằng `docker compose cp`), và một
    # traceback FileNotFoundError không nói được rằng cần chép ảnh vào đâu.
    for label, path in (("--products", args.products), ("--backgrounds", args.backgrounds)):
        if not os.path.isdir(path):
            logger.error("Không thấy thư mục %s: %s", label, path)
            logger.error(
                "Tạo và chép ảnh vào bằng:\n"
                "  docker compose exec ai-engine mkdir -p %s\n"
                "  docker compose cp <thư-mục-trên-máy-chủ>/. ai-engine:%s",
                path,
                path,
            )
            return 1

    classes = sorted(
        d for d in os.listdir(args.products)
        if os.path.isdir(os.path.join(args.products, d))
    )
    if not classes:
        logger.error("Không thấy thư mục SKU nào trong %s", args.products)
        return 1

    # Tách nền TRƯỚC vòng sinh ảnh: nếu tách hỏng thì phải biết ngay, chứ
    # không phải sau khi đã ghi xong 800 ảnh rác.
    logger.info("Tách nền các ảnh sản phẩm...")
    cutouts: list[tuple[int, str, object, object]] = []
    for idx, cls in enumerate(classes):
        files = list_images(os.path.join(args.products, cls))
        ok_count = 0
        for path in files:
            img = cv2.imread(path)
            if img is None:
                continue
            mask = segment_on_plain_background(img)
            if mask is None:
                logger.warning("  bỏ %s — không tách được khỏi nền", os.path.basename(path))
                continue
            ys, xs = np.where(mask > 0)
            y1, y2, x1, x2 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            cutouts.append((idx, cls, img[y1:y2, x1:x2].copy(), mask[y1:y2, x1:x2].copy()))
            ok_count += 1
            if args.debug_masks:
                os.makedirs(args.debug_masks, exist_ok=True)
                cv2.imwrite(
                    os.path.join(args.debug_masks, f"{cls}_{ok_count:03d}.png"),
                    cv2.bitwise_and(img, img, mask=mask),
                )
        logger.info("  %-16s %d/%d ảnh tách được", cls, ok_count, len(files))
        if ok_count == 0:
            logger.error(
                "    Không ảnh nào dùng được. Nền phải TRƠN và khác màu sản phẩm."
            )

    if not cutouts:
        logger.error("Không tách được ảnh nào. Chụp lại trên nền trơn (giấy trắng/bìa màu).")
        return 1

    backgrounds = list_images(args.backgrounds)
    if not backgrounds:
        logger.error("Không thấy ảnh bối cảnh trong %s", args.backgrounds)
        return 1
    logger.info("%d ảnh cắt, %d bối cảnh\n", len(cutouts), len(backgrounds))

    for split in ("train", "val"):
        os.makedirs(os.path.join(args.out, "images", split), exist_ok=True)
        os.makedirs(os.path.join(args.out, "labels", split), exist_ok=True)

    n_val = int(args.count * args.val_split)
    for i in range(args.count):
        split = "val" if i < n_val else "train"
        bg = cv2.imread(random.choice(backgrounds))
        if bg is None:
            continue
        bg = bg.copy()
        H, W = bg.shape[:2]

        lines: list[str] = []
        placed: list[tuple[int, int, int, int]] = []
        for _ in range(random.randint(args.min_objects, args.max_objects)):
            cls_idx, _cls_name, obj, mask = random.choice(cutouts)

            # Tỉ lệ ngẫu nhiên: sản phẩm ở kệ gần và kệ xa có kích thước
            # rất khác nhau, mô hình phải thấy cả dải đó lúc huấn luyện.
            target_h = random.randint(int(H * 0.06), int(H * 0.28))
            scale = target_h / obj.shape[0]
            nw, nh = max(8, int(obj.shape[1] * scale)), max(8, target_h)
            if nw >= W or nh >= H:
                continue
            o = cv2.resize(obj, (nw, nh), interpolation=cv2.INTER_AREA)
            m = cv2.resize(mask, (nw, nh), interpolation=cv2.INTER_NEAREST)

            if random.random() < 0.5:
                o, m = cv2.flip(o, 1), cv2.flip(m, 1)
            # Lệch sáng: camera thật có vùng sáng vùng tối, còn ảnh chụp
            # sản phẩm thường đủ sáng đều. Không thêm biến thiên này thì
            # mô hình chỉ nhận ra sản phẩm ở đúng mức sáng lúc chụp.
            o = np.clip(o.astype(np.float32) * random.uniform(0.65, 1.25), 0, 255).astype(np.uint8)

            x = random.randint(0, W - nw)
            y = random.randint(0, H - nh)

            # Không cho chồng lấn quá nhiều: hai hộp bao gần trùng nhau dạy
            # mô hình những mẫu mà NMS lúc suy luận sẽ gộp lại, tức dạy thứ
            # nó không thể tái tạo.
            if any(
                max(0, min(x + nw, px2) - max(x, px1)) * max(0, min(y + nh, py2) - max(y, py1))
                > 0.35 * nw * nh
                for px1, py1, px2, py2 in placed
            ):
                continue

            paste(bg, o, m, x, y)
            placed.append((x, y, x + nw, y + nh))
            label = cls_idx if args.per_class else 0
            lines.append(
                f"{label} {(x + nw / 2) / W:.6f} {(y + nh / 2) / H:.6f} "
                f"{nw / W:.6f} {nh / H:.6f}"
            )

        if not lines:
            continue
        stem = f"synth_{i:05d}"
        cv2.imwrite(os.path.join(args.out, "images", split, stem + ".jpg"), bg,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        with open(os.path.join(args.out, "labels", split, stem + ".txt"), "w") as fh:
            fh.write("\n".join(lines) + "\n")

    names = classes if args.per_class else ["product"]
    yaml_path = os.path.join(args.out, "data.yaml")
    with open(yaml_path, "w", encoding="utf-8") as fh:
        fh.write(f"path: {args.out}\ntrain: images/train\nval: images/val\n")
        fh.write(f"nc: {len(names)}\nnames: {json.dumps(names, ensure_ascii=False)}\n")

    logger.info("Xong. Dataset: %s", args.out)
    logger.info("Số lớp: %d (%s)", len(names), ", ".join(names))
    logger.info("\nHuấn luyện:")
    logger.info("  yolo detect train data=%s model=yolov8n.pt epochs=80 imgsz=640", yaml_path)
    if not args.per_class:
        logger.info(
            "\nMột lớp 'product' là chủ ý: việc phân biệt thương hiệu do "
            "classifier làm trên ảnh đã cắt, nơi nhãn đọc được ở 224px "
            "thay vì 40px."
        )
    logger.info(
        "\nLƯU Ý: đây là dữ liệu TỔNG HỢP để khởi động. Ảnh dán trông 'dán', "
        "nên mô hình sẽ kém hơn khi gặp cảnh thật. Thay dần bằng khung hình "
        "camera đã qua hàng đợi duyệt."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
