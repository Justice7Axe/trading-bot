"""나눠 팔기 규칙 (실전 real.py 가 쓴다) — 절반 익절 → 남은 절반 처리.

  1️⃣ 상승장 장 초 (UP)      : 처음 −4% · +7% 절반 · 남은 절반 고점 −4% 트레일링(본전 아래로 안 내림)
  🔁 시초 회복 (RECLAIM)    : 처음 흔들기 저가 · +2R 절반 · 남은 절반 고점 −3% 트레일링(본전 아래로 안 내림)
  ☕ 카페 테마 대장 (CAFE)   : 처음 −2% · +2.5% 절반 · 남은 절반 상한가 닿으면 전부 (손절 −2% 그대로)
  모두 15:19 까지 안 끝나면 다음 날 09:00 (호출하는 쪽).
"""
from typing import Optional

from kiwoom_trading.strategies.cafe_leader.live import HALF_TP as CAFE_HALF_TP, KIND as CAFE_KIND, STOP as CAFE_STOP
from kiwoom_trading.strategies.premarket_reclaim.live import HALF_R as RECLAIM_HALF_R, KIND as RECLAIM_KIND, TRAIL as RECLAIM_TRAIL
from kiwoom_trading.strategies.regime_plays.live import UP_HALF_TP, UP_KIND, UP_STOP, UP_TRAIL

KINDS = (UP_KIND, RECLAIM_KIND, CAFE_KIND)


def first_stop(kind: str, buy: float, stop_px: Optional[float]) -> float:
    if kind == RECLAIM_KIND and stop_px and stop_px < buy:
        return stop_px
    return buy * (1 - (UP_STOP if kind == UP_KIND else CAFE_STOP if kind == CAFE_KIND else 0.04))


def half_price(kind: str, buy: float, stop0: float) -> float:
    if kind == UP_KIND:
        return buy * (1 + UP_HALF_TP)
    if kind == RECLAIM_KIND:
        return buy + RECLAIM_HALF_R * (buy - stop0)
    return buy * (1 + CAFE_HALF_TP)


def decide(kind: str, buy: float, stop_px: Optional[float], peak: float, part: int, price: float,
           upper: Optional[float] = None) -> tuple[Optional[str], str]:
    """→ (행동 'half' | 'sell' | None, 이유). part = 이미 판 절반 수량."""
    stop0 = first_stop(kind, buy, stop_px)
    if not part:
        if price <= stop0:
            return "sell", f"손절 {stop0:,.0f}원 ({stop0 / buy - 1:+.1%})"
        hp = half_price(kind, buy, stop0)
        if price >= hp:
            return "half", f"절반 익절 {price / buy - 1:+.1%} (기준 {hp:,.0f}원)"
        return None, ""
    if kind == CAFE_KIND:
        if price <= stop0:
            return "sell", f"손절 −{CAFE_STOP:.0%} (절반 익절 뒤)"
        if upper and price >= upper:
            return "sell", "상한가"
        return None, ""
    trail = UP_TRAIL if kind == UP_KIND else RECLAIM_TRAIL
    stop = max(stop0, buy, peak * (1 - trail))
    if price <= stop:
        return "sell", f"트레일링 고점 −{trail:.0%} (절반 익절 뒤)"
    return None, ""


def plan_text(kind: str, buy: float, stop_px: Optional[float]) -> str:
    stop0 = first_stop(kind, buy, stop_px)
    hp = half_price(kind, buy, stop0)
    rest = ("남은 절반 상한가 닿으면 전부" if kind == CAFE_KIND
            else f"남은 절반 고점 −{(UP_TRAIL if kind == UP_KIND else RECLAIM_TRAIL):.0%} 트레일링(본전 아래로 안 내림)")
    return f"손절 {stop0:,.0f}원 ({stop0 / buy - 1:+.1%}) · {hp:,.0f}원({hp / buy - 1:+.1%})에 절반 익절 → {rest}, 못 닿으면 다음 날 09:00"
