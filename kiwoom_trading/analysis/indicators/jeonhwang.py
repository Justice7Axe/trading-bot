"""전황(이종호) 『대형주 추세추종 투자법칙』 매매 규칙.

책 3~5장을 숫자로 옮긴 판단 함수 모음. 데이터 읽기는 하지 않는다 (백테스트·스캐너가 값을 넣어 부른다).
규칙의 출처·검증 결과는 .claude/skills/jeonhwang/SKILL.md.

흐름 (책 5장 「전황 트레이딩 플로우」):
  1. 지수 구간 (87쪽): 1구간 = 지수가 20·60·120일선 정배열 / 2구간 = 20일선 위 / 3구간 = 20일선 아래 → 쉰다.
  2. 장 마감 후 조건검색 (172쪽): 당일 거래대금 35위 안 · 상승률 100위 안 · 시가총액 3조 이상.
  3. 차트 위치 (175쪽): 일봉 60일선 > 120일선 정배열이 아니면 지운다. 오버슈팅(장 초 1시간 눌림 없이 +20%)은 뺀다 (191쪽).
  4. 관심종목은 3~6개월 둔다 (241쪽). 매매는 일봉 20일선 위에서만 (202쪽), 15분봉 60·120선 정배열이고
     120선을 지킬 때만 (204·230·241쪽).
  5. 매수 구역 (206쪽): 15분봉 최근 130개 고가 대비 2~4%(대형주)·3~8%(주도 섹터) 내려온 자리. 장 초반 쏠림이
     가라앉은 뒤 10시 30분까지 집중 (196·279쪽).
  6. 매도 (228쪽): 손절 기준에 안 걸리면 그날은 들고 넘어가 다음 날 오전(시가)에 판다.
     손절 = 매수가 −2%(대형주 219쪽) · 15분봉 120선 이탈(204쪽) · 일봉 20일선 이탈(202쪽).
"""
from dataclasses import dataclass, replace
from datetime import time
from typing import Optional, Sequence

import numpy as np

# ---- 1. 지수 구간 ---------------------------------------------------------------


def index_zone(closes: Sequence[float]) -> Optional[int]:
    """지수 일봉 종가(오래된 → 최근, 판단일 전날까지)로 구간 1·2·3. 120일 미만이면 None."""
    if len(closes) < 120:
        return None
    c = np.asarray(closes, dtype=float)
    ma20, ma60, ma120 = c[-20:].mean(), c[-60:].mean(), c[-120:].mean()
    if c[-1] > ma20 > ma60 > ma120:
        return 1
    if c[-1] > ma20:
        return 2
    return 3


# ---- 2·3. 장 마감 후 후보 ----------------------------------------------------------


@dataclass(frozen=True)
class ScreenParams:
    value_rank: int = 35          # 거래대금 순위 (전체 시장)
    chg_rank: int = 100           # 상승률 순위
    min_cap: float = 3e12         # 시가총액 3조
    overshoot_rise: float = 0.20  # 장 초 1시간 시가 대비 +20%
    overshoot_dip: float = 0.03   # 그 사이 고점 대비 3% 이상 눌림이 없으면 오버슈팅


def passes_screen(value_rank: int, chg_rank: int, cap: float, chg: float, p: ScreenParams = ScreenParams()) -> bool:
    """조건검색식: 대금 35위·상승률 100위·시총 3조. 하락 마감은 빼고 본다."""
    return value_rank <= p.value_rank and chg_rank <= p.chg_rank and cap >= p.min_cap and chg > 0


def daily_aligned(ma60: Optional[float], ma120: Optional[float]) -> bool:
    """일봉 60일선 > 120일선 (정배열)."""
    return ma60 is not None and ma120 is not None and ma60 > ma120


def is_overshoot(first_hour: Sequence[tuple[float, float, float]], day_open: float, p: ScreenParams = ScreenParams()) -> bool:
    """장 시작 후 1시간 (high, low, close) 1분봉으로 오버슈팅 판정: 시가 대비 +20%를 넘는 동안 고점 대비 3% 눌림이 한 번도 없음."""
    if not first_hour or day_open <= 0:
        return False
    run_hi, worst_dip = day_open, 0.0
    for hi, lo, _ in first_hour:
        worst_dip = min(worst_dip, lo / run_hi - 1)
        run_hi = max(run_hi, hi)
        if run_hi / day_open - 1 >= p.overshoot_rise:
            return worst_dip > -p.overshoot_dip
    return False


# ---- 4·5·6. 장중 매수·매도 ----------------------------------------------------------


@dataclass(frozen=True)
class TradeParams:
    zone_lo: float = 0.02            # 고점 대비 이만큼 내려오면 매수 (책 수식 highest(h,130)*0.98)
    zone_hi: float = 0.04            # 이보다 더 빠졌으면 구역을 벗어남 → 안 산다
    high_bars: int = 130             # 고점 = 15분봉 최근 130개 고가
    entry_start: time = time(9, 10)  # 장 초반 쏠림이 가라앉은 뒤
    entry_end: time = time(10, 30)   # 10시 30분까지 매매 집중
    stop_pct: Optional[float] = 0.02  # 매수가 대비 손절 (None = 안 씀)
    stop_ma120: bool = True          # 15분봉 120선 아래 마감 → 그 봉 종가에 손절
    need_15m_aligned: bool = True    # 15분봉 60선 > 120선일 때만 매수


DEFAULT = TradeParams()


def with_trade(**kw) -> TradeParams:
    return replace(DEFAULT, **kw)


@dataclass
class Fill:
    entry_ts: object
    entry: float
    exit_ts: object = None
    exit: Optional[float] = None     # None = 장 끝까지 손절 안 걸림 → 다음 날 시가 매도
    reason: str = ""


def bars_15m(ts: Sequence, o: Sequence[float], h: Sequence[float], l: Sequence[float], c: Sequence[float]):
    """1분봉 → 15분봉 (정규장, 09:00 기준 15분 단위). 반환: [(시작 시각, o, h, l, c, 마지막 1분봉 시각)]."""
    out, cur = [], None
    for t, oo, hh, ll, cc in zip(ts, o, h, l, c):
        mins = t.hour * 60 + t.minute
        k = mins - mins % 15
        if cur is None or cur[0] != (t.date(), k):
            if cur is not None:
                out.append(cur[1])
            cur = ((t.date(), k), [t, oo, hh, ll, cc, t])
        else:
            b = cur[1]
            b[2], b[3], b[4], b[5] = max(b[2], hh), min(b[3], ll), cc, t
    if cur is not None:
        out.append(cur[1])
    return out


def simulate_zone_day(hist15: Sequence[tuple], day1m: Sequence[tuple], ma20_px: Optional[float],
                      p: TradeParams = DEFAULT) -> Optional[Fill]:
    """매수 구역 매매 하루.

    hist15: 전날까지 15분봉 [(시작, o, h, l, c, 끝)] (오래된 → 최근, 130개 이상 권장).
    day1m: 그날 정규장 1분봉 [(ts, o, h, l, c)].
    ma20_px: 일봉 20일선 (1분봉 가격 단위로 맞춘 값) — 장중 이 아래로 내려가면 손절.
    매수 = entry_start~entry_end 에 가격이 (15분봉 130개 고가) × (1 − zone_lo) 에 닿을 때, 그 가격이
      × (1 − zone_hi) 보다 위이고 15분봉 120선 위, (설정 시) 15분봉 60선 > 120선.
    매도 = 손절 기준(매수가 −stop_pct, 15분봉 120선 아래 마감, 20일선 아래) 닿으면 즉시 (같은 1분봉이면 손절 먼저),
      장 끝까지 안 닿으면 exit=None (다음 날 시가).
    """
    closes = [b[4] for b in hist15]
    highs = [b[2] for b in hist15]
    if len(closes) < 120:
        return None

    def done_stats():     # 완성된 15분봉 기준 (120선, 60선, 고가 129개) — 15분마다 한 번만 계산
        return sum(closes[-120:]) / 120, sum(closes[-60:]) / 60, max(highs[-(p.high_bars - 1):])

    ma120, ma60, ref_done = done_stats()
    fill: Optional[Fill] = None
    cur15 = None          # 지금 만들어지는 15분봉 [시작키, o, h, l, c]
    for t, o, h, l, c in day1m:
        mins = t.hour * 60 + t.minute
        key = mins - mins % 15
        if cur15 is not None and cur15[0] != key:          # 15분봉 하나 완성
            closes.append(cur15[4]); highs.append(cur15[2])
            ma120, ma60, ref_done = done_stats()
            if fill and p.stop_ma120 and cur15[4] < ma120:
                fill.exit_ts, fill.exit, fill.reason = cur15[5], cur15[4], "15분봉 120선 이탈"
                return fill
            cur15 = None
        prev_hi = cur15[2] if cur15 is not None else 0.0     # 이 1분봉 전까지의 고가 (봉 안 순서를 모르므로)
        if cur15 is None:
            cur15 = [key, o, h, l, c, t]
        else:
            cur15[2], cur15[3], cur15[4], cur15[5] = max(cur15[2], h), min(cur15[3], l), c, t

        if fill is None:
            if not (p.entry_start <= t.time() <= p.entry_end):
                continue
            ref = max(ref_done, prev_hi, o)
            if p.need_15m_aligned and not ma60 > ma120:
                continue
            line, floor = ref * (1 - p.zone_lo), ref * (1 - p.zone_hi)
            px = o if o <= line else (line if l <= line else None)
            if px is None or px < floor or px < ma120 or (ma20_px and px < ma20_px):
                continue
            fill = Fill(t, px)
            # 매수한 봉 안에서도 손절가에 닿았으면 손절 (보수적으로)
            stop = _stop_level(fill.entry, ma20_px, p)
            if stop and l <= stop and px > stop:
                fill.exit_ts, fill.exit, fill.reason = t, stop, "손절(매수 봉)"
                return fill
            continue
        stop = _stop_level(fill.entry, ma20_px, p)
        if stop and l <= stop:
            fill.exit_ts, fill.exit = t, min(o, stop)
            fill.reason = "20일선 이탈" if ma20_px and stop == ma20_px else "매수가 손절"
            return fill
    return fill


def _stop_level(entry: float, ma20_px: Optional[float], p: TradeParams) -> Optional[float]:
    lv = [x for x in (entry * (1 - p.stop_pct) if p.stop_pct else None, ma20_px) if x]
    return max(lv) if lv else None


def simulate_momentum_day(day1m: Sequence[tuple], prev_close: float, at: time, ma20_px: Optional[float],
                          near_high: float = 0.02, min_chg: float = 0.0, stop_pct: float = 0.02,
                          end: time = time(15, 20)) -> Optional[Fill]:
    """시각 at 에 그날 고가 대비 near_high 안·전날 대비 min_chg 이상이면 그 1분봉 종가에 산다 (당일 주도주 · 오후 종가배팅).
    이후 매수가 −stop_pct 또는 20일선 아래면 손절, 아니면 다음 날 시가."""
    day_hi, fill = 0.0, None
    for t, o, h, l, c in day1m:
        day_hi = max(day_hi, h)
        if fill is None:
            if t.time() < at:
                continue
            if t.time() > end:
                return None
            if c >= day_hi * (1 - near_high) and c / prev_close - 1 >= min_chg and not (ma20_px and c < ma20_px):
                fill = Fill(t, c)
            else:
                return None          # 그 시각에 조건이 안 되면 그날은 안 산다
            continue
        stop = max(x for x in (fill.entry * (1 - stop_pct), ma20_px or 0))
        if l <= stop:
            fill.exit_ts, fill.exit, fill.reason = t, min(o, stop), "손절"
            return fill
    return fill
