"""65기법 매수 타이밍 (지정가 1회 매수).

- 매수가: 1차(첫) 장대양봉의 종가
- 신호일(마지막 장대양봉) 다음 거래일부터 entry_valid_days 거래일 동안, 저가가 매수가 이하로
  내려온 날 체결. 그날 시가가 이미 매수가보다 낮으면(갭하락) 시가에 체결된 것으로 본다.
- 기간 안에 내려오지 않으면 매수하지 않는다.
"""
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from kiwoom_trading.analysis.indicators.sixty_five_strategy import SixtyFiveSignal


DEFAULT_ENTRY_VALID_DAYS = 20


@dataclass
class Fill:
    date: date
    price: float
    days_after_signal: int


@dataclass
class EntryPlan:
    entry_price: int                  # 매수가 (1차 장대양봉 종가)
    fill: Optional[Fill]
    valid_until: Optional[date]       # 주문 유효 마지막 거래일 (데이터 범위 밖이면 None)
    still_open: bool                  # 데이터 마지막 날 기준 아직 유효한 미체결 주문인가
    last_close: int
    last_date: date

    @property
    def return_pct(self) -> Optional[float]:
        return self.last_close / self.fill.price - 1 if self.fill else None


def candle_row(signal: SixtyFiveSignal, rows_asc: list[dict[str, Any]], nth: int) -> dict[str, Any]:
    """nth번째(0부터) 장대양봉의 일봉 row."""
    target = signal.candles[min(nth, len(signal.candles) - 1)].date
    return next(r for r in rows_asc if r["date"] == target)


def _fill_on(row: dict[str, Any], limit: float) -> Optional[float]:
    low, open_ = row.get("low"), row.get("open")
    if low is None or low > limit:
        return None
    return min(open_, limit) if open_ else limit


def plan_entries(signal: SixtyFiveSignal, rows_asc: list[dict[str, Any]], valid_days: int = DEFAULT_ENTRY_VALID_DAYS) -> EntryPlan:
    signal_idx = next(i for i, r in enumerate(rows_asc) if r["date"] == signal.signal_date)
    entry_price = candle_row(signal, rows_asc, 0)["close"]

    fill: Optional[Fill] = None
    end_idx = min(len(rows_asc) - 1, signal_idx + valid_days)
    for i in range(signal_idx + 1, end_idx + 1):
        if (price := _fill_on(rows_asc[i], entry_price)) is not None:
            fill = Fill(rows_asc[i]["date"], price, i - signal_idx)
            break

    window_complete = signal_idx + valid_days <= len(rows_asc) - 1
    return EntryPlan(
        entry_price=entry_price,
        fill=fill,
        valid_until=rows_asc[signal_idx + valid_days]["date"] if window_complete else None,
        still_open=fill is None and not window_complete,
        last_close=rows_asc[-1]["close"],
        last_date=rows_asc[-1]["date"],
    )
