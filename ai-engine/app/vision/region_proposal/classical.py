"""Đề xuất vùng có vật thể bằng xử lý ảnh cổ điển (contour), KHÔNG học sâu.

Vì sao có module này
--------------------
Detector COCO (yolov8n) không có lớp nào cho gói mì, nên nó không bao giờ
khoanh gói mì để bộ phân loại SKU nhìn thấy — đây chính là "sản phẩm để
trên bàn AI không nhận diện được" mà người dùng báo. Trong khi chờ dữ
liệu cắt-dán để train detector nhận ra gói mì, module này lấp tạm khoảng
trống: đề xuất vùng ứng viên bằng contour rồi để bộ phân loại thử.

Kế thừa từ bài tập xử lý ảnh của người dùng (HSV -> ngưỡng -> morphology
OPEN/CLOSE -> findContours -> bounding box), nhưng có ba thay đổi bắt buộc,
mỗi cái đều rút ra từ việc CHẠY THỬ chứ không đoán:

1. KHÔNG lọc riêng màu đỏ. Bài gốc lọc đỏ vì biển báo giao thông viền đỏ.
   Sản phẩm cửa hàng đủ màu nên lọc một màu sẽ trượt hết trừ gói mì.
2. KHÔNG ngưỡng saturation tuyệt đối. Đo thử cho thấy mặt bàn gỗ có
   saturation ~128 — cao hơn cả ngưỡng — nên "vật sặc sỡ nổi trên nền
   trung tính" là sai. Thay bằng: ƯỚC LƯỢNG MÀU NỀN (màu chiếm đa số trong
   ROI, chính là mặt quầy) rồi lấy vùng KHÁC nền quá ngưỡng. Đây đúng là
   cách segment_on_plain_background trong script cắt-dán đã kiểm chứng.
3. Giữ NHIỀU contour, không chỉ contour lớn nhất. Bài gốc chỉ cần một biển
   báo mỗi ảnh; ở đây một khung có thể có nhiều sản phẩm cạnh nhau.

Chỉ nên chạy BÊN TRONG vùng ROI đã vẽ, nơi nền đã bị che đen. Ngoài ROI —
kệ hàng phía sau, người qua lại — cách cổ điển này sinh rác. Người gọi
(person_tracker) chịu trách nhiệm chỉ bật khi có ROI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProposedRegion:
    x1: int
    y1: int
    x2: int
    y2: int
    # Điểm "tự tin" thô của đề xuất — dùng để xếp hạng và cắt bớt, KHÔNG phải
    # xác suất phân loại. Bộ phân loại SKU mới là thứ quyết định đây là gì.
    score: float


def propose_regions(
    frame_bgr,
    *,
    min_area_frac: float = 0.0008,
    max_area_frac: float = 0.25,
    max_regions: int = 8,
    bg_tolerance: int = 45,
    allow_local_fallback: bool = True,
) -> list[ProposedRegion]:
    """Trả về danh sách bbox ứng viên trong frame (đã được che ROI ở ngoài).

    frame_bgr: ndarray BGR, phần ngoài ROI đã là đen (0,0,0).

    min_area_frac / max_area_frac: lọc theo tỉ lệ diện tích khung. Quá nhỏ là
    nhiễu/nhãn giá; quá lớn thường là cả mặt bàn hoặc bóng người, không phải
    một sản phẩm.
    """
    import cv2
    import numpy as np

    h, w = frame_bgr.shape[:2]
    if h == 0 or w == 0:
        return []
    frame_area = float(h * w)

    # Chỉ xét các pixel không phải nền đen (tức là bên trong ROI). Nếu ROI
    # rỗng hoặc camera tối thì không có gì để đề xuất.
    nonblack = frame_bgr.reshape(-1, 3)
    nonblack = nonblack[nonblack.sum(axis=1) > 24]
    if nonblack.shape[0] < 0.02 * frame_area:
        return []

    # Màu nền = màu chiếm đa số trong ROI, chính là mặt quầy/bàn. Dùng median
    # (bền với ngoại lệ) thay vì mean: vài sản phẩm sáng màu không kéo lệch
    # được ước lượng nền như mean.
    bg_color = np.median(nonblack, axis=0)

    # Vùng vật thể = pixel (không đen) khác màu nền quá ngưỡng. Pixel đen
    # ngoài ROI có tổng gần 0 nên khác nền, phải loại riêng để không tính cả
    # nền đen thành "vật".
    diff = np.abs(frame_bgr.astype(np.int16) - bg_color.astype(np.int16)).sum(axis=2)
    is_inside_roi = frame_bgr.sum(axis=2) > 24
    color_mask = ((diff > bg_tolerance) & is_inside_roi).astype(np.uint8) * 255

    # Cạnh bắt thêm ranh giới vật ít khác màu nền (hộp cùng tông) mà ngưỡng
    # khác-nền bỏ sót. Chỉ lấy cạnh bên trong ROI.
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edges = cv2.bitwise_and(edges, edges, mask=is_inside_roi.astype(np.uint8))

    mask = cv2.bitwise_or(color_mask, edges)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    # Thứ tự y hệt segment_on_plain_background của script cắt-dán: OPEN trước
    # để bỏ đốm nhiễu, rồi CLOSE để nối các mảnh của cùng một vật và lấp lỗ.
    # Đảo thứ tự thì CLOSE nối bóng/khe vào vật trước khi OPEN kịp dọn.
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    def _regions_from_contours(items, *, reject_scene_spans: bool):
        found: list[ProposedRegion] = []
        for cnt in items:
            area = cv2.contourArea(cnt)
            frac = area / frame_area
            if frac < min_area_frac or frac > max_area_frac:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            # A contour spanning almost the complete ROI is the counter/floor
            # boundary, not a product. This commonly happens with perspective
            # camera views where the pay-zone contains several background
            # colours and the global median is not a valid background model.
            if reject_scene_spans and (bw >= 0.80 * w or bh >= 0.80 * h):
                continue
            # Loại dải quá dài/mảnh — thường là vệt cạnh của mép bàn hay khe ROI,
            # không phải một sản phẩm.
            aspect = max(bw, bh) / max(1, min(bw, bh))
            if aspect > 6.0:
                continue
            found.append(
                ProposedRegion(
                    x1=x, y1=y, x2=x + bw, y2=y + bh, score=float(frac)
                )
            )
        return found

    regions = _regions_from_contours(contours, reject_scene_spans=True)

    # A global median works for upload photos on a plain background. It fails
    # on a real checkout view containing wood, floor, shadows and perspective:
    # all surfaces merge into one large contour. If that happened, compare
    # each pixel with a heavily blurred local background instead. Bottles and
    # packs remain compact high-contrast islands while gradual lighting and
    # wood-colour changes disappear.
    if allow_local_fallback and not regions and contours:
        blur_size = max(15, min(51, (min(h, w) // 10) | 1))
        local_bg = cv2.GaussianBlur(frame_bgr, (blur_size, blur_size), 0)
        local_diff = np.abs(
            frame_bgr.astype(np.int16) - local_bg.astype(np.int16)
        ).sum(axis=2)
        local_threshold = max(55, bg_tolerance)
        # ``frame_bgr`` can also contain black person masks. Keep away from
        # every black/non-black boundary so Gaussian blur does not turn the
        # edge of a masked torso (or the ROI polygon) into a fake object.
        safe_inside = cv2.erode(
            is_inside_roi.astype(np.uint8),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
            iterations=1,
        ).astype(bool)
        local_mask = (
            (local_diff > local_threshold) & safe_inside
        ).astype(np.uint8) * 255
        local_mask = cv2.morphologyEx(
            local_mask, cv2.MORPH_OPEN, kernel, iterations=1
        )
        local_mask = cv2.morphologyEx(
            local_mask, cv2.MORPH_CLOSE, kernel, iterations=2
        )
        local_contours, _ = cv2.findContours(
            local_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        regions = _regions_from_contours(
            local_contours, reject_scene_spans=True
        )

    # Vật to (diện tích lớn) đứng trước: nếu phải cắt bớt vì vượt max_regions,
    # ưu tiên giữ những vật rõ ràng nhất thay vì đốm nhỏ.
    regions.sort(key=lambda r: r.score, reverse=True)
    return regions[:max_regions]
