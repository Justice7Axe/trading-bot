"""⑦ 📈 주도주 추세 보유 — 52주 신고가로 마감한 대금 최상위 주도주를 다음 날 시가에 사서 종가가 20일선 아래로 내려갈 때까지 들고 간다
(2026-10-25 사용자: "하이닉스 4/1~7/31 은 2~3배가 맞다, 추세 추종 주도주를 찾아 들고 가라". 매도 = 20일선 이탈, 종목당 100만 원·1주가 넘으면 1주).

선정 (전 거래일 장 마감 일봉, 20:00 일일 업데이트 뒤 확정치):
  종가 ≥ 52주 고가(그 전 250거래일 고가) & 그날 주식 대금 순위 5위 안 & 그날 외국인·기관 둘 다 순매수.
매수: 다음 날 09:00 첫 확인 때 시장가 (시가 근처). 종목당 100만 원(1주가 넘으면 1주), 동시 10종목까지 (다른 매매의 10종목 한도와 따로).
매도: 장 마감 종가가 20일 이동평균 아래 → 다음 날 09:00 시장가. 손절·익절 없음, 15:19 에도 안 판다.

1년 백테스트 (일봉 2025-10 ~ 2026-10, 비용 0.25%, 스크래치 swing3.py / swing4.py):
| 고르는 조건 (매도 20일선 이탈) | 동시 보유 | 건수 | 건당 | 앞 / 뒤 | 손익(100만/건) |
|---|---|---|---|---|---|
| 52주 신고가 & 대금 10위 | 무제한 | 143 | +11.5% | +17.7 / −3.4 | +1,464만 |
| 52주 신고가 & 대금 10위 | 10 | 75 | +9.4% | +20.9 / −13.6 | +677만 |
| 52주 신고가 & 대금 5위 | 무제한 | 75 | +14.4% | +17.1 / +7.4 | +1,026만 |
| **52주 신고가 & 대금 5위 & 외인·기관 둘 다 순매수 (채택)** | **10** | **45** | **+13.4%** | **+13.7 / +12.4** | **+580만** |
| 대금 10위 (신고가 조건 없음) | 무제한 | 665 | +1.5% | | +741만 |
| 60일 신고가 & 대금 10위 | 무제한 | 169 | +8.2% | | +1,224만 |
- 주도주를 고르는 핵심은 ① 52주 신고가(60일 신고가·조건 없음보다 확실히 좋음) ② 대금 최상위(5 > 10 > 20 > 30 > 50위, 단조) ③ 외인·기관이 함께 산 날.
  이미 60일 +30% 넘게 오른 종목이 더 좋고(+12.3% vs −1.5%), 신호 날 시장 분위기는 크게 상관없었다.
- 중앙값은 마이너스(작은 손실이 잦음), +50% 넘는 매매 20% 안팎이 전체 수익을 만든다 (전형적인 추세 추종).
- SK하이닉스: 2026-04-14 신호 → 04-15 1,165,000 매수 → 06-09 2,050,000 매도 (+75%), 06-18 → 07-03 −14%.
⚠️ 52주 고가에 250일이 필요해 1년(대체로 강세장)만 검증. 약세장 성과는 모름.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Optional

from kiwoom_trading.screener.intraday_signals import Signal

KIND = "주도주 추세"
TOP_N = 5                 # 그날 주식 대금 순위 (10 으로 바꾸면 처음 제안안)
NEED_FLOW = True          # 그날 외국인·기관 둘 다 순매수
HI_DAYS = 250
MA_DAYS = 20
MAX_HOLD = 10             # 동시 보유 (다른 매매의 MAX_POSITIONS 와 따로)
BUDGET = 1_000_000
BUY_START, BUY_END = time(9, 0), time(9, 30)


@dataclass
class TrendPick:
    code: str
    name: str
    close: float
    rank: int
    hi: float
    foreign: int
    inst: int


def load_trend_picks(conn, today: date) -> tuple[Optional[date], list[TrendPick]]:
    """today 전 마지막 거래일 장 마감 기준 ⑦ 매수 대상."""
    day = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [today]).fetchone()[0]
    if day is None:
        return None, []
    start = conn.execute(f"""SELECT min(date) FROM (SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date < ?
                             ORDER BY date DESC LIMIT {HI_DAYS})""", [day]).fetchone()[0]
    rows = conn.execute(f"""
        WITH top AS (SELECT d.code, s.name, d.close, rank() OVER (ORDER BY d.value DESC) rk
                     FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.date = ? AND d.value IS NOT NULL QUALIFY rk <= ?),
             hi AS (SELECT code, max(high) hi, count(*) n FROM daily_ohlcv WHERE date >= ? AND date < ? AND code IN (SELECT code FROM top) GROUP BY code)
        SELECT t.code, t.name, t.close, t.rk, hi.hi, i.foreign_, i.institution
        FROM top t JOIN hi USING(code) LEFT JOIN investor_daily i ON i.code = t.code AND i.date = ?
        WHERE hi.n >= 200 AND t.close >= hi.hi ORDER BY t.rk""", [day, TOP_N, start, day, day]).fetchall()
    picks = [TrendPick(c, n, float(cl), int(rk), float(h), f, i) for c, n, cl, rk, h, f, i in rows]
    if NEED_FLOW:
        picks = [p for p in picks if (p.foreign or 0) > 0 and (p.inst or 0) > 0]
    return day, picks


def ma_breaks(conn, codes, today: date) -> dict[str, tuple[date, float, float]]:
    """today 전 마지막 거래일 종가가 20일선 아래인 종목 → (그날, 종가, 20일선)."""
    out = {}
    for code in codes:
        rows = conn.execute(f"SELECT date, close FROM daily_ohlcv WHERE code = ? AND date < ? ORDER BY date DESC LIMIT {MA_DAYS}",
                            [code, today]).fetchall()
        if len(rows) < MA_DAYS:
            continue
        ma = sum(float(c) for _, c in rows) / MA_DAYS
        if float(rows[0][1]) < ma:
            out[code] = (rows[0][0], float(rows[0][1]), ma)
    return out


class TrendHoldWatcher:
    """09:00 첫 확인 때 전날 고른 ⑦ 대상을 한 번에 매수 신호로 낸다 (이미 낸 날은 다시 안 냄)."""

    def __init__(self, market, picks: list[TrendPick], day: Optional[date], done: bool = False) -> None:
        self.market = market
        self.picks = picks
        self.day = day
        self.done = done

    def check(self, now: datetime, value_top) -> list:
        if self.done or not self.picks or not (BUY_START <= now.time() <= BUY_END):
            return []
        self.done = True
        ts = now.replace(second=0, microsecond=0, tzinfo=None)
        out = []
        for p in self.picks:
            try:
                q = self.market.quote(p.code, integrated=False)
            except Exception:
                logging.warning("주도주 추세: %s 시세 조회 실패", p.code)
                continue
            if not q or not q.price:
                continue
            reason = (f"{self.day:%m-%d} 52주 신고가 마감 {p.close:,.0f} (52주 고가 {p.hi:,.0f}), 대금 {p.rank}위, "
                      f"외인 {(p.foreign or 0) / 1e8:+,.0f}억·기관 {(p.inst or 0) / 1e8:+,.0f}억 → 시가 매수, 종가가 20일선 아래면 다음 날 09:00 매도 "
                      f"(1년 45건 +13.4%, 앞 +13.7 / 뒤 +12.4)")
            out.append((p.code, q.name or p.name, KIND, Signal(ts, KIND, float(q.price), p.close, 0.0, reason)))
        logging.info("주도주 추세 매수 신호 %s종목: %s", len(out), ", ".join(f"{n} {s.price:,.0f}" for _, n, _, s in out))
        return out
