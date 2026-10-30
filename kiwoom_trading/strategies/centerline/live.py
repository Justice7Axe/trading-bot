"""📍 중심선 강한 돌파 — 시총·거래대금 큰 종목의 장대양봉(기준봉) 몸통 가운데를 거래대금을 싣고 뚫을 때 모의 매수.

2026-10-30 사용자: ① '중심선을 돌파할 때 사고 2~3% 익절, 깨면 손절' → '그냥 중심선을 강하게 돌파할 때' →
  ② '중심선 모의 매매는 강한 돌파 방식으로 바꾸되 시총이 높고 거래대금도 높은 종목만'. (처음 10-30 아침 판은 '중심선에 닿으면 매수' — 바꿈)

기준봉 (전 거래일까지 10거래일 안, 장 마감 일봉): 양봉, 전날 대비 +10%↑, 거래량 ≥ 20일 평균 × 3, 대금 ≥ 100억,
  **그날 주식 대금 10위 안, 시총(종가 × 상장주식수) ≥ 5천억**, 우선주 제외. 그 뒤 이미 📍 신호가 난 기준봉은 뺌(기준봉 하나에 한 번).
중심선 C = 기준봉 정규장(KRX 1분봉 09:00~15:30) (시가 + 종가) / 2.
매수 (09:01~15:00, 매분 KRX 1분봉): 막 끝난 봉이 '직전 봉 종가 < C ≤ 이 봉 종가' 이고 봉 대금 ≥ 10억 & ≥ 직전 20봉 평균 × 5 → 모의 매수(다음 봉 시가 근처).
매도 (paper '다음날' 방식): 익절 +3% · 손절 C × (1 − 1%) · 못 닿으면 다음 날 09:00. 돈은 📍 전용 몫 300만·종목당 50만, 실전 안 함.

1년 1분봉 백테스트 (strategies/centerline/backtest_strong.py, data/centerline/strong_bigcap.txt, 비용 0.25%):
  시총 5천억↑·대금 10위·돌파 봉 5배: 27건 — 익절 +3%·손절 C−1% 건당 +0.11%, +5%·C−0.5% +0.45% (★ 없음, 최고 5일 빼면 −).
  시총·대금 조건 225개 중 플러스 44개, ★ 0개 → 큰 종목만 골라도 뚜렷한 우위는 없다. 모의로 쌓아 보고 판단.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal

KIND = "중심선"
MIN_GAIN, VOL_MULT, MIN_VALUE, TOP_N, MIN_MCAP = 0.10, 3.0, 1e10, 10, 5e11
WAIT = 10
BAR_VALUE, BAR_MULT = 1e9, 5.0
TP, STOP = 0.03, 0.01          # 익절 +3% / 손절 = 중심선 × (1 − 1%)
POOL, BUDGET = 3_000_000, 500_000
BUY_START, BUY_END = time(9, 1), time(15, 0)


@dataclass
class CenterPick:
    code: str
    name: str
    base_d: date
    center: float
    rank: int
    mcap: float
    gain: float


def _regular(client, code: str, d: date) -> Optional[tuple[float, float, float, float]]:
    """KRX 1분봉으로 d 일 정규장 (시가, 고가, 저가, 종가)."""
    b = [x for x in fetch_minute_bars(client, code, d, "KRX") if time(9, 0) <= x["ts"].time() <= time(15, 30)]
    if len(b) < 30:
        return None
    return float(b[0]["open"]), max(float(x["high"]) for x in b), min(float(x["low"]) for x in b), float(b[-1]["close"])


def load_picks(conn, client, today: date, fired: set = frozenset()) -> list[CenterPick]:
    """오늘 감시할 📍 후보. conn = daily_ohlcv.duckdb, fired = 지난 WAIT 거래일에 이미 📍 신호가 난 종목."""
    days = [d for (d,) in conn.execute(f"""SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date < ?
                                            ORDER BY date DESC LIMIT {WAIT + 21}""", [today]).fetchall()][::-1]
    if len(days) < WAIT + 21:
        return []
    out, seen = [], set()
    for bi in range(len(days) - 1, len(days) - WAIT - 1, -1):   # 가장 최근 기준봉부터
        d = days[bi]
        rows = conn.execute("""
            WITH t AS (SELECT d.code, s.name, d.open, d.close, d.volume, d.value, d.close * coalesce(s.listed_shares, 0) AS mcap,
                              rank() OVER (ORDER BY d.value DESC) rk
                       FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value IS NOT NULL QUALIFY rk <= ?),
                 h AS (SELECT code, avg(volume) av, count(*) n FROM daily_ohlcv
                       WHERE date >= ? AND date < ? AND code IN (SELECT code FROM t) GROUP BY code),
                 p AS (SELECT code, close pc FROM daily_ohlcv WHERE date = ?)
            SELECT t.code, t.name, t.rk, t.mcap, t.close / p.pc - 1
            FROM t JOIN h USING(code) JOIN p USING(code)
            WHERE h.n >= 20 AND t.close > t.open AND t.close / p.pc - 1 >= ? AND t.volume >= h.av * ? AND t.value >= ? AND t.mcap >= ?""",
                            [d, TOP_N, days[bi - 20], d, days[bi - 1], MIN_GAIN, VOL_MULT, MIN_VALUE, MIN_MCAP]).fetchall()
        for code, name, rk, mcap, gain in rows:
            if code[-1] in "579K" or code in seen or code in fired:
                continue
            try:
                base, prev = _regular(client, code, d), _regular(client, code, days[bi - 1])
            except Exception:
                logging.exception("중심선: %s 1분봉 조회 실패", code)
                continue
            if not base or not prev or base[3] <= base[0] or base[3] / prev[3] - 1 < MIN_GAIN:
                logging.info("중심선: %s %s 기준봉 정규장 값으로는 조건 밖 (%s)", name, d, base)
                continue
            seen.add(code)
            out.append(CenterPick(code, name, d, (base[0] + base[3]) / 2, int(rk), float(mcap), float(gain)))
    return out


class CenterlineWatcher:
    """매분: 후보 KRX 1분봉의 막 끝난 봉이 중심선을 대금 실어 뚫으면 매수 신호 (종목당 한 번)."""

    def __init__(self, market, client, today: date, picks: list[CenterPick], done: set = frozenset()) -> None:
        self.market, self.client, self.today, self.picks = market, client, today, picks
        self.done = set(done)
        self.last: dict[str, datetime] = {}

    def check(self, now: datetime, value_top) -> list:
        if not (BUY_START <= now.time() <= BUY_END) or not self.picks:
            return []
        minute = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        for p in self.picks:
            if p.code in self.done or self.last.get(p.code) == minute:
                continue
            self.last[p.code] = minute
            try:
                bars = [b for b in fetch_minute_bars(self.client, p.code, self.today, "KRX")
                        if time(9, 0) <= b["ts"].time() and b["ts"] < minute]
            except Exception:
                logging.warning("중심선: %s 1분봉 조회 실패", p.code)
                continue
            if len(bars) < 2:
                continue
            x, prv = bars[-1], bars[-2]
            if not (minute - x["ts"]).total_seconds() <= 120:   # 막 끝난 봉만 (늦은 신호로 안 삼)
                continue
            val = float(x["close"]) * float(x["volume"])
            prev20 = [float(b["close"]) * float(b["volume"]) for b in bars[-21:-1]]
            avg = sum(prev20) / len(prev20) if prev20 else 0
            if not (float(prv["close"]) < p.center <= float(x["close"]) and val >= BAR_VALUE and avg and val >= avg * BAR_MULT):
                continue
            self.done.add(p.code)
            reason = (f"{p.base_d:%m-%d} 기준봉 +{p.gain:.0%}·대금 {p.rank}위·시총 {p.mcap / 1e12:.1f}조 → 몸통 중심선 {p.center:,.0f} 강한 돌파 "
                      f"({x['ts']:%H:%M} 봉 대금 {val / 1e8:,.0f}억 = 직전 20봉 평균 {val / avg:.0f}배). 익절 +{TP:.0%} / 손절 {p.center * (1 - STOP):,.0f}, "
                      f"못 닿으면 다음 날 09:00 (1년 27건 건당 +0.1~0.5%, ★ 없음 — 모의로 확인)")
            out.append((p.code, p.name, KIND, Signal(minute, KIND, float(x["close"]), float(p.center), float(p.center * (1 - STOP)), reason)))
        if out:
            logging.info("중심선 강한 돌파 신호: %s", ", ".join(f"{n} {s.price:,.0f}" for _, n, _, s in out))
        return out
