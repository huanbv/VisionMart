#!/usr/bin/env python
"""Chẩn đoán một khung hình: tiền xử lý đang giúp hay đang phá?

Vì sao cần công cụ riêng, dù đã có quality analyzer
--------------------------------------------------
``quality/analyzer.py`` đo TOÀN KHUNG HÌNH: độ sáng, tương phản, độ nét
trung bình. Đó là chỉ số đúng cho câu hỏi "khung này có dùng được không".

Nhưng nó trả lời SAI cho câu hỏi quan trọng hơn trong pipeline hai tầng:
*vùng ảnh mà classifier sẽ đọc còn chi tiết không?*

Hai câu này lệch nhau, và lệch theo hướng nguy hiểm. Khử nhiễu làm ảnh
mượt hơn, nhiễu giảm, điểm chất lượng toàn khung TĂNG — trong khi chính
nó vừa xoá mất kết cấu tần số cao trên nhãn sản phẩm, tức đúng thứ duy
nhất phân biệt Aquafina với Lavie. Chỉ nhìn điểm toàn khung, ta sẽ thấy
"ảnh tốt lên" đúng lúc mô hình mất khả năng nhận dạng.

Nên công cụ này đo riêng phần đó: cắt các ô nhỏ cỡ một sản phẩm trên kệ,
so kết cấu trước và sau tiền xử lý, rồi nói thẳng cái nào mất bao nhiêu.

Dùng
----
    python scripts/diagnose_frame.py anh.jpg
    python scripts/diagnose_frame.py anh.jpg --patch-size 48
"""

from __future__ import annotations

import argparse
import os
import sys

# Ngưỡng mất kết cấu coi là nghiêm trọng. 15% là mức mà thử nghiệm nội bộ
# cho thấy chữ nhỏ trên nhãn bắt đầu không đọc được; dưới mức đó thường
# vẫn còn đủ nét cạnh để phân loại.
TEXTURE_LOSS_WARN = 0.15
TEXTURE_LOSS_SEVERE = 0.30


def patch_texture(gray, patch_size: int) -> list[float]:
    """Độ 'gồ ghề' của từng ô nhỏ — đại diện cho kết cấu nhãn sản phẩm.

    Chia lưới thay vì đo toàn ảnh, vì trung bình toàn khung bị các mảng
    lớn trơn (sàn nhà, tường, trần) kéo xuống và che mất đúng vùng có
    thông tin. Một cửa hàng có nửa khung là sàn gạch thì chỉ số toàn khung
    nói nhiều về cái sàn hơn là về sản phẩm.
    """
    import cv2

    h, w = gray.shape[:2]
    values: list[float] = []
    for y in range(0, h - patch_size + 1, patch_size):
        for x in range(0, w - patch_size + 1, patch_size):
            patch = gray[y : y + patch_size, x : x + patch_size]
            values.append(float(cv2.Laplacian(patch, cv2.CV_64F).var()))
    return values


def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    n = len(ordered)
    return {
        "n": n,
        "trung_vi": ordered[n // 2],
        # Phân vị 90 là chỉ số quan trọng nhất ở đây: nó đại diện cho
        # những ô GIÀU chi tiết nhất — tức các kệ hàng — chứ không phải
        # mặt sàn trống. Đó chính là vùng classifier sẽ làm việc.
        "p90": ordered[int(n * 0.9)],
        "p10": ordered[int(n * 0.1)],
    }


# Các bước làm mượt, kèm mức xoá kết cấu đo trên ảnh mô phỏng kệ hàng.
# Xếp theo mức phá hoại giảm dần, vì đó là thứ tự nên tắt.
_SMOOTHERS = (
    ("enable_gaussian_blur", "Gaussian blur", "xoá ~99% kết cấu nhãn"),
    ("enable_median_blur", "Median blur", "xoá ~97% kết cấu nhãn"),
    ("enable_adaptive_median", "Adaptive median", "cùng họ median"),
    ("enable_bilateral", "Bilateral", "xoá ~29% — nhẹ nhất trong nhóm"),
)


def report_config_only(cfg) -> int:
    """Báo cáo cấu hình khi không có ảnh.

    Tách riêng vì đây là câu hỏi hay gặp nhất và không cần dữ liệu gì
    thêm: người vận hành thấy ảnh bết thì việc đầu tiên cần biết là bước
    nào đang chạy, chứ không phải đi tìm cho ra một tấm ảnh mẫu.
    """
    print("=" * 70)
    print("CẤU HÌNH TIỀN XỬ LÝ ĐANG ÁP DỤNG")
    print("=" * 70)

    on = [n for n in dir(cfg) if n.startswith("enable_") and getattr(cfg, n, False) is True]
    if not on:
        print("\nKhông có bước tiền xử lý nào bật — YOLO nhận đúng ảnh gốc.")
        print("Nếu khung hình vẫn bết thì nguyên nhân nằm ở camera hoặc")
        print("bitrate luồng, không phải ở pipeline.")
        print("=" * 70)
        return 0

    print(f"\nĐang bật ({len(on)}):")
    for name in sorted(on):
        print(f"  - {name}")

    active = [(n, label, note) for n, label, note in _SMOOTHERS if getattr(cfg, n, False)]
    print()
    if active:
        print("!" * 70)
        print("CẢNH BÁO: có bước LÀM MƯỢT đang bật")
        print("!" * 70)
        for name, label, note in active:
            print(f"  {label:18} ({name})")
            print(f"      {note}")
        print("\n  Kết cấu tần số cao trên nhãn là thứ DUY NHẤT phân biệt hai")
        print("  chai cùng hình dáng khác thương hiệu. Xoá nó đi thì tầng phân")
        print("  loại không còn gì để đọc, dù ảnh trông 'sạch' hơn.")
        print("\n  Thêm nữa: YOLO được huấn luyện trên ảnh SẮC NÉT. Đưa cho nó")
        print("  ảnh đã làm mượt là đưa thứ khác với những gì nó đã học.")
        print("\n  → Tắt tại Admin → Cấu hình xử lý ảnh (có hiệu lực ngay).")
    else:
        print("Không có bước làm mượt nào bật — tốt cho tầng phân loại.")

    print("=" * 70)
    print("\nĐo cụ thể trên một khung hình:")
    print("  python scripts/diagnose_frame.py --rtsp rtsp://<camera>")
    print("  python scripts/diagnose_frame.py anh.jpg --save /tmp/ss")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", nargs="?", default=None,
                        help="Ảnh cần chẩn đoán. Bỏ trống thì chỉ báo cáo cấu hình.")
    parser.add_argument("--rtsp", default=None,
                        help="Lấy một khung trực tiếp từ luồng RTSP thay vì đọc file")
    parser.add_argument("--patch-size", type=int, default=32,
                        help="Cạnh ô lưới, xấp xỉ kích thước một sản phẩm trên kệ")
    parser.add_argument("--save", default=None,
                        help="Ghi ảnh trước/sau ra thư mục này để xem bằng mắt")
    args = parser.parse_args()

    import cv2

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.vision.config import get_vision_config
    from app.vision.enhancement.enhance import enhance_frame

    original = None
    if args.rtsp:
        cap = cv2.VideoCapture(args.rtsp)
        try:
            ok, original = cap.read()
        finally:
            cap.release()
        if not ok or original is None:
            print(f"Không đọc được khung hình từ {args.rtsp}")
            return 2
    elif args.image:
        if not os.path.isfile(args.image):
            print(f"Không thấy file: {args.image}")
            print("\nGợi ý: bỏ trống tham số để chỉ xem cấu hình đang bật,")
            print("hoặc dùng --rtsp rtsp://... để lấy khung trực tiếp từ camera.")
            return 2
        original = cv2.imread(args.image)
        if original is None:
            print("Không đọc được ảnh.")
            return 2

    # Không có ảnh vẫn báo cáo cấu hình được — và đó thường là câu hỏi đầu
    # tiên cần trả lời ("cờ nào đang bật?"), nên không bắt người dùng phải
    # kiếm cho ra một tấm ảnh mới xem được.
    if original is None:
        cfg = get_vision_config()
        return report_config_only(cfg)

    h, w = original.shape[:2]
    cfg = get_vision_config()

    print("=" * 70)
    print("CHẨN ĐOÁN KHUNG HÌNH")
    print("=" * 70)
    print(f"Kích thước: {w}x{h}")

    flags = [name for name in dir(cfg)
             if name.startswith("enable_") and getattr(cfg, name, False) is True]
    print(f"\nCờ đang BẬT: {', '.join(flags) if flags else 'không có cờ nào'}")

    smoothers = [f for f in flags if f in
                 ("enable_gaussian_blur", "enable_median_blur",
                  "enable_bilateral", "enable_adaptive_median")]

    processed = enhance_frame(original.copy(), cfg)
    if isinstance(processed, tuple):
        processed = processed[0]

    g_before = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    g_after = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)

    before = summarize(patch_texture(g_before, args.patch_size))
    after = summarize(patch_texture(g_after, args.patch_size))

    print(f"\n--- Kết cấu theo ô {args.patch_size}x{args.patch_size} "
          f"({before['n']} ô) ---")
    print(f"{'':12}{'trước':>12}{'sau':>12}{'thay đổi':>12}")
    for key, label in (("p90", "ô giàu chi tiết"), ("trung_vi", "trung vị"),
                       ("p10", "ô trống")):
        b, a = before[key], after[key]
        delta = (a - b) / b if b > 1e-9 else 0.0
        print(f"{label:12}{b:>12.1f}{a:>12.1f}{delta:>+11.1%}")

    b90, a90 = before["p90"], after["p90"]
    loss = (b90 - a90) / b90 if b90 > 1e-9 else 0.0

    print("\n" + "=" * 70)
    if not flags:
        print("KẾT LUẬN: không có tiền xử lý nào bật — YOLO nhận đúng ảnh gốc.")
        print("  Nếu ảnh vẫn mờ/nhoè thì nguồn nằm ở CAMERA hoặc khâu nén,")
        print("  không phải ở pipeline. Kiểm tra độ phân giải và bitrate luồng.")
    elif loss >= TEXTURE_LOSS_SEVERE:
        print(f"KẾT LUẬN: MẤT {loss:.0%} KẾT CẤU ở vùng giàu chi tiết — NGHIÊM TRỌNG")
        print(f"  Thủ phạm nhiều khả năng: {', '.join(smoothers) or 'các bước làm mượt'}")
        print("  Đây là kết cấu nhãn sản phẩm — thứ duy nhất phân biệt được")
        print("  hai chai cùng hình dáng khác thương hiệu. Mất nó thì tầng")
        print("  phân loại không còn gì để đọc, dù ảnh trông 'sạch' hơn.")
        print("  → Tắt các bước làm mượt, đo lại.")
    elif loss >= TEXTURE_LOSS_WARN:
        print(f"KẾT LUẬN: mất {loss:.0%} kết cấu — CẦN THEO DÕI")
        print("  Chưa nguy hiểm nhưng đủ để làm giảm độ chính xác phân loại.")
        print("  → Chạy A/B trước khi giữ cấu hình này:")
        print("     python -m evaluation.cli preprocessing-ab --database-url ...")
    elif loss <= -0.05:
        print(f"KẾT LUẬN: kết cấu TĂNG {-loss:.0%} — có thể có lợi")
        print("  Nhưng ĐỪNG bật trên production chỉ vì con số này: mô hình")
        print("  hiện được huấn luyện trên ảnh CHƯA tiền xử lý, nên sắc nét")
        print("  hơn vẫn có thể khiến nó nhận kém đi do lệch phân phối.")
        print("  → Phải đo A/B trên nhãn thật mới kết luận được.")
    else:
        print(f"KẾT LUẬN: kết cấu gần như không đổi ({loss:+.0%})")
        print("  Tiền xử lý đang tốn CPU mà chưa đổi lấy gì rõ rệt.")
    print("=" * 70)

    # Kích thước vật thể là ràng buộc cứng, độc lập với mọi cấu hình.
    from app.vision.config import get_vision_config as _cfg
    min_size = getattr(_cfg(), "crop_min_size", 24)
    print(f"\nLƯU Ý VỀ KÍCH THƯỚC VẬT THỂ")
    print(f"  Ngưỡng crop tối thiểu hiện tại: {min_size}px")
    print(f"  Ở góc camera bao quát cả cửa hàng, một sản phẩm trên kệ xa")
    print(f"  thường chỉ 15-30px. Crop nhỏ hơn {min_size}px sẽ bị loại — đúng,")
    print(f"  vì phóng to một ô 12x8 chỉ tạo ra phán đoán tự tin mà sai.")
    print(f"  Không cấu hình nào cứu được điều này; cần camera gần hơn hoặc")
    print(f"  độ phân giải cao hơn cho vùng cần nhận SKU.")

    if args.save:
        os.makedirs(args.save, exist_ok=True)
        before_path = os.path.join(args.save, "truoc.jpg")
        after_path = os.path.join(args.save, "sau.jpg")
        # Chất lượng 95: nén mạnh sẽ tự tạo ra bết, và khi mục đích của
        # hai file này là để so bết thì đó là hỏng đúng thứ cần đo.
        cv2.imwrite(before_path, original, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        cv2.imwrite(after_path, processed, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        print(f"\nĐã ghi ảnh so sánh:\n  {before_path}\n  {after_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
