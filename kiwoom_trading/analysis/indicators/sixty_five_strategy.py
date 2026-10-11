"""65기법 종목 발굴.

조건
1) 연속 N개(기본 6) 일봉 창 안에서
2) 고가 기준 상승률이 15% 이상인 캔들(= 장대양봉)들의 상승률을 '각각' 더한 값이 65% 이상
   (창 전체의 누적 상승폭이 아니라 개별 장대양봉 상승률의 합)
   단, 신호일 시가총액이 1조원 이상이면 50% 이상도 허용
3) 합산에 포함되는 장대양봉은 거래대금이 1,000억 이상이어야 함

추가 필터 (조건검색식: [일]5봉전(중) 종가대비 0봉전 고가등락률 33% 이상)
4) 신호일 고가 ÷ 5거래일 전 종가 − 1 ≥ 33%

시가총액 = 해당일 market_cap(KRX 수집분) 또는 종가 × 현재 상장주식수(근사).

신호일 = 합계가 처음 기준을 넘긴 날(창의 마지막 장대양봉). 이미 신호가 난 창과 겹치는
이후 신호는 같은 이벤트로 묶는다.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass(frozen=True)
class SixtyFiveConfig:
    window: int = 6                     # 5~6개 캔들
    min_candle_rise: float = 0.15       # 장대양봉 기준(고가 기준 상승률)
    target_sum: float = 0.65            # 장대양봉 상승률 합계 기준
    min_trade_value: int = 100_000_000_000  # 1,000억
    rise_base: str = "prev_close"       # 'prev_close': 고가/전일종가, 'open': 고가/당일시가
    large_cap_threshold: int = 1_000_000_000_000  # 1조
    large_cap_target_sum: float = 0.50  # 대형주 완화 기준
    lookback_bars: int = 5                           # 5봉전 종가 기준
    min_rise_from_lookback: Optional[float] = 0.33   # 0봉전 고가 등락률 33%. None이면 끔


def market_cap_of(row: dict[str, Any], listed_shares: Optional[int]) -> Optional[int]:
    if row.get("market_cap"):
        return row["market_cap"]
    if listed_shares and row.get("close"):
        return row["close"] * listed_shares
    return None


def target_for(market_cap: Optional[int], config: SixtyFiveConfig) -> float:
    if market_cap is not None and market_cap >= config.large_cap_threshold:
        return config.large_cap_target_sum
    return config.target_sum


@dataclass
class BigCandle:
    date: date
    rise: float
    high: int
    close: int
    trade_value: int


@dataclass
class SixtyFiveSignal:
    stock_code: str
    signal_date: date
    window_start: date
    rise_sum: float
    candles: list[BigCandle] = field(default_factory=list)
    signal_close: Optional[int] = None
    market_cap: Optional[int] = None
    target_sum: float = 0.65


@dataclass
class WindowScore:
    """조건 미달이어도 창별 합계를 확인하기 위한 진단용 값."""
    end_date: date
    window_start: date
    rise_sum: float
    candle_count: int
    excluded_by_value: int
    candle_dates: tuple[date, ...] = ()
    market_cap: Optional[int] = None
    target_sum: float = 0.65
    rejected: Optional[str] = None      # 합계는 통과했지만 추가 필터에 걸린 사유


def filter_reason(rows_asc: list[dict[str, Any]], end: int, config: SixtyFiveConfig) -> Optional[str]:
    if config.min_rise_from_lookback is None:
        return None
    base_idx = end - config.lookback_bars
    if base_idx < 0 or not rows_asc[base_idx].get("close"):
        return f"{config.lookback_bars}봉전 데이터 없음"
    rise = rows_asc[end]["high"] / rows_asc[base_idx]["close"] - 1
    if rise < config.min_rise_from_lookback:
        return f"{config.lookback_bars}봉전 종가 대비 고가 {rise:+.1%}"
    return None


def _candle_rise(row: dict[str, Any], prev_close: Optional[int], base: str) -> Optional[float]:
    high = row.get("high")
    reference = row.get("open") if base == "open" else prev_close
    if not high or not reference:
        return None
    return high / reference - 1


def scan_sixty_five(
    stock_code: str,
    rows_asc: list[dict[str, Any]],
    config: SixtyFiveConfig,
    listed_shares: Optional[int] = None,
) -> tuple[list[SixtyFiveSignal], list[WindowScore]]:
    """rows_asc: date 오름차순 일봉(dict: date, open, high, low, close, value[, market_cap])."""
    rises: list[Optional[float]] = []
    prev_close: Optional[int] = None
    for row in rows_asc:
        rises.append(_candle_rise(row, prev_close, config.rise_base))
        prev_close = row.get("close")

    signals: list[SixtyFiveSignal] = []
    scores: list[WindowScore] = []
    last_signal_idx = -config.window

    for end in range(len(rows_asc)):
        start = max(0, end - config.window + 1)
        candles: list[BigCandle] = []
        excluded_by_value = 0
        for i in range(start, end + 1):
            rise = rises[i]
            if rise is None or rise < config.min_candle_rise:
                continue
            value = rows_asc[i].get("value") or 0
            if value < config.min_trade_value:
                excluded_by_value += 1
                continue
            candles.append(BigCandle(rows_asc[i]["date"], rise, rows_asc[i]["high"], rows_asc[i]["close"], value))

        rise_sum = sum(c.rise for c in candles)
        market_cap = market_cap_of(rows_asc[end], listed_shares)
        target = target_for(market_cap, config)
        # 신호는 장대양봉이 나온 당일에만 발생 (합계가 기준을 넘기는 순간)
        triggered_today = bool(candles) and candles[-1].date == rows_asc[end]["date"]
        passed_sum = triggered_today and rise_sum >= target and end - last_signal_idx >= config.window
        rejected = filter_reason(rows_asc, end, config) if passed_sum else None

        if candles or excluded_by_value:
            scores.append(WindowScore(
                rows_asc[end]["date"], rows_asc[start]["date"], rise_sum, len(candles), excluded_by_value,
                tuple(c.date for c in candles), market_cap, target, rejected,
            ))

        if passed_sum and rejected is None:
            signals.append(
                SixtyFiveSignal(
                    stock_code=stock_code,
                    signal_date=rows_asc[end]["date"],
                    window_start=rows_asc[start]["date"],
                    rise_sum=rise_sum,
                    candles=candles,
                    signal_close=rows_asc[end].get("close"),
                    market_cap=market_cap,
                    target_sum=target,
                )
            )
            last_signal_idx = end

    return signals, scores
