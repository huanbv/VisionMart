"""So sánh A/B tiền xử lý: bật có thực sự tốt hơn tắt không?

Vì sao cần công cụ riêng
------------------------
Bật CLAHE/gamma làm ảnh *trông* rõ hơn với mắt người. Nhưng mô hình không
nhìn bằng mắt người: nó được huấn luyện trên ảnh **chưa** qua tiền xử lý,
nên bật tiền xử lý chỉ ở lúc suy luận tạo ra lệch phân phối — đưa cho mô
hình thứ khác với những gì nó đã học. Kết quả có thể **tệ đi** dù ảnh đẹp
hơn.

Không có cách nào biết trước hướng nào đúng cho một cửa hàng cụ thể. Chỉ
có đo.

Nhãn lấy từ đâu
---------------
Đây là phần trước đây thiếu. Đo A/B cần *ground truth*, và bộ ảnh mẫu
tổng hợp thì vô nghĩa — nó không có ánh sáng, góc máy, hay sản phẩm của
cửa hàng này.

Nguồn nhãn đúng là ``ai_review_candidates`` đã được **người duyệt**: đó là
khung hình thật, từ camera thật, với nhãn con người xác nhận. Đúng thứ cần
để trả lời "tiền xử lý có giúp mô hình của tôi trên camera của tôi không".

Đọc kết quả thế nào
-------------------
Công cụ này **không** chỉ in ra con số rồi để người dùng tự diễn giải.
Một chênh lệch nhỏ trên mẫu nhỏ là nhiễu, không phải cải thiện — và đó là
cách phổ biến nhất để tự lừa mình khi làm A/B. Nên mỗi kịch bản đều kèm
một kết luận rõ ràng: NÊN BẬT / KHÔNG NÊN / CHƯA ĐỦ DỮ LIỆU.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("evaluation.preprocessing_ab")

# Dưới ngưỡng này, kết quả không đáng tin dù chênh lệch trông đẹp.
# 30 khung hình là mức tối thiểu tuyệt đối để nói bất cứ điều gì; 200+ mới
# đủ để phân biệt cải thiện vài phần trăm với dao động ngẫu nhiên.
MIN_FRAMES_FOR_VERDICT = 30
RECOMMENDED_FRAMES = 200

# Chênh lệch F1 nhỏ hơn mức này coi như không có khác biệt thực chất —
# tiền xử lý luôn tốn thêm CPU, nên "hoà" nghĩa là "không nên bật".
MIN_MEANINGFUL_F1_DELTA = 0.02


@dataclass
class ArmResult:
    """Kết quả một nhánh (tắt hoặc một cấu hình tiền xử lý)."""

    name: str
    env: dict[str, str] = field(default_factory=dict)
    frames: int = 0
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    avg_latency_ms: float = 0.0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class Comparison:
    baseline: ArmResult
    variant: ArmResult
    verdict: str = ""
    reason: str = ""

    @property
    def f1_delta(self) -> float:
        return self.variant.f1 - self.baseline.f1

    @property
    def latency_delta_ms(self) -> float:
        return self.variant.avg_latency_ms - self.baseline.avg_latency_ms


def margin_of_error(p: float, n: int, z: float = 1.96) -> float:
    """Biên sai số 95% của một tỉ lệ ước lượng từ n mẫu.

    Đây là thứ ngăn việc đọc nhầm nhiễu thành tín hiệu. Với n=50 và
    p=0.80, biên sai số là ±0.11 — nghĩa là chênh lệch F1 0.03 giữa hai
    nhánh **không nói lên điều gì**. Không có con số này thì mọi phép A/B
    trên mẫu nhỏ đều trông như có kết luận.
    """
    if n <= 0:
        return 1.0
    return z * math.sqrt(max(p * (1 - p), 0.0) / n)


def decide(comparison: Comparison) -> Comparison:
    """Kết luận có nên bật cấu hình này không.

    Thứ tự kiểm tra phản ánh mức độ nghiêm trọng: dữ liệu không đủ thì mọi
    so sánh đều vô nghĩa nên phải chặn trước; sau đó mới xét chênh lệch có
    vượt được nhiễu không; cuối cùng mới cân nhắc chi phí CPU.
    """
    base, var = comparison.baseline, comparison.variant
    n = min(base.frames, var.frames)

    if n < MIN_FRAMES_FOR_VERDICT:
        comparison.verdict = "CHƯA ĐỦ DỮ LIỆU"
        comparison.reason = (
            f"Chỉ có {n} khung hình có nhãn (cần tối thiểu "
            f"{MIN_FRAMES_FOR_VERDICT}, nên có {RECOMMENDED_FRAMES}+). "
            "Hãy duyệt thêm mẫu trong hàng đợi rồi đo lại."
        )
        return comparison

    delta = comparison.f1_delta
    moe = margin_of_error(base.f1, n) + margin_of_error(var.f1, n)

    if abs(delta) < moe:
        comparison.verdict = "KHÔNG NÊN BẬT"
        comparison.reason = (
            f"Chênh lệch F1 {delta:+.3f} nhỏ hơn biên sai số ±{moe:.3f} "
            f"trên {n} khung — không phân biệt được với dao động ngẫu "
            f"nhiên. Tiền xử lý tốn thêm {comparison.latency_delta_ms:+.1f}ms "
            "mà chưa chứng minh được lợi ích."
        )
        return comparison

    if delta < 0:
        comparison.verdict = "KHÔNG NÊN BẬT"
        comparison.reason = (
            f"F1 GIẢM {delta:+.3f} (từ {base.f1:.3f} xuống {var.f1:.3f}). "
            "Đây chính là lệch phân phối train/inference: mô hình được "
            "huấn luyện trên ảnh chưa tiền xử lý. Nếu vẫn muốn dùng cấu "
            "hình này, phải huấn luyện lại với CÙNG bước tiền xử lý."
        )
        return comparison

    if delta < MIN_MEANINGFUL_F1_DELTA:
        comparison.verdict = "KHÔNG NÊN BẬT"
        comparison.reason = (
            f"F1 chỉ tăng {delta:+.3f}, dưới ngưỡng đáng kể "
            f"{MIN_MEANINGFUL_F1_DELTA:.2f}, trong khi tốn thêm "
            f"{comparison.latency_delta_ms:+.1f}ms mỗi khung."
        )
        return comparison

    comparison.verdict = "NÊN BẬT"
    comparison.reason = (
        f"F1 tăng {delta:+.3f} (từ {base.f1:.3f} lên {var.f1:.3f}), vượt "
        f"biên sai số ±{moe:.3f} trên {n} khung. Chi phí thêm "
        f"{comparison.latency_delta_ms:+.1f}ms mỗi khung."
    )
    return comparison


def format_report(comparisons: list[Comparison]) -> str:
    """Bảng kết quả dạng văn bản cho terminal và file báo cáo."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("SO SÁNH A/B: TIỀN XỬ LÝ ẢNH")
    lines.append("=" * 78)
    if not comparisons:
        lines.append("Không có kịch bản nào được chạy.")
        return "\n".join(lines)

    base = comparisons[0].baseline
    lines.append(
        f"\nNhánh đối chứng (tắt hết): F1={base.f1:.3f} "
        f"P={base.precision:.3f} R={base.recall:.3f} "
        f"trên {base.frames} khung, {base.avg_latency_ms:.1f}ms/khung\n"
    )
    lines.append(f"{'Cấu hình':<28}{'F1':>8}{'Δ F1':>9}{'Δ ms':>9}  Kết luận")
    lines.append("-" * 78)
    for c in comparisons:
        lines.append(
            f"{c.variant.name:<28}{c.variant.f1:>8.3f}{c.f1_delta:>+9.3f}"
            f"{c.latency_delta_ms:>+9.1f}  {c.verdict}"
        )
    lines.append("-" * 78)
    lines.append("\nGiải thích chi tiết:")
    for c in comparisons:
        lines.append(f"\n  [{c.variant.name}] {c.verdict}")
        lines.append(f"    {c.reason}")

    winners = [c for c in comparisons if c.verdict == "NÊN BẬT"]
    lines.append("\n" + "=" * 78)
    if winners:
        best = max(winners, key=lambda c: c.f1_delta)
        lines.append(f"KHUYẾN NGHỊ: bật '{best.variant.name}'")
        lines.append("  Biến môi trường:")
        for k, v in sorted(best.variant.env.items()):
            lines.append(f"    {k}={v}")
        lines.append(
            "\n  LƯU Ý: kết quả này đúng cho bộ nhãn hiện tại. Sau khi huấn "
            "luyện lại mô hình, phải đo lại — và nếu dùng tiền xử lý ở lúc "
            "suy luận thì phải áp dụng y hệt ở lúc huấn luyện."
        )
    else:
        lines.append("KHUYẾN NGHỊ: giữ nguyên tiền xử lý TẮT.")
        lines.append(
            "  Không cấu hình nào chứng minh được cải thiện vượt nhiễu. Đây "
            "là kết quả hoàn toàn bình thường khi mô hình được huấn luyện "
            "trên ảnh chưa tiền xử lý — không phải lỗi cấu hình."
        )
    lines.append("=" * 78)
    return "\n".join(lines)


def fetch_labelled_frames(
    database_url: str,
    *,
    organization_id: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Lấy khung hình đã được người duyệt, kèm nhãn, từ hàng đợi duyệt.

    Chỉ lấy bản ghi ``approved``: bản ``pending`` chưa ai xác nhận nên
    dùng làm ground truth thì chẳng khác gì đo mô hình bằng chính phán
    đoán của nó.
    """
    from sqlalchemy import create_engine, text

    url = database_url.replace("+asyncpg", "").replace("+psycopg_async", "")
    engine = create_engine(url)

    where_org = "AND r.organization_id = :org" if organization_id else ""
    params: dict[str, Any] = {"lim": limit}
    if organization_id:
        params["org"] = organization_id

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT r.id, r.storage_key, p.sku, p.name
                FROM ai_review_candidates r
                JOIN products p ON p.id = r.confirmed_product_id
                WHERE r.status = 'approved'
                  AND r.is_deleted = false
                  AND r.storage_key IS NOT NULL
                  {where_org}
                ORDER BY r.reviewed_at DESC
                LIMIT :lim
                """
            ),
            params,
        ).mappings().all()

    return [
        {"id": str(r["id"]), "key": str(r["storage_key"]), "sku": str(r["sku"])}
        for r in rows
    ]
