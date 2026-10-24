"""🧱 저항 재시험 후보 (지투지바이오형) — 장 마감 뒤 일봉·대금으로 '다음 날 예전 고점 돌파를 지켜볼 종목'을 고른다
(2026-10-25 사용자: "지투지바이오 일봉 캔들 모양과 거래대금 패턴으로 종목이 포착되게 하라").

지투지바이오(456160) 10-22 장 마감 모양:
- 10-01 +20.7% 장대양봉(대금 20일 평균 4.9배), 고가 45,150 = 예전 고점(저항)
- 10-08~15 고점 대비 −34% 까지 급락 → 10-19 +24.6%, 10-21 +17.9% 장대양봉 두 번으로 V자 회복
- 10-21·22 고가 45,000·45,200 으로 저항에 닿고 종가는 저항 −7.5% 에서 버팀, 최근 3일 대금 = 이전 20일 평균의 4.3배
- 10-23 45,200 돌파 → +18.8% (시장은 −4.4% 강한 하락장)

규칙 (일봉, 장 마감 기준): 그날 대금 50억↑ 주식
  H = 60거래일 전 ~ 4거래일 전 고가 최고 (예전 고점)
  ① 최근 5일 중 종가 +15%↑ 장대양봉 1개↑  ② 최근 3일 평균 대금 ≥ 이전 20일 평균 × 2
  ③ 종가가 H 의 −15% ~ 0%  ④ 최근 3일 고가 최고 ≥ H × 0.97 (저항 시험)
  다음 날 볼 값: R = max(H, 최근 3일 고가) 돌파
⚠️ 2년 일봉 검증(스크래치 g2g_daily.py / g2g_daily_an.py): 하루 약 8종목, 다음 날 R 돌파 14%, 돌파 매수(+7% 익절, 손절 없이 다음 날 시가)
   −0.32% (앞 −0.65 / 뒤 −0.09) → 모양만으로는 우위 없음. 장대양봉 2개↑·대금 4배↑ 로 더 닮게 하면 −0.9~−1.6% 로 더 나쁘다.
   강한 상승장 날 돌파만 +1.3~1.5% (61건). → 알림(관찰)용. 모의 매수는 기존 규칙대로 강한 상승장 날 신호만.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

BIG_BULL = 0.15
VALUE_MULT = 2.0
POS_LOW, POS_HIGH = -0.15, 0.0
TEST_GAP = 0.03
MIN_VALUE = 5e9


@dataclass
class RetestCandidate:
    code: str
    name: str
    close: float
    resistance: float      # 다음 날 돌파 볼 값 R
    pos: float             # 종가 ÷ H − 1
    value_mult: float
    big_bulls: int
    dip: float             # 최근 15일 저가 ÷ H − 1
    base_value: float = 0.0   # 평소 하루 대금 = 최근 3일 뺀 20일 평균 (원)
    mcap: float = 0.0         # 시가총액 ≈ 현재 상장주식수 × 종가 (원)


def find_retest(conn, today: date) -> list[RetestCandidate]:
    dates = [d for (d,) in conn.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date <= ? ORDER BY date DESC LIMIT 66",
                                        [today]).fetchall()][::-1]
    if len(dates) < 66 or dates[-1] != today:
        return []
    codes = [c for (c,) in conn.execute("""SELECT d.code FROM daily_ohlcv d JOIN stocks s USING(code)
                                           WHERE d.date = ? AND d.value >= ?""", [today, MIN_VALUE]).fetchall()]
    if not codes:
        return []
    names = dict(conn.execute("SELECT code, name FROM stocks").fetchall())
    shares = dict(conn.execute("SELECT code, listed_shares FROM stocks").fetchall())
    hist: dict[str, dict] = {c: {} for c in codes}
    ph = ",".join("?" * len(codes))
    for c, d, o, h, l, cl, v in conn.execute(f"""SELECT code, date, open, high, low, close, value FROM daily_ohlcv
                                                 WHERE date >= ? AND date <= ? AND code IN ({ph})""", [dates[0], today, *codes]).fetchall():
        hist[c][d] = (o, h, l, cl, v)
    out = []
    for c in codes:
        xs = [hist[c].get(d) for d in dates]
        if any(x is None or x[1] is None or x[3] is None for x in xs):
            continue
        k = len(xs)     # 마지막(오늘) 다음 날을 보는 것과 같다
        H = max(x[1] for x in xs[k - 60:k - 3])
        bulls = sum(1 for j in range(k - 5, k) if xs[j - 1][3] and xs[j][3] / xs[j - 1][3] - 1 >= BIG_BULL)
        v3 = sum(x[4] or 0 for x in xs[k - 3:k]) / 3
        v20 = sum(x[4] or 0 for x in xs[k - 23:k - 3]) / 20
        pos = xs[-1][3] / H - 1
        test = max(x[1] for x in xs[k - 3:k]) / H - 1
        if bulls >= 1 and v20 and v3 / v20 >= VALUE_MULT and POS_LOW <= pos <= POS_HIGH and test >= -TEST_GAP:
            out.append(RetestCandidate(c, names.get(c, c), xs[-1][3], max(H, max(x[1] for x in xs[k - 3:k])), pos, v3 / v20, bulls,
                                       min(x[2] for x in xs[k - 15:k]) / H - 1, v20, (shares.get(c) or 0) * xs[-1][3]))
    return sorted(out, key=lambda x: -x.value_mult)


def format_retest(cands: list[RetestCandidate], limit: int = 15) -> str:
    if not cands:
        return "🧱 저항 재시험 후보(지투지바이오형): 없음"
    lines = [f"🧱 저항 재시험 후보(지투지바이오형) {len(cands)}종목 — 다음 날 '돌파선' 넘으면 🎯 저항 돌파 모의 매수",
             "(시총 2천억↑ · 09:10 뒤 돌파 · 돌파 때 그날 누적 대금 ≥ 평소 하루 대금일 때만. 일봉 2년 220건 +1.2%, 1분봉 1년 75건 −5% 손절 +1.9%)"]
    for x in cands[:limit]:
        lines.append(f"- {x.name}({x.code}) 종가 {x.close:,.0f} · 돌파선 {x.resistance:,.0f} ({x.resistance / x.close - 1:+.1%}) · "
                     f"대금 {x.value_mult:.1f}배 · 시총 {x.mcap / 1e8:,.0f}억{'' if x.mcap >= MIN_MCAP else '(2천억 미만, 매수 안 함)'} · 평소 대금 {x.base_value / 1e8:,.0f}억 · "
                     f"장대양봉 {x.big_bulls}개 · 고점 대비 저점 {x.dip:+.0%}")
    if len(cands) > limit:
        lines.append(f"… 외 {len(cands) - limit}종목")
    return "\n".join(lines)


# ---------------------------------------------------------------- 장중: 강한 상승장 날 돌파선 돌파 → 모의 매수 (2026-10-25 사용자 "원해 해줘")
RETEST_KIND = "저항 돌파"
WATCH_START, WATCH_END = time(9, 10), time(15, 15)
RETEST_TP = 0.07       # 익절 +7%
RETEST_STOP = 0.05     # 손절 −5% (즉시)
MIN_MCAP = 2e11        # 시가총액 2천억↑ (2026-10-25: 평소 대금 50억↑ 대신. 2천억↓ 후보는 어느 대금 구간도 손실)
CUM_MULT = 1.0         # ④ 돌파 때 그날 누적 대금 ≥ 평소 하루 대금 × 1


class RetestWatcher:
    """전 거래일 장 마감 후보(find_retest) 중 시가총액 2천억↑ 종목이 09:10~15:15 돌파선 R 을 넘으면 🎯 신호 — 모든 날(약세장·강한 하락장 포함).
    돌파를 처음 본 순간 그날 09:00 부터 누적 대금(통합 1분봉) ≥ 평소 하루 대금일 때만 산다(아니면 그날은 버림).
    시가가 이미 R 위면 사지 않는다. 매도는 paper_trader '다음날': +7% 익절 / −5% 즉시 손절 / 둘 다 아니면 다음 날 09:00.
    근거 (2026-10-25 사용자 '바꿔줘', 스크래치 g2g_filter*.py):
      일봉 2년 ① 평소 대금 ≥50억 +0.29% · ≥100억 +0.75% (단조) / 1분봉 1년 ④ 돌파 때 누적 ≥ 평소 & 09:10 뒤 132건 −5% 손절 +1.00%
      (앞 +1.54 / 뒤 +0.93), 강한 상승장 아닌 날 105건 +0.80%, 09:10 전 순간 돌파 −0.58%.
    2026-10-25 '제안대로 해줘': 평소 대금 50억↑ → 시총 2천억↑ (스크래치 mcap_turn*.py). 지투지형 돌파 일봉 2년: 시총 2천억↓ 254건 −1.65%,
      2천억↑ 220건 +1.22% (2천~5천억 +1.07 · 5천억~1조 +1.38 · 1~3조 +2.46), 1분봉 시총 2천억↑ & 누적 대금 조건 75건 −5% 손절 +1.92%
      (앞 +1.73 / 뒤 +2.15) vs 평소 대금 50억↑ 68건 +1.13%. 2천억↑ 안에서는 평소 대금 크기 무관."""

    def __init__(self, market, candidates: list[RetestCandidate], regime=None, done: Optional[set[str]] = None) -> None:
        self.market = market
        self.cands = {c.code: c for c in candidates if c.mcap >= MIN_MCAP}
        self.regime = regime
        self.done: set[str] = set(done or ())
        self.skip: set[str] = set()          # 시가가 이미 돌파선 위 → 오늘은 안 봄

    def _cum_value(self, code: str, day: date) -> Optional[float]:
        from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
        try:
            bars = fetch_minute_bars(self.market.client, code, day, "AL")
        except Exception:
            logging.warning("저항 돌파: %s 1분봉 조회 실패", code)
            return None
        return sum(b["volume"] * ((b["high"] or 0) + (b["low"] or 0) + (b["close"] or 0)) / 3
                   for b in bars if b["ts"].time() >= time(9, 0))

    def check(self, now: datetime, value_top=None) -> list:
        from kiwoom_trading.screener.intraday_signals import Signal
        if not self.cands or not (WATCH_START <= now.time() <= WATCH_END):
            return []
        out = []
        for code, c in self.cands.items():
            if code in self.done or code in self.skip:
                continue
            try:
                q = self.market.quote(code, integrated=False)
            except Exception:
                logging.warning("저항 돌파: %s 시세 조회 실패", code)
                continue
            if not q:
                continue
            if q.open > c.resistance:
                self.skip.add(code)
                logging.info("저항 돌파: %s 시가 %s 가 이미 돌파선 %s 위 → 안 삼", c.name, q.open, c.resistance)
                continue
            if q.price <= c.resistance:
                continue
            self.done.add(code)      # 돌파를 처음 본 순간 한 번만 판정
            cum = self._cum_value(code, now.date())
            if cum is None or cum < c.base_value * CUM_MULT:
                logging.info("저항 돌파: %s 돌파했지만 그날 누적 대금 %s억 < 평소 %s억 → 안 삼", c.name,
                             "?" if cum is None else f"{cum / 1e8:,.0f}", f"{c.base_value / 1e8:,.0f}")
                continue
            ts = now.replace(second=0, microsecond=0, tzinfo=None)
            reason = (f"🧱 저항 재시험 후보 돌파선 {c.resistance:,.0f} 돌파, 그날 누적 대금 {cum / 1e8:,.0f}억 = 평소 {c.base_value / 1e8:,.0f}억의 "
                      f"{cum / c.base_value:.1f}배 — +{RETEST_TP:.0%} 익절 / −{RETEST_STOP:.0%} 손절, 못 닿으면 다음 날 09:00 매도 "
                      f"(1분봉 1년 132건 +1.0%)")
            out.append((code, c.name, RETEST_KIND, Signal(ts, RETEST_KIND, float(q.price), float(c.resistance),
                                                          float(q.price) * (1 - RETEST_STOP), reason)))
        return out
