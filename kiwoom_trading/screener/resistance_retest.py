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
                                       min(x[2] for x in xs[k - 15:k]) / H - 1))
    return sorted(out, key=lambda x: -x.value_mult)


def format_retest(cands: list[RetestCandidate], limit: int = 15) -> str:
    if not cands:
        return "🧱 저항 재시험 후보(지투지바이오형): 없음"
    lines = [f"🧱 저항 재시험 후보(지투지바이오형) {len(cands)}종목 — 다음 날 '돌파선' 넘는지 관찰",
             "(장대양봉 뒤 큰 대금으로 예전 고점 바로 아래에서 버팀. 2년: 다음 날 돌파 14%, 돌파 매수 −0.3% · 강한 상승장 날만 +1.4% → 알림용)"]
    for x in cands[:limit]:
        lines.append(f"- {x.name}({x.code}) 종가 {x.close:,.0f} · 돌파선 {x.resistance:,.0f} ({x.resistance / x.close - 1:+.1%}) · "
                     f"대금 {x.value_mult:.1f}배 · 장대양봉 {x.big_bulls}개 · 고점 대비 저점 {x.dip:+.0%}")
    if len(cands) > limit:
        lines.append(f"… 외 {len(cands) - limit}종목")
    return "\n".join(lines)


# ---------------------------------------------------------------- 장중: 강한 상승장 날 돌파선 돌파 → 모의 매수 (2026-10-25 사용자 "원해 해줘")
RETEST_KIND = "저항 돌파"
WATCH_START, WATCH_END = time(9, 0), time(15, 15)
RETEST_TP = 0.07       # 익절 +7%
RETEST_STOP = 0.05     # 손절 −5% (즉시)


class RetestWatcher:
    """전 거래일 장 마감 후보(find_retest)의 돌파선 R 을 강한 상승장 날 장중에 넘으면 🎯 신호.
    시가가 이미 R 위면 사지 않는다(2년 −0.97%). 매도는 paper_trader '다음날' 방식: +7% 익절 / −5% 즉시 손절 /
    둘 다 아니면 15:19 에 팔지 않고 다음 날 첫 정규장(09:00)에 판다.
    근거: 2년 일봉, 강한 상승장 날 후보 돌파 61건 +7% 익절·다음 날 시가 +1.47% (다른 날은 −0.05 ~ −2.05%)."""

    def __init__(self, market, candidates: list[RetestCandidate], regime=None, done: Optional[set[str]] = None) -> None:
        self.market = market
        self.cands = {c.code: c for c in candidates}
        self.regime = regime
        self.done: set[str] = set(done or ())
        self.skip: set[str] = set()          # 시가가 이미 돌파선 위 → 오늘은 안 봄

    def check(self, now: datetime, value_top=None) -> list:
        from kiwoom_trading.screener.intraday_signals import Signal
        if not self.cands or not (WATCH_START <= now.time() <= WATCH_END):
            return []
        if self.regime is None or not self.regime.strong_up:
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
            self.done.add(code)
            ts = now.replace(second=0, microsecond=0, tzinfo=None)
            reason = (f"🧱 저항 재시험 후보가 강한 상승장 날 돌파선 {c.resistance:,.0f} 돌파 (전날 대금 {c.value_mult:.1f}배, "
                      f"장대양봉 {c.big_bulls}개) — +{RETEST_TP:.0%} 익절 / −{RETEST_STOP:.0%} 손절, 못 닿으면 다음 날 09:00 매도 "
                      f"(2년 강한 상승장 61건 +1.47%)")
            out.append((code, c.name, RETEST_KIND, Signal(ts, RETEST_KIND, float(q.price), float(c.resistance),
                                                          float(q.price) * (1 - RETEST_STOP), reason)))
        return out
