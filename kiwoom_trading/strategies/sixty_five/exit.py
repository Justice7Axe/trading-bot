"""65기법 매수(1차 장대양봉 종가 지정가) → 매도 규칙 시뮬레이션.

가정
- 체결일: 가격이 지정가를 뚫고 내려오는 중이므로 저가가 손절가 이하면 그날 손절.
  체결일의 익절은 장중 순서를 알 수 없어 판정하지 않는다(보수적).
- 같은 날 손절가와 익절가가 모두 닿으면 보수적으로 손절.
- 갭으로 손절가/익절가를 건너뛰면 그날 시가에 청산.
- 손절가가 매수가 이상이면(1차 장대양봉이 음봉 몸통 등) 매매하지 않는다.
- max_hold_days 거래일이 지나면 종가에 청산. 데이터 끝까지 보유 중이면 마지막 종가로 평가(open 상태).
"""
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from kiwoom_trading.strategies.sixty_five.entry import DEFAULT_ENTRY_VALID_DAYS, candle_row, plan_entries
from kiwoom_trading.strategies.sixty_five.rules import SixtyFiveSignal


STRUCTURE_POINTS = {"시가": "open", "저가": "low", "종가": "close"}


@dataclass(frozen=True)
class ExitRule:
    name: str
    stop_loss: Optional[float] = None        # 매수가 대비 (-0.10 = -10%)
    take_profit: Optional[float] = None      # 매수가 대비 (+0.20 = +20%)
    trailing_stop: Optional[float] = None    # 보유 중 최고가 대비 (0.10 = 고점 대비 -10%)
    structure_stop: Optional[str] = None     # 1차 장대양봉의 '시가' / '저가' / '종가' 이탈 시 손절
    max_hold_days: int = 60


# 기본 매도 규칙 (그리드 서치 결과, 포착 기준 시총 5,000억 이상 포함):
#   1차 장대양봉 종가 매수 → +25% 익절 / 1차 장대양봉 시가 장중 이탈 시 손절 / 둘 다 아니면 5거래일째 종가 매도
DEFAULT_EXIT_RULE = ExitRule("익절+25%/1차시가 손절/5거래일", take_profit=0.25, structure_stop="시가", max_hold_days=5)


@dataclass
class Trade:
    stock_code: str
    signal_date: date
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    reason: str
    holding_days: int
    is_open: bool

    @property
    def ret(self) -> float:
        return self.exit_price / self.entry_price - 1


def structure_stop_price(signal: SixtyFiveSignal, rows: list[dict[str, Any]], rule: ExitRule) -> Optional[float]:
    if not rule.structure_stop:
        return None
    return candle_row(signal, rows, 0)[STRUCTURE_POINTS[rule.structure_stop]]


def simulate(signal: SixtyFiveSignal, rows: list[dict[str, Any]], rule: ExitRule, valid_days: int = DEFAULT_ENTRY_VALID_DAYS) -> Optional[Trade]:
    fill = plan_entries(signal, rows, valid_days).fill
    if fill is None:
        return None
    structure_level = structure_stop_price(signal, rows, rule)
    if structure_level is not None and structure_level >= fill.price:
        return None
    entry_i = next(i for i, r in enumerate(rows) if r["date"] == fill.date)
    price = fill.price
    peak = price

    def stop_level() -> Optional[tuple[float, str]]:
        stops = []
        if rule.stop_loss is not None:
            stops.append((price * (1 + rule.stop_loss), "손절"))
        if rule.trailing_stop is not None:
            stops.append((peak * (1 - rule.trailing_stop), "추적손절"))
        if structure_level is not None:
            stops.append((structure_level, "손절"))
        return max(stops, key=lambda x: x[0]) if stops else None

    def close(i: int, exit_price: float, reason: str, is_open: bool = False) -> Trade:
        return Trade(signal.stock_code, signal.signal_date, fill.date, rows[i]["date"], price, exit_price, reason, i - entry_i, is_open)

    for i in range(entry_i, len(rows)):
        row = rows[i]
        stop = stop_level()
        if stop and row["low"] <= stop[0]:
            return close(i, stop[0] if i == entry_i else min(row["open"], stop[0]), stop[1])
        if i > entry_i and rule.take_profit is not None and row["high"] >= price * (1 + rule.take_profit):
            return close(i, max(row["open"], price * (1 + rule.take_profit)), "익절")
        if i - entry_i >= rule.max_hold_days:
            return close(i, row["close"], "기간 만료")
        if i > entry_i:
            peak = max(peak, row["high"])

    return close(len(rows) - 1, rows[-1]["close"], "보유 중", is_open=True)
