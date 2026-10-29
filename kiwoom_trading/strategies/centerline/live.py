"""📍 중심선 — 거래대금이 몰린 장대양봉(기준봉) 몸통 가운데까지 눌리면 모의 매수 (2026-10-30 사용자 '모의 매매로 해줘').

기준봉 (전 거래일까지 10거래일 안, 장 마감 일봉으로 고름):
  양봉, 전날 대비 +10%↑, 거래량 ≥ 직전 20일 평균 × 3, 대금 ≥ 100억, 그날 주식 대금 20위 안, 대금 ≥ 직전 20일 평균 대금 × 10, 우선주 제외
  (순위·대금·거래량은 daily_ohlcv 통합 값 — 백테스트와 같음)
중심선 C = 기준봉 정규장(KRX) (시가 + 종가) / 2. 정규장 값은 KRX 1분봉 09:00~15:30 으로 만든다 (9-14 부터 일봉 종가 = 애프터 종가라서).
아직 살 수 있는 후보: 기준봉 뒤 어제까지 날마다 시가 ≥ C, 저가 > C(닿았으면 그날 샀어야 함), 종가 ≥ C.
매수: 오늘 KRX 시가가 C 아래면 끝. 장중 저가가 C 에 닿으면 신호(신호가 C) → paper 가 시장가로 삼 (C +1% 넘게 이미 반등했으면 추격 안 함).
  09:10 강한 하락장 판정 뒤에는 안 삼 (cancel_d.py: D 날 09:10 뒤 체결 12건 −1.80%), 그 전 체결은 삼.
매도 (paper.py mode '중심선'): 장중 C × 0.97 닿으면 손절 · 종가가 C 아래면 다음 날 09:00 · 산 날 포함 5거래일 들고 6일째 09:00.
돈: 📍 전용 몫 300만, 종목당 50만 (보유 한도 10칸 안 씀, 몫 넘는 신호는 잔고 밖 가상). 실전은 안 함.

백테스트 (strategies/centerline, data/centerline/*.txt):
  2년 289건 건당 +1.11% (앞 +1.29 / 뒤 +0.87, 최고 5일 빼도 + ★), 매도 72조합 중 65% 플러스. 중앙 −3.25%, 승률 25% — 소수 큰 수익이 만듦.
  6️⃣ 겹침 13%·7️⃣ 3%. 1년 계좌(시드 1천만)에 몫 30%·종목당 5% + D 취소로 넣으면 지금 배분 7,837만 → 7,974만(+2%), B6 2.2억 → −1% — 보탬은 거의 없음.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.screener.intraday_signals import Signal

KIND = "중심선"
MIN_GAIN, VOL_MULT, MIN_VALUE, TOP_N, ACCEL = 0.10, 3.0, 1e10, 20, 10.0
WAIT = 10                 # 기준봉 뒤 몇 거래일 안에 눌림을 기다리나
STOP = 0.03               # 손절 = 중심선 × (1 − 3%)
HOLD = 5                  # 산 날 포함 5거래일 → 6일째 09:00 매도
POOL, BUDGET = 3_000_000, 500_000
BUY_START, BUY_END = time(9, 0), time(15, 19)


@dataclass
class CenterPick:
    code: str
    name: str
    base_d: date
    center: float
    rank: int
    accel: float
    gain: float


def _regular(client, code: str, d: date) -> Optional[tuple[float, float, float, float]]:
    """KRX 1분봉으로 d 일 정규장 (시가, 고가, 저가, 종가)."""
    b = [x for x in fetch_minute_bars(client, code, d, "KRX") if time(9, 0) <= x["ts"].time() <= time(15, 30)]
    if len(b) < 30:
        return None
    return float(b[0]["open"]), max(float(x["high"]) for x in b), min(float(x["low"]) for x in b), float(b[-1]["close"])


def load_picks(conn, client, today: date) -> list[CenterPick]:
    """오늘 살 수 있는 📍 후보. conn = daily_ohlcv.duckdb, client = 키움 REST (KRX 1분봉 조회)."""
    days = [d for (d,) in conn.execute(f"""SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date < ?
                                            ORDER BY date DESC LIMIT {WAIT + 21}""", [today]).fetchall()][::-1]
    if len(days) < WAIT + 21:
        return []
    out = []
    for bi in range(len(days) - WAIT, len(days)):
        d = days[bi]
        rows = conn.execute("""
            WITH t AS (SELECT d.code, s.name, d.open, d.close, d.volume, d.value, rank() OVER (ORDER BY d.value DESC) rk
                       FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value IS NOT NULL QUALIFY rk <= ?),
                 h AS (SELECT code, avg(volume) av, avg(value) aval, count(*) n FROM daily_ohlcv
                       WHERE date >= ? AND date < ? AND code IN (SELECT code FROM t) GROUP BY code),
                 p AS (SELECT code, close pc FROM daily_ohlcv WHERE date = ?)
            SELECT t.code, t.name, t.rk, t.value / h.aval, t.close / p.pc - 1
            FROM t JOIN h USING(code) JOIN p USING(code)
            WHERE h.n >= 20 AND t.close > t.open AND t.close / p.pc - 1 >= ? AND t.volume >= h.av * ? AND t.value >= ?
              AND t.value >= h.aval * ?""", [d, TOP_N, days[bi - 20], d, days[bi - 1], MIN_GAIN, VOL_MULT, MIN_VALUE, ACCEL]).fetchall()
        for code, name, rk, acc, gain in rows:
            if code[-1] in "579K":
                continue
            try:
                base, prev = _regular(client, code, d), _regular(client, code, days[bi - 1])
                if not base or not prev or base[3] <= base[0] or base[3] / prev[3] - 1 < MIN_GAIN:
                    logging.info("중심선: %s %s 기준봉 정규장 값으로는 조건 밖 (%s)", name, d, base)
                    continue
                C = (base[0] + base[3]) / 2
                alive = True
                for k in range(bi + 1, len(days)):
                    r = _regular(client, code, days[k])
                    if not r or r[0] < C or r[2] <= C or r[3] < C:
                        alive = False; break
            except Exception:
                logging.exception("중심선: %s 1분봉 조회 실패", code)
                continue
            if alive:
                out.append(CenterPick(code, name, d, C, int(rk), float(acc), float(gain)))
    return out


def exit_reasons(client, held: list, today: date, trading_days: list[date]) -> dict[str, str]:
    """전날 이전에 산 📍 보유 → 오늘 09:00 에 팔 이유 {trade id: 이유}. held = paper Trade (stop = C × 0.97)."""
    out = {}
    prev = max(d for d in trading_days if d < today)
    for t in held:
        C = t.stop / (1 - STOP) if t.stop else None
        n = sum(1 for d in trading_days if t.date <= d < today)
        try:
            r = _regular(client, t.code, prev)
        except Exception:
            logging.exception("중심선: %s 전날 1분봉 조회 실패 — 09:00 에 팖", t.code)
            r = None
        if r is None or C is None:
            out[t.id] = "전날 정규장 종가를 못 받음 — 시초 매도"
        elif r[3] < C:
            out[t.id] = f"{prev:%m-%d} 종가 {r[3]:,.0f} < 중심선 {C:,.0f} — 시초 매도"
        elif n >= HOLD:
            out[t.id] = f"{HOLD}거래일 보유 끝 — 시초 매도"
    return out


class CenterlineWatcher:
    """장중 매분: 후보 KRX 시세 저가가 중심선에 닿으면 매수 신호 (종목당 하루 한 번)."""

    def __init__(self, market, picks: list[CenterPick], done: set[str] = frozenset()) -> None:
        self.market, self.picks = market, picks
        self.done = set(done)
        self.dead: set[str] = set()

    def check(self, now: datetime, value_top) -> list:
        if not (BUY_START <= now.time() <= BUY_END):
            return []
        out = []
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        for p in self.picks:
            if p.code in self.done or p.code in self.dead:
                continue
            try:
                q = self.market.quote(p.code, integrated=False)
            except Exception:
                logging.warning("중심선: %s 시세 조회 실패", p.code)
                continue
            if not q or not q.price or not q.open:
                continue
            if q.open < p.center:
                self.dead.add(p.code)
                logging.info("중심선: %s 시가 %s 가 중심선 %s 아래 — 오늘 안 삼", p.name, f"{q.open:,}", f"{p.center:,.0f}")
                continue
            if q.low > p.center:
                continue
            self.done.add(p.code)
            reason = (f"{p.base_d:%m-%d} 기준봉 +{p.gain:.0%}·대금 {p.rank}위·평소 대금 {p.accel:.0f}배 → 몸통 중심선 {p.center:,.0f} 눌림 "
                      f"(손절 {p.center * (1 - STOP):,.0f}, 종가가 중심선 아래면 다음 날 09:00, 최대 {HOLD}거래일; 2년 289건 +1.11%)")
            out.append((p.code, q.name or p.name, KIND, Signal(ts, KIND, float(p.center), float(p.center), float(p.center * (1 - STOP)), reason)))
        if out:
            logging.info("중심선 매수 신호: %s", ", ".join(f"{n} {s.price:,.0f}" for _, n, _, s in out))
        return out
