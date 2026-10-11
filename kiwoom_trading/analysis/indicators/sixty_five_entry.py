"""65기법 매수 타이밍 (지정가 분할 매수).

- 1차 매수가: 두 번째 장대양봉 몸통의 중간 지점 = (시가 + 종가) / 2
  (장대양봉이 1개뿐이면 그 캔들 기준)
- 2차 매수가: 첫 장대양봉의 종가
- 신호 다음 거래일부터 entry_valid_days 거래일 동안, 저가가 매수가 이하로 내려온 날 체결.
  그날 시가가 이미 매수가보다 낮으면(갭하락) 시가에 체결된 것으로 본다.
- 1차/2차 같은 금액 매수 기준으로 평균단가를 계산한다.
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
    first_price: int                  # 1차 매수가 (두 번째 장대양봉 몸통 중간)
    second_price: int                 # 2차 매수가 (첫 장대양봉 종가)
    first_fill: Optional[Fill]
    second_fill: Optional[Fill]
    valid_until: Optional[date]       # 주문 유효 마지막 거래일 (데이터 범위 밖이면 None)
    still_open: bool                  # 데이터 마지막 날 기준 아직 유효한 미체결 주문이 있는가
    avg_cost: Optional[float]
    last_close: int
    last_date: date

    @property
    def return_pct(self) -> Optional[float]:
        return self.last_close / self.avg_cost - 1 if self.avg_cost else None


def _fill_on(row: dict[str, Any], limit: float) -> Optional[float]:
    low, open_ = row.get("low"), row.get("open")
    if low is None or low > limit:
        return None
    return min(open_, limit) if open_ else limit


def plan_entries(signal: SixtyFiveSignal, rows_asc: list[dict[str, Any]], valid_days: int = DEFAULT_ENTRY_VALID_DAYS) -> EntryPlan:
    by_date = {r["date"]: i for i, r in enumerate(rows_asc)}
    signal_idx = by_date[signal.signal_date]
    first_candle = rows_asc[by_date[signal.candles[0].date]]
    second_candle = rows_asc[by_date[signal.candles[min(1, len(signal.candles) - 1)].date]]
    first_price = round((second_candle["open"] + second_candle["close"]) / 2)
    second_price = first_candle["close"]

    first_fill: Optional[Fill] = None
    second_fill: Optional[Fill] = None
    end_idx = min(len(rows_asc) - 1, signal_idx + valid_days)
    for i in range(signal_idx + 1, end_idx + 1):
        row = rows_asc[i]
        if first_fill is None and (price := _fill_on(row, first_price)) is not None:
            first_fill = Fill(row["date"], price, i - signal_idx)
        if second_fill is None and (price := _fill_on(row, second_price)) is not None:
            second_fill = Fill(row["date"], price, i - signal_idx)
        if first_fill and second_fill:
            break

    window_complete = signal_idx + valid_days <= len(rows_asc) - 1
    valid_until = rows_asc[signal_idx + valid_days]["date"] if window_complete else None
    still_open = not window_complete and (first_fill is None or second_fill is None)

    fills = [f.price for f in (first_fill, second_fill) if f]
    avg_cost = sum(fills) / len(fills) if fills else None
    return EntryPlan(
        first_price=first_price,
        second_price=second_price,
        first_fill=first_fill,
        second_fill=second_fill,
        valid_until=valid_until,
        still_open=still_open,
        avg_cost=avg_cost,
        last_close=rows_asc[-1]["close"],
        last_date=rows_asc[-1]["date"],
    )
