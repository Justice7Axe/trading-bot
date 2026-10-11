"""65기법 매수(1차/2차 지정가) → 매도 규칙 시뮬레이션.

가정
- 1차/2차 같은 금액. 2차가 체결되기 전에 청산되면 2차 주문은 취소.
- 손절/익절/추적손절은 마지막 체결 다음 날부터 판정 (체결일 장중 순서를 알 수 없음).
- 같은 날 손절가와 익절가가 모두 닿으면 보수적으로 손절.
- 갭으로 손절가/익절가를 건너뛰면 그날 시가에 청산.
- max_hold_days 거래일이 지나면 종가에 청산. 데이터 끝까지 보유 중이면 마지막 종가로 평가(open 상태).
"""
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from kiwoom_trading.analysis.indicators.sixty_five_entry import DEFAULT_ENTRY_VALID_DAYS, plan_entries
from kiwoom_trading.analysis.indicators.sixty_five_strategy import SixtyFiveSignal


@dataclass(frozen=True)
class ExitRule:
    name: str
    stop_loss: Optional[float] = None        # 평단 대비 (-0.10 = -10%)
    take_profit: Optional[float] = None      # 평단 대비 (+0.20 = +20%)
    trailing_stop: Optional[float] = None    # 보유 중 최고가 대비 (0.10 = 고점 대비 -10%)
    structure_stop: bool = False             # 첫 장대양봉 저가 이탈 시 손절
    max_hold_days: int = 60


@dataclass
class Trade:
    stock_code: str
    signal_date: date
    entry_date: date
    exit_date: date
    avg_cost: float
    exit_price: float
    fills: int
    reason: str
    holding_days: int
    is_open: bool

    @property
    def ret(self) -> float:
        return self.exit_price / self.avg_cost - 1


def simulate(signal: SixtyFiveSignal, rows: list[dict[str, Any]], rule: ExitRule, valid_days: int = DEFAULT_ENTRY_VALID_DAYS) -> Optional[Trade]:
    plan = plan_entries(signal, rows, valid_days)
    fills = sorted([f for f in (plan.first_fill, plan.second_fill) if f], key=lambda f: f.date)
    if not fills:
        return None
    idx = {r["date"]: i for i, r in enumerate(rows)}
    structure_level = rows[idx[signal.candles[0].date]]["low"]

    entry_i = idx[fills[0].date]
    prices = [fills[0].price]
    pending = fills[1] if len(fills) > 1 else None
    if pending and pending.date == fills[0].date:  # 갭하락으로 같은 날 둘 다 체결
        prices.append(pending.price)
        pending = None
    check_from = entry_i + 1
    peak = rows[entry_i]["high"]

    for i in range(entry_i + 1, len(rows)):
        row = rows[i]
        if pending and row["date"] == pending.date:
            prices.append(pending.price)
            pending = None
            check_from = i + 1
            peak = max(peak, row["high"])
            continue
        if i < check_from:
            continue

        avg = sum(prices) / len(prices)
        stops = []
        if rule.stop_loss is not None:
            stops.append((avg * (1 + rule.stop_loss), "손절"))
        if rule.trailing_stop is not None:
            stops.append((peak * (1 - rule.trailing_stop), "추적손절"))
        if rule.structure_stop:
            stops.append((structure_level, "첫 장대양봉 저가 이탈"))
        if stops:
            level, reason = max(stops, key=lambda x: x[0])
            if row["low"] <= level:
                return _close(signal, rows, fills, prices, entry_i, i, min(row["open"], level), reason)
        if rule.take_profit is not None:
            target = avg * (1 + rule.take_profit)
            if row["high"] >= target:
                return _close(signal, rows, fills, prices, entry_i, i, max(row["open"], target), "익절")
        if i - entry_i >= rule.max_hold_days:
            return _close(signal, rows, fills, prices, entry_i, i, row["close"], "기간 만료")
        peak = max(peak, row["high"])

    return _close(signal, rows, fills, prices, entry_i, len(rows) - 1, rows[-1]["close"], "보유 중", is_open=True)


def _close(signal, rows, fills, prices, entry_i, exit_i, price, reason, is_open=False) -> Trade:
    return Trade(
        stock_code=signal.stock_code,
        signal_date=signal.signal_date,
        entry_date=fills[0].date,
        exit_date=rows[exit_i]["date"],
        avg_cost=sum(prices) / len(prices),
        exit_price=price,
        fills=len(prices),
        reason=reason,
        holding_days=exit_i - entry_i,
        is_open=is_open,
    )
