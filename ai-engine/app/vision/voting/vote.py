"""Bỏ phiếu nhiều khung hình cho danh tính một track.

Vấn đề với quyết định một khung
-------------------------------
Hai gói mì cùng tông đỏ ở 40px, qua một khung hình mờ, có thể ra
``Gấu Đỏ 0.60`` dù thật ra là Hảo Hảo. Cơ chế cũ (``_TRACK_CACHE``) khoá
đúng cái kết quả một-khung đó trong 30 giây: đoán sai ở khung đầu thì sai
suốt cả track.

Nhưng một track sống qua hàng chục khung hình, và các khung đó là các
*quan sát độc lập* của cùng một vật thể dưới góc, độ mờ, ánh sáng khác
nhau. Nhiễu ở mỗi khung là ngẫu nhiên; danh tính thật thì không đổi. Trung
bình hoá nhiều khung sẽ triệt tiêu nhiễu và giữ lại tín hiệu — đây là lý do
duy nhất khiến bỏ phiếu nâng được độ chính xác mà không cần đổi mô hình.

    Khung 1  Hảo Hảo 0.96
    Khung 2  Hảo Hảo 0.95
    Khung 3  Gấu Đỏ  0.60   <- nhiễu một khung
    Khung 4  Hảo Hảo 0.94
    ----------------------
    Chốt:    Hảo Hảo

Bỏ phiếu theo TRỌNG SỐ, không đếm phiếu trơn
--------------------------------------------
Một phiếu ``0.96`` mang nhiều thông tin hơn một phiếu ``0.55``, nên cộng
dồn *độ tin cậy* theo từng SKU thay vì đếm số lần. Nếu đếm trơn, ba phiếu
lưỡng lự 0.51 sẽ thắng hai phiếu chắc chắn 0.98 — ngược với điều ta muốn.

Khi nào chốt
------------
Không chốt ngay ở khung đầu (cả điểm của việc bỏ phiếu), nhưng cũng không
đợi mãi. Chốt khi thoả **cả hai**:

* đã có tối thiểu ``min_votes`` phiếu, và
* SKU dẫn đầu chiếm ``agreement_ratio`` tỉ lệ trọng số — tức các khung
  *đồng thuận*, không phải chia rẽ 50/50.

Một track chia rẽ dai dẳng (hai sản phẩm thật sự khó phân biệt) sẽ không
bao giờ đạt tỉ lệ đồng thuận, và **không chốt là câu trả lời đúng** ở đó:
nó đẩy quyết định sang OCR, tầng đọc được chữ trên nhãn.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Vote:
    sku: str
    confidence: float
    ts: float


@dataclass
class VoteResult:
    sku: str | None
    confidence: float            # trọng số dẫn đầu / tổng trọng số (đồng thuận)
    settled: bool                # đã đủ điều kiện chốt chưa
    votes_count: int
    runner_up_sku: str | None = None
    agreement: float = 0.0       # = confidence, đặt tên rõ cho tầng gọi
    tally: dict[str, float] = field(default_factory=dict)
    reason: str = ""


class TrackVoteBox:
    """Hòm phiếu cho một track: giữ cửa sổ các phiếu gần nhất và tổng hợp.

    Cửa sổ giới hạn (``window``) để một track sống rất lâu không tích luỹ
    vô hạn, và để danh tính có thể *đổi* khi vật thể thật đổi — cùng một
    track id đôi khi nhảy sang vật khác khi hai người đi cắt qua nhau,
    nên phiếu quá cũ không nên tiếp tục đè lên hiện tại.
    """

    __slots__ = ("votes", "window")

    def __init__(self, window: int = 30) -> None:
        self.votes: deque[Vote] = deque(maxlen=window)
        self.window = window

    def add(self, sku: str, confidence: float, ts: float | None = None) -> None:
        if not sku:
            return
        self.votes.append(Vote(sku, max(0.0, min(1.0, confidence)), ts or time.monotonic()))

    def tally(self) -> dict[str, float]:
        acc: dict[str, float] = {}
        for v in self.votes:
            acc[v.sku] = acc.get(v.sku, 0.0) + v.confidence
        return acc


def tally_votes(
    box: TrackVoteBox,
    *,
    min_votes: int = 3,
    agreement_ratio: float = 0.6,
) -> VoteResult:
    """Tổng hợp hòm phiếu thành một quyết định.

    ``agreement_ratio`` đo mức đồng thuận, không phải độ tin cậy tuyệt đối:
    0.6 nghĩa là SKU dẫn đầu phải chiếm ≥60% tổng trọng số phiếu. Ngưỡng
    này tách được "các khung nhất trí" khỏi "các khung cãi nhau", và chính
    sự phân biệt đó mới là thứ bỏ phiếu đem lại.
    """
    counts = box.tally()
    n = len(box.votes)
    if not counts:
        return VoteResult(sku=None, confidence=0.0, settled=False, votes_count=0,
                          reason="chưa có phiếu nào")

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(counts.values())
    lead_sku, lead_weight = ranked[0]
    runner = ranked[1][0] if len(ranked) > 1 else None
    agreement = lead_weight / total if total > 0 else 0.0

    settled = n >= min_votes and agreement >= agreement_ratio
    if settled:
        reason = (
            f"chốt sau {n} khung: {lead_sku} đồng thuận {agreement:.0%}"
        )
    elif n < min_votes:
        reason = f"mới {n}/{min_votes} khung — chờ thêm để bỏ phiếu"
    else:
        reason = (
            f"{n} khung nhưng chỉ đồng thuận {agreement:.0%} < "
            f"{agreement_ratio:.0%} — hai sản phẩm quá giống, cần OCR"
        )

    return VoteResult(
        sku=lead_sku,
        confidence=round(agreement, 4),
        settled=settled,
        votes_count=n,
        runner_up_sku=runner,
        agreement=round(agreement, 4),
        tally={k: round(v, 4) for k, v in counts.items()},
        reason=reason,
    )
