"""🔁 시가 탈환 — 시초 흔들기 뒤 시가 회복 — 모의·실전 매수 (2026-10-27 사용자 'B 로 해봐' → 같은 날 '모의·실전 모두', 이름 '시가 탈환').

삼성SDI 10-27 차트에서 정형화 (backtest.py · timing.py, 스킬 buy-signals 18장):
  ① 프리장 갭     : 08:00~08:59 통합 1분봉 고점 ≥ 전일 종가 × 1.02
  ② 시초 흔들기   : 09:00~09:10 저가 ≤ 프리장 고점 × 0.98, 저가 ≥ 전일 종가 × 0.99
  ③ 시가 회복     : 흔들기 저가 봉 뒤 ~10:30, 1분봉 종가 > 09:00 시가 & 봉 대금 ≥ 10억 & ≥ 직전 5봉 평균 × 2 → 매수 (흔들기 저가를 깨면 그날 끝)
  손절 = 흔들기 저가 × 0.999. 손절까지 거리는 따지지 않는다 (2026-10-27 사용자 "손절선까지 따지는 것은 무리 — 관심 종목·대금 포착·타점이면 매수").
  (처음 B 는 '손절까지 2.5% 안'만 샀다 → 같은 날 사용자 결정으로 뺌)
  매도 = +2R(R = 매수가 − 손절가) 에 절반 익절 → 남은 절반 고점 −3% 트레일링(본전 아래로 안 내림), 못 닿으면 다음 날 09:00 (paper.py).
1년 (전날 대금 200위, 2025-10-16~2026-10-22, timing.py E1·M3): 2,273건 건당 +0.33% · +0.21R, 앞 +0.32 / 뒤 +0.33, 최고 5일 빼도 + ★.
대상 = 전날 대금 상위 200 주식. 09:01 에 ①② 를 보고(통합 1분봉, 종목당 1번) 남은 종목만 매분 1분봉을 다시 받는다 (최대 MAX_WATCH).
"""
import logging
from datetime import date, datetime, time
from typing import Optional

from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal

KIND = "시가 탈환"   # 처음 이름 "시초 회복" (2026-10-27 사용자 이름 변경)
GAP, SHAKE, HOLD = 0.02, 0.02, 0.01
VAL_MIN, MULT = 1e9, 2.0
HALF_R, TRAIL = 2.0, 0.03   # paper.py 매도
PRE_AT, SETUP_AT, SHAKE_END, END = time(8, 55), time(9, 11), time(9, 10), time(10, 30)
MAX_WATCH = 30


def load_candidates(conn, today: date) -> list[str]:
    """전 거래일 대금 상위 200 주식 (우선주 제외)."""
    prev = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE date < ?", [today]).fetchone()[0]
    if not prev:
        return []
    return [c for (c,) in conn.execute("""SELECT d.code FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value IS NOT NULL
                                          QUALIFY rank() OVER (ORDER BY d.value DESC) <= 200 ORDER BY d.value DESC""", [prev]).fetchall()
            if c[-1] not in "579K"]


class ReclaimWatcher:
    def __init__(self, market, client, today: date, candidates: list[str], names: dict[str, str], done: set[str] = frozenset()) -> None:
        self.market, self.client, self.today = market, client, today
        self.cands, self.names = candidates, names
        self.done = set(done)                # 오늘 이미 신호를 낸 종목
        self.setups: Optional[dict] = None   # code → (프리장 고점, 09:00 시가, 흔들기 저가, 흔들기 봉 시각, 전일 종가)
        self.dead: set[str] = set()
        self.gappers: Optional[list[str]] = None   # 08:55 통합 시세로 프리장 갭 2%↑ 인 종목만 (09:11 에 1분봉을 받을 종목 수를 줄임)

    def _prefilter(self) -> None:
        """08:55~08:59: 통합(_AL) 시세 고가(= 프리장 고가) ≥ 기준가 × 1.02 → 09:11 에 볼 종목. 1종목 1번 조회."""
        self.gappers = []
        for code in self.cands:
            try:
                q = self.market.quote(code, integrated=True)
            except Exception:
                continue
            if q and q.base_price and q.high >= q.base_price * (1 + GAP):
                self.gappers.append(code)
        logging.info("시가 탈환: 프리장 갭 2%%↑ %s종목 (전날 대금 200위 중)", len(self.gappers))

    def _bars(self, code: str):
        b = fetch_minute_bars(self.client, code, self.today, "AL")
        return [(x["ts"].time(), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), float(x["volume"])) for x in b]

    def _setup(self) -> None:
        self.setups = {}
        for code in (self.gappers if self.gappers is not None else self.cands):
            try:
                q = self.market.quote(code, integrated=False)
                prev = float(q.base_price) if q and q.base_price else None
                if not prev:
                    continue
                b = self._bars(code)
            except Exception:
                logging.warning("시가 탈환: %s 1분봉 실패", code)
                continue
            pre = [x for x in b if x[0] < time(9, 0)]
            early = [x for x in b if time(9, 0) <= x[0] <= SHAKE_END]
            if len(pre) < 10 or not early:
                continue
            pre_hi = max(x[2] for x in pre)
            low_bar = min(early, key=lambda x: x[3])
            lo = low_bar[3]
            if pre_hi >= prev * (1 + GAP) and lo <= pre_hi * (1 - SHAKE) and lo >= prev * (1 - HOLD):
                self.setups[code] = (pre_hi, early[0][1], lo, low_bar[0], prev)
            if len(self.setups) >= MAX_WATCH:
                break
        logging.info("시가 탈환: 프리장 갭·시초 흔들기 %s종목 %s", len(self.setups),
                     ", ".join(f"{self.names.get(c, c)}(프리장 고점 {s[0]:,.0f}·흔들기 저가 {s[2]:,.0f})" for c, s in self.setups.items()))

    def check(self, now: datetime, value_top=()) -> list[tuple[str, str, str, Signal]]:
        t = now.time()
        if PRE_AT <= t < time(9, 0) and self.gappers is None:
            self._prefilter()
            return []
        if t < SETUP_AT or t > END:
            return []
        if self.setups is None:
            self._setup()
        out = []
        for code, (pre_hi, op, lo, lo_t, prev) in self.setups.items():
            if code in self.done or code in self.dead:
                continue
            try:
                b = [x for x in self._bars(code) if x[0] < now.replace(second=0).time()]   # 마감된 봉만
            except Exception:
                continue
            after = [i for i, x in enumerate(b) if x[0] > lo_t]
            if any(b[i][3] < lo for i in after):
                self.dead.add(code)              # 흔들기 저가를 깼다 → 그날 끝
                continue
            vals = [x[4] * x[5] for x in b]
            for i in after:
                if i < 5 or b[i][0] > END:
                    continue
                avg5 = sum(vals[i - 5:i]) / 5
                if b[i][4] > op and vals[i] >= VAL_MIN and vals[i] >= MULT * avg5:
                    stop = lo * 0.999
                    price = b[i][4]
                    name = self.names.get(code, code)
                    reason = (f"🔁 시가 탈환 — 시초 흔들기 뒤 시가 회복 — 프리장 고점 {pre_hi:,.0f}(전일 대비 {pre_hi / prev - 1:+.1%}) → 09:00~ 저가 {lo:,.0f}, "
                              f"{b[i][0]:%H:%M} 종가 {price:,.0f} > 시가 {op:,.0f}, 봉 대금 {vals[i] / 1e8:.0f}억(직전 5봉 {avg5 / 1e8:.0f}억). "
                              f"손절 {stop:,.0f}({stop / price - 1:+.1%}), +{HALF_R:g}R 에 절반 익절 → 남은 절반 고점 −{TRAIL:.0%} 트레일링, "
                              f"못 닿으면 다음 날 09:00")
                    out.append((code, name, KIND, Signal(now.replace(second=0, microsecond=0, tzinfo=None), KIND, float(price), float(op), float(stop), reason)))
                    self.done.add(code)
                    break
        return out
