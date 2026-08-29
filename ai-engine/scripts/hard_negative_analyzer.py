"""Hard Negative Analyzer — thống kê các cặp SKU AI hay nhầm nhất.

Vì sao có script này
--------------------
Mục tiêu số 1 của dự án là phân biệt các sản phẩm nhìn giống nhau: Hảo Hảo
↔ Gấu Đỏ, Sting ↔ 7up, Aquafina ↔ Lavie, Pepsi ↔ Coca. Không thể sửa cái
mình không đo được. Script này KHÔNG đoán cặp nào hay nhầm — nó đọc dữ liệu
duyệt thật (bảng ai_review_candidates) và đếm: mỗi lần AI đoán X nhưng người
duyệt sửa thành Y, đó là một lần nhầm X->Y.

Nguồn dữ liệu đã có sẵn, không cần bảng mới:
  predicted_class / predicted_product_id  = AI đoán gì
  confirmed_product_id (status='approved')= người duyệt sửa thành gì
  confidence                              = AI tự tin bao nhiêu khi đoán sai

Kết quả: ma trận nhầm lẫn + xếp hạng cặp nhầm nhiều nhất, kèm độ tin cậy
trung bình lúc nhầm. Tin cậy cao mà vẫn nhầm là nguy hiểm nhất — mô hình
"chắc chắn" một cách sai lầm, nên đó là chỗ cần thêm dữ liệu train trước.

Đây là công cụ PHÂN TÍCH, chỉ đọc DB, không sửa gì. An toàn chạy trên máy
thật.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("hard-negative")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    p.add_argument(
        "--top", type=int, default=15, help="Số cặp nhầm hàng đầu để in ra"
    )
    p.add_argument(
        "--min-count",
        type=int,
        default=1,
        help="Bỏ qua cặp nhầm ít hơn số lần này (lọc nhiễu)",
    )
    return p.parse_args()


def _label(product_name: str | None, sku: str | None, predicted_class: str | None) -> str:
    """Tên hiển thị ưu tiên: tên sản phẩm > SKU > class thô của detector.

    predicted_class có thể là nhãn của bộ phân loại (vd 'mg_hh') khi AI đoán
    một class chưa map sang product, nên vẫn giữ được thông tin thay vì để
    trống.
    """
    return product_name or sku or predicted_class or "(không rõ)"


def analyze(rows: list[dict]) -> dict:
    """Tổng hợp confusion từ các bản ghi đã duyệt. Tách khỏi phần DB để test.

    rows: mỗi phần tử có predicted_label, confirmed_label, confidence.
    Chỉ tính các bản ghi mà AI đoán SAI (predicted != confirmed) — đó mới là
    hard negative. Bản ghi đoán đúng vẫn hữu ích cho accuracy nhưng không
    phải là cặp nhầm.
    """
    pair_count: dict[tuple[str, str], int] = defaultdict(int)
    pair_conf_sum: dict[tuple[str, str], float] = defaultdict(float)
    pair_conf_n: dict[tuple[str, str], int] = defaultdict(int)
    total_reviewed = 0
    total_wrong = 0

    for r in rows:
        pred = r.get("predicted_label")
        conf_true = r.get("confirmed_label")
        if not conf_true:
            continue  # chưa duyệt xong thì không tính
        if not pred:
            continue  # AI không đoán gì — không đưa vào mẫu số accuracy
        total_reviewed += 1
        if pred == conf_true:
            continue  # đoán đúng — không phải cặp nhầm
        total_wrong += 1
        # Gộp hai chiều thành một cặp đối xứng để "X hay nhầm với Y" và
        # "Y hay nhầm với X" cộng dồn — thứ ta quan tâm là CẶP dễ lẫn, không
        # phải chiều nào. Nhưng vẫn giữ chiều gốc trong count có hướng để
        # biết AI thiên về đoán nhầm sang bên nào.
        key = (pred, conf_true)
        pair_count[key] += 1
        c = r.get("confidence")
        if c is not None:
            pair_conf_sum[key] += float(c)
            pair_conf_n[key] += 1

    results = []
    for (pred, true), n in pair_count.items():
        avg_conf = (
            pair_conf_sum[(pred, true)] / pair_conf_n[(pred, true)]
            if pair_conf_n[(pred, true)]
            else None
        )
        results.append(
            {
                "predicted": pred,
                "actual": true,
                "count": n,
                "avg_confidence": avg_conf,
            }
        )
    # Sắp xếp: nhiều lần nhầm trước; cùng số lần thì tin cậy cao (nhầm mà
    # "chắc chắn") lên trước vì đó là lỗi nguy hiểm hơn.
    results.sort(
        key=lambda x: (x["count"], x["avg_confidence"] or 0.0), reverse=True
    )
    accuracy = (
        (total_reviewed - total_wrong) / total_reviewed if total_reviewed else None
    )
    return {
        "total_reviewed": total_reviewed,
        "total_wrong": total_wrong,
        "review_accuracy": accuracy,
        "pairs": results,
    }


def _fetch_rows(database_url: str) -> list[dict]:
    from sqlalchemy import create_engine, text

    url = database_url.replace("+asyncpg", "").replace("+psycopg_async", "")
    engine = create_engine(url)
    rows: list[dict] = []
    with engine.connect() as conn:
        # Nối review_candidate với products hai lần (dự đoán và xác nhận) để
        # lấy tên đọc được thay vì UUID. LEFT JOIN vì predicted_product_id có
        # thể rỗng (AI đoán class chưa map sang product) — vẫn giữ được nhờ
        # predicted_class.
        result = conn.execute(
            text(
                """
                SELECT
                    r.predicted_class                       AS predicted_class,
                    pp.name AS predicted_name, pp.sku AS predicted_sku,
                    cp.name AS confirmed_name, cp.sku AS confirmed_sku,
                    r.confidence                            AS confidence
                FROM ai_review_candidates r
                LEFT JOIN products pp ON pp.id = r.predicted_product_id
                LEFT JOIN products cp ON cp.id = r.confirmed_product_id
                WHERE r.status = 'approved'
                  AND r.confirmed_product_id IS NOT NULL
                """
            )
        )
        for m in result.mappings():
            rows.append(
                {
                    "predicted_label": _label(
                        m["predicted_name"], m["predicted_sku"], m["predicted_class"]
                    ),
                    "confirmed_label": _label(
                        m["confirmed_name"], m["confirmed_sku"], None
                    ),
                    "confidence": m["confidence"],
                }
            )
    return rows


def _print_report(summary: dict, top: int, min_count: int) -> None:
    acc = summary["review_accuracy"]
    logger.info("=" * 60)
    logger.info("HARD NEGATIVE ANALYZER — báo cáo cặp SKU hay nhầm")
    logger.info("=" * 60)
    logger.info("Số bản ghi đã duyệt : %d", summary["total_reviewed"])
    logger.info("Số lần AI đoán sai  : %d", summary["total_wrong"])
    if acc is not None:
        logger.info("Accuracy (trên tập duyệt): %.1f%%", acc * 100)
    logger.info("")
    pairs = [p for p in summary["pairs"] if p["count"] >= min_count][:top]
    if not pairs:
        logger.info(
            "Chưa có cặp nhầm nào đạt ngưỡng. Cần duyệt thêm dữ liệu ở"
            " 'Duyệt dữ liệu huấn luyện' rồi chạy lại."
        )
        return
    logger.info("%-22s %-22s %6s %8s", "AI ĐOÁN", "THỰC TẾ LÀ", "SỐ LẦN", "TIN CẬY")
    logger.info("-" * 60)
    for p in pairs:
        conf = f"{p['avg_confidence']*100:.0f}%" if p["avg_confidence"] is not None else "  -"
        logger.info(
            "%-22s %-22s %6d %8s",
            p["predicted"][:22],
            p["actual"][:22],
            p["count"],
            conf,
        )
    logger.info("")
    # Gợi ý hành động dựa trên dữ liệu, không phải khẩu hiệu chung chung.
    worst = pairs[0]
    logger.info("GỢI Ý:")
    logger.info(
        "  Cặp nhầm nhiều nhất: '%s' bị đoán thành '%s' (%d lần).",
        worst["actual"],
        worst["predicted"],
        worst["count"],
    )
    if worst["avg_confidence"] is not None and worst["avg_confidence"] > 0.7:
        logger.info(
            "  Tin cậy trung bình %.0f%% — mô hình 'chắc chắn' một cách SAI."
            " Đây là lỗi nguy hiểm nhất: nâng ngưỡng không cứu được, phải bổ"
            " sung ảnh train phân biệt hai SKU này (chụp nhiều góc, cận nhãn).",
            worst["avg_confidence"] * 100,
        )
    else:
        logger.info(
            "  Tin cậy thấp — mô hình đã 'lưỡng lự'. Bộ phân loại đang bỏ"
            " phiếu sát nhau; thêm vài chục ảnh mỗi SKU và bật multi-frame"
            " voting sẽ kéo tách được."
        )


def main() -> int:
    args = parse_args()
    if not args.database_url:
        logger.error("Thiếu --database-url (và biến DATABASE_URL cũng rỗng).")
        logger.error("ai-engine không được cấp DATABASE_URL theo thiết kế.")
        logger.error("Chạy trên VPS với biến từ .env của backend:")
        logger.error(
            "  docker compose exec \\\n"
            "    -e DATABASE_URL=\"$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)\" \\\n"
            "    ai-engine python scripts/hard_negative_analyzer.py"
        )
        return 1
    rows = _fetch_rows(args.database_url)
    summary = analyze(rows)
    _print_report(summary, top=args.top, min_count=args.min_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
