"""시장 상황별 매매 (2026-10-25 사용자: "9종목과 지투지바이오의 시장 상황이 다르면 상황에 따라 다른 알고리즘을 쓰자").

| 시장 상황 (09:10 판정) | 매매 |
|---|---|
| 강한 상승장 | ① 📈 상승장 장 초 (이 모듈 UpOpenWatcher) + ② 🎯 저항 돌파 |
| 상승 흐름 보통 날 | ③ 🎯 막힌 고점 돌파 (이 모듈 BlockedHighWatcher) + ② |
| 하락 흐름 보통 날 | ② + ⑤ 🎯 약세장 인버스 (inverse_gap.WeakInverseWatcher) |
| 강한 하락장 | ② + ④ 🌙 역행 강세 종가 |
매도는 모두 paper_trader '다음날' 방식: 익절가 / 손절가 즉시 / 둘 다 아니면 15:19 에 팔지 않고 다음 날 09:00.
익절가는 +7% 가 기본이고, ① 은 익절 없음, ⑤ 는 +5% (paper_trader.NEXT_DAY_TP).

① 📈 상승장 장 초 — 10-16 사용자 주도주 9종목 모양(강한 상승장 날 장 초 전일 고가 돌파한 대형주).
   09:10 판정에서 강한 상승장이면 그 즉시 한 번: KRX 대금 상위 주식 순서 40위 안, 현재가 > 시가 → 매수.
   종목당 25만 원, 보유 한도(10종목) 예외로 40종목까지 (2026-10-25 사용자 선택).
   매도 (2026-10-25 사용자 '가 나 다 모두 적용'): 익절 없음 · 손절 −4% · 못 닿으면 다음 날 09:00. 전날 외인·기관이 둘 다 순매도한 종목은 안 삼 (paper_trader).
     근거 (스크래치 u_open.py / u_combo.py, 강한 상승장 42일): +7/−2 844건 +0.44% → 익절 없음/−4 +0.75% (앞·뒤 +, 익절 클수록·손절 넓을수록 단조),
     둘 다 순매도 제외 634건 +0.86% (빠지는 쪽 −0.04%).
   근거 (스크래치 prevhigh.py / prevhigh_an.py, 1분봉 1년 강한 상승장 41일, 09:10 봉 시가): 799건 +7/−2 +0.44% (+0.20R, 앞·뒤 +),
   9종목 중 7개 포착. 순위대별 1~10위 +0.94% · 11~20 +0.41 · 21~40 +0.18 (모두 앞·뒤 +). 강한 상승장 아닌 날은 같은 규칙 −0.37%.
   09:20 에야 강한 상승장으로 판정된 날은 사지 않는다 (09:20 매수는 약함).

③ 🎯 막힌 고점 돌파 — 전날까지 5거래일 고가 최고 R 을 09:30 전에 1분봉 종가로 넘고, 그때 09:00 부터 누적 대금 ≥ 20일 평균 하루 대금의 10%,
   시가 ≤ R (갭으로 넘은 종목 제외), 매수가 ≤ R × 1.03. 상승 흐름 보통 날(코스피 52주 고점 대비 −10% 안)과 강한 상승장 날.
   09:10 판정 전에 난 돌파는 판정 뒤 조건이 맞으면 산다. 손절 −3%, 강한 상승장 날은 −5%
   (2026-10-25, 스크래치 u_res_cb.py: 강한 상승장 42일 461건 +7/−3 +0.67% → +7/−5 +0.92%, 앞·뒤 +).
   근거 (스크래치 resbo2.py / open_plan.py, 1분봉 1년 상승 흐름 보통 날 103일): 바로 매수 1,298건 +7/−3 +0.44% (+0.14R, 앞 +0.60 / 뒤 +0.04).
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

from kiwoom_trading.screener.intraday_signals import Signal

UP_KIND = "상승장 장 초"
UP_TOP_N = 40
UP_STOP = 0.04                   # 익절 없음 (paper_trader.NEXT_DAY_TP)
UP_BUDGET = 250_000
UP_DECIDE = time(9, 10)          # 09:10 판정일 때만 (09:10~09:15 스냅샷)
UP_DEADLINE = time(9, 16)

BLOCK_KIND = "막힌 고점 돌파"
BLOCK_STOP = 0.03
BLOCK_STOP_UP = 0.05             # 강한 상승장 날
BLOCK_END = time(9, 30)
BLOCK_CHASE = 0.03
BLOCK_VALUE = 0.10


class UpOpenWatcher:
    def __init__(self, market, stock_codes, regime=None, done: bool = False) -> None:
        self.market = market
        self.stocks = set(stock_codes)
        self.regime = regime
        self.checked = done

    def check(self, now: datetime, value_top) -> list:
        if self.checked or self.regime is None or not (UP_DECIDE <= now.time() <= UP_DEADLINE):
            return []
        r = self.regime
        if r.strong_down or (UP_DECIDE not in r.done and not r.strong_up):
            return []
        self.checked = True
        if not r.strong_up:
            return []
        ranked = sorted((i for i in value_top if i.code in self.stocks), key=lambda i: i.rank)[:UP_TOP_N]
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        for n, i in enumerate(ranked, 1):
            try:
                q = self.market.quote(i.code, integrated=False)
            except Exception:
                logging.warning("상승장 장 초: %s 시세 조회 실패", i.code)
                continue
            if not q or q.price <= q.open:
                continue
            reason = (f"강한 상승장 09:10 — 대금 {n}위, 시가 대비 {q.price / q.open - 1:+.1%}. 익절 없음 / −{UP_STOP:.0%} 손절, "
                      f"못 닿으면 다음 날 09:00 (1년 42일 +0.75%, 전날 외인·기관 둘 다 순매도 제외 시 +0.86%, 종목당 {UP_BUDGET // 10000}만 원)")
            out.append((i.code, q.name or i.name, UP_KIND, Signal(ts, UP_KIND, float(q.price), float(q.open), float(q.price) * (1 - UP_STOP), reason)))
        logging.info("상승장 장 초: 대금 상위 %s종목 중 시가 위 %s종목", len(ranked), len(out))
        return out


@dataclass
class BlockCand:
    code: str
    R: float           # 5거래일 고가 최고
    base: float        # 20일 평균 하루 대금


def load_block_candidates(conn, today: date) -> dict[str, BlockCand]:
    """전 거래일 대금 상위 200 주식의 5일 고가·20일 평균 대금 (전날까지)."""
    dates = [d for (d,) in conn.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date < ? ORDER BY date DESC LIMIT 20",
                                        [today]).fetchall()]
    if len(dates) < 20:
        return {}
    prev = dates[0]
    codes = [c for (c,) in conn.execute("""SELECT d.code FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value IS NOT NULL
                                           QUALIFY rank() OVER (ORDER BY d.value DESC) <= 200""", [prev]).fetchall()]
    ph = ",".join("?" * len(codes))
    out = {}
    for c, hi5, v20 in conn.execute(f"""SELECT code, max(CASE WHEN date >= ? THEN high END), avg(value) FROM daily_ohlcv
                                        WHERE date >= ? AND date <= ? AND code IN ({ph}) GROUP BY code""",
                                     [dates[4], dates[-1], prev, *codes]).fetchall():
        if hi5 and v20:
            out[c] = BlockCand(c, float(hi5), float(v20))
    return out


class BlockedHighWatcher:
    def __init__(self, market, client, cands: dict[str, BlockCand], regime=None, done: Optional[set[str]] = None) -> None:
        self.market, self.client = market, client
        self.cands = cands
        self.regime = regime
        self.done: set[str] = set(done or ())
        self.pending: dict[str, tuple[datetime, float]] = {}   # 09:10 판정 전에 난 돌파 → (시각, 누적 대금)

    def _day_ok(self) -> Optional[bool]:
        r = self.regime
        if r is None:
            return False
        if not (r.strong_up or r.strong_down or UP_DECIDE in r.done):
            return None                                  # 아직 판정 전
        return not r.strong_down and (r.strong_up or not r.trend_weak)

    def _confirm(self, code: str, c: BlockCand, day: date) -> Optional[tuple[datetime, float]]:
        """1분봉으로 09:00~ 첫 종가 > R 봉을 찾고 그때 누적 대금 (그 봉까지)."""
        from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
        try:
            bars = [b for b in fetch_minute_bars(self.client, code, day, "KRX") if b["ts"].time() >= time(9, 0)]
        except Exception:
            logging.warning("막힌 고점 돌파: %s 1분봉 조회 실패", code)
            return None
        if not bars or (bars[0]["open"] or 0) > c.R:
            return None
        cum = 0.0
        for b in bars:
            cum += b["volume"] * ((b["high"] or 0) + (b["low"] or 0) + (b["close"] or 0)) / 3
            if (b["close"] or 0) > c.R:
                return (b["ts"], cum) if b["ts"].time() < BLOCK_END else None
        return None

    def check(self, now: datetime, value_top) -> list:
        if not self.cands or now.time() < time(9, 1) or now.time() > time(9, 40):
            return []
        ok = self._day_ok()
        if ok is False:
            return []
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        prices = {i.code: i.price for i in value_top if i.price}
        for code, c in self.cands.items():
            if code in self.done:
                continue
            if code not in self.pending:
                if now.time() > BLOCK_END or not prices.get(code) or prices[code] <= c.R:
                    continue
                hit = self._confirm(code, c, now.date())
                if hit is None:
                    continue
                self.pending[code] = hit
            if ok is None:
                continue                                   # 판정 뒤에 산다
            self.done.add(code)
            bo_ts, cum = self.pending[code]
            price = prices.get(code)
            if cum < c.base * BLOCK_VALUE or not price or price > c.R * (1 + BLOCK_CHASE):
                logging.info("막힌 고점 돌파: %s 조건 미달 (누적 대금 %.0f억 / 기준 %.0f억, 현재가 %s, 돌파선 %s)", code,
                             cum / 1e8, c.base * BLOCK_VALUE / 1e8, price, c.R)
                continue
            up = bool(self.regime is not None and self.regime.strong_up)
            stop = BLOCK_STOP_UP if up else BLOCK_STOP
            reason = (f"5일 고점 {c.R:,.0f} 을 {bo_ts:%H:%M} 돌파, 누적 대금 {cum / 1e8:,.0f}억 = 20일 평균의 {cum / c.base:.0%} "
                      f"— +7% 익절 / −{stop:.0%} 손절, 못 닿으면 다음 날 09:00 "
                      + ("(1년 강한 상승장 날 +7/−5 +0.92%)" if up else "(1년 상승 흐름 보통 날 +0.44%)"))
            name = next((i.name for i in value_top if i.code == code), code)
            out.append((code, name, BLOCK_KIND, Signal(ts, BLOCK_KIND, float(price), float(c.R), float(price) * (1 - stop), reason)))
        return out
