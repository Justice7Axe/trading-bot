"""65기법 종목 발굴.

조건
1) 연속 N개(기본 6) 일봉 창 안에서
2) 고가 기준 상승률이 15% 이상인 양봉(종가 > 시가, = 장대양봉)들의 상승률을 '각각' 더한 값이 65% 이상
   (장중에 15% 넘게 올랐어도 시가 아래로 마감한 음봉은 장대양봉이 아님)
   (창 전체의 누적 상승폭이 아니라 개별 장대양봉 상승률의 합)
3) 합산에 포함되는 장대양봉은 거래대금이 1,000억 이상이어야 함

대형주(신호일 시가총액 10조 이상)는 2)를 아래로 대체
   - 장대양봉 기준 13% 이상, 3개 이상
   - 장대양봉 상승률 합계 50% 이상

추가 필터 (조건검색식: [일]5봉전(중) 종가대비 0봉전 고가등락률 33% 이상)
4) 신호일 고가 ÷ 5거래일 전 종가 − 1 ≥ 33%
5) 신호일 시가총액 5,000억 이상
6) (선택) 급등 기간 N거래일 이내: 1차 장대양봉 ~ 신호일 (max_rally_days, 기본 꺼짐)

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
    require_bullish: bool = True        # 장대양봉은 양봉(종가 > 시가)만 인정
    rise_base: str = "prev_close"       # 'prev_close': 고가/전일종가, 'open': 고가/당일시가
    large_cap_threshold: int = 10_000_000_000_000  # 10조
    large_cap_min_candle_rise: float = 0.13         # 대형주 장대양봉 기준
    large_cap_min_candles: int = 3                  # 대형주 최소 장대양봉 개수
    large_cap_target_sum: float = 0.50              # 대형주 합계 기준
    lookback_bars: int = 5                           # 5봉전 종가 기준
    min_rise_from_lookback: Optional[float] = 0.33   # 0봉전 고가 등락률 33%. None이면 끔
    min_market_cap: int = 500_000_000_000            # 신호일 시가총액 5,000억. 0이면 끔
    max_rally_days: Optional[int] = None             # 1차 장대양봉 ~ 신호일 거래일 수 상한 (3분할·5일 매매에서 4가 유효). None이면 끔


EPSILON = 1e-9  # 11300/10000-1 = 0.12999… 같은 부동소수점 오차로 경계값이 탈락하지 않게


def _gte(value: float, threshold: float) -> bool:
    return value >= threshold - EPSILON


def market_cap_of(row: dict[str, Any], listed_shares: Optional[int]) -> Optional[int]:
    if row.get("market_cap"):
        return row["market_cap"]
    if listed_shares and row.get("close"):
        return row["close"] * listed_shares
    return None


@dataclass(frozen=True)
class Rule:
    min_candle_rise: float
    min_candles: int
    target_sum: float
    large_cap: bool


def rule_for(market_cap: Optional[int], config: SixtyFiveConfig) -> Rule:
    if market_cap is not None and market_cap >= config.large_cap_threshold:
        return Rule(config.large_cap_min_candle_rise, config.large_cap_min_candles, config.large_cap_target_sum, True)
    return Rule(config.min_candle_rise, 1, config.target_sum, False)


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
    rule: Optional[Rule] = None


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
    rule: Optional[Rule] = None


def filter_reason(
    rows_asc: list[dict[str, Any]], end: int, config: SixtyFiveConfig,
    market_cap: Optional[int] = None, rally_days: Optional[int] = None,
) -> Optional[str]:
    if config.min_market_cap and (market_cap is None or market_cap < config.min_market_cap):
        return "시총 미달"
    if config.max_rally_days is not None and rally_days is not None and rally_days > config.max_rally_days:
        return f"급등 기간 {rally_days}일"
    if config.min_rise_from_lookback is None:
        return None
    base_idx = end - config.lookback_bars
    if base_idx < 0 or not rows_asc[base_idx].get("close"):
        return f"{config.lookback_bars}봉전 데이터 없음"
    rise = rows_asc[end]["high"] / rows_asc[base_idx]["close"] - 1
    if not _gte(rise, config.min_rise_from_lookback):
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
        # 시가총액(신호일 기준)에 따라 장대양봉 기준/개수/합계 기준이 달라진다
        market_cap = market_cap_of(rows_asc[end], listed_shares)
        rule = rule_for(market_cap, config)
        target = rule.target_sum
        candles: list[BigCandle] = []
        excluded_by_value = 0
        for i in range(start, end + 1):
            rise = rises[i]
            if rise is None or not _gte(rise, rule.min_candle_rise):
                continue
            if config.require_bullish and not rows_asc[i]["close"] > rows_asc[i]["open"]:
                continue
            value = rows_asc[i].get("value") or 0
            if value < config.min_trade_value:
                excluded_by_value += 1
                continue
            candles.append(BigCandle(rows_asc[i]["date"], rise, rows_asc[i]["high"], rows_asc[i]["close"], value))

        rise_sum = sum(c.rise for c in candles)
        # 신호는 장대양봉이 나온 당일에만 발생 (합계가 기준을 넘기는 순간)
        triggered_today = bool(candles) and candles[-1].date == rows_asc[end]["date"]
        passed_sum = triggered_today and len(candles) >= rule.min_candles and _gte(rise_sum, target) and end - last_signal_idx >= config.window
        rally_days = end - next(k for k in range(start, end + 1) if rows_asc[k]["date"] == candles[0].date) + 1 if candles else None
        rejected = filter_reason(rows_asc, end, config, market_cap, rally_days) if passed_sum else None

        if candles or excluded_by_value:
            scores.append(WindowScore(
                rows_asc[end]["date"], rows_asc[start]["date"], rise_sum, len(candles), excluded_by_value,
                tuple(c.date for c in candles), market_cap, target, rejected, rule,
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
                    rule=rule,
                )
            )
            last_signal_idx = end

    return signals, scores
