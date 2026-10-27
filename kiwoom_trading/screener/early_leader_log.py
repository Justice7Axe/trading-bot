"""🔬 당일 주도주 조기 점수 기록 (알림 없음, 2026-10-28 사용자 "둘 다 진행").

연구(kiwoom_trading/research/leader_early/, data/leader_early/report.txt): 09:05 점수 상위 3 중 43% 가 그날 주도주
(장 마감 대금 20위 & +5%↑), 고른 것 중 가짜(약 55%)가 수익을 다 지운다 → 가짜를 거르는 장중 수급(09:20 외인·09:50 기관 잠정, 프로그램)을
20일 넘게 쌓아 확인한다. 이 기록과 investor_intraday·program_intraday 를 code·시각으로 붙여 본다.

점수 (미래 정보 없음): 전날 대금 상위 200 종목 안에서 세 값의 백분위 평균
  누적 대금(그 시각 KRX 대금 순위 목록의 trade_value, 200위 밖이면 0) · 그 시각 등락률 · 전날 대금
  (연구의 프리장 고가 갭은 장전 시세 조회가 200번 더 필요해 뺐다)
기록: screener.duckdb early_leaders — 09:05·09:10 에 상위 10 (점수·값), 15:45 에 그날 결과(장 마감 대금 순위·등락·L1·L2),
      다음 거래일 09:05 에 다음 날 시가 등락.
"""
import logging
from datetime import date, datetime, time
from typing import Optional

from kiwoom_trading.screener.market_data import RankItem

TIMES = (time(9, 5), time(9, 10))
RESULT_AT = time(15, 45)
TOP = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS early_leaders (    -- 🔬 당일 주도주 조기 점수 (기록만)
    date DATE, t VARCHAR, rank INTEGER, code VARCHAR, name VARCHAR, score DOUBLE,
    cum_val DOUBLE, chg DOUBLE, prev_val DOUBLE, price DOUBLE,
    final_rank INTEGER, final_chg DOUBLE, close DOUBLE, high DOUBLE, l1 BOOLEAN, l2 BOOLEAN, next_open_chg DOUBLE,
    PRIMARY KEY (date, t, code)
)"""


def load_universe(conn, today: date) -> dict[str, float]:
    """전 거래일 대금 상위 200 (우선주 제외) → 전날 대금."""
    prev = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE date < ?", [today]).fetchone()[0]
    if not prev:
        return {}
    return {c: float(v) for c, v in conn.execute("""SELECT d.code, d.value FROM daily_ohlcv d JOIN stocks s USING(code)
                                                    WHERE d.date = ? AND d.value IS NOT NULL
                                                    QUALIFY rank() OVER (ORDER BY d.value DESC) <= 200""", [prev]).fetchall()
            if c[-1] not in "579K"}


def _pct(vals: dict[str, float]) -> dict[str, float]:
    order = sorted(vals, key=lambda c: vals[c])
    n = max(len(order) - 1, 1)
    return {c: i / n for i, c in enumerate(order)}


class EarlyLeaderLog:
    def __init__(self, store, market, today: date, universe: dict[str, float], names: dict[str, str]) -> None:
        self.conn, self.market, self.today = store.conn, market, today
        self.universe, self.names = universe, names
        self.conn.execute(SCHEMA)
        done = {t for (t,) in self.conn.execute("SELECT DISTINCT t FROM early_leaders WHERE date = ?", [today]).fetchall()}
        self.done = {t for t in TIMES if f"{t:%H:%M}" in done}
        self.result_done = bool(self.conn.execute("SELECT count(*) FROM early_leaders WHERE date = ? AND final_rank IS NOT NULL",
                                                  [today]).fetchone()[0])
        self.next_done = False

    def tick(self, now: datetime, value_top: list[RankItem]) -> None:
        tm = now.time()
        for t in TIMES:
            if t not in self.done and t <= tm < time(t.hour, t.minute + 5) and len(value_top) >= 100:
                self.done.add(t)
                self._snap(now, t, value_top)
        if not self.next_done and time(9, 5) <= tm < time(9, 30):
            self.next_done = True
            self._fill_next_open()
        if not self.result_done and tm >= RESULT_AT and len(value_top) >= 100:
            self.result_done = True
            self._fill_result(value_top)

    def _snap(self, now: datetime, t: time, value_top: list[RankItem]) -> None:
        by = {i.code: i for i in value_top}
        rows = {c: (float(by[c].trade_value or 0) if c in by else 0.0, by[c].change_rate if c in by and by[c].change_rate is not None else None,
                    pv, float(by[c].price or 0) if c in by else None) for c, pv in self.universe.items()}
        rows = {c: r for c, r in rows.items() if r[1] is not None}     # 대금 상위 200 밖이면 그 시각 등락을 몰라 뺀다 (누적 대금도 작아 상위권이 아님)
        if len(rows) < 20:
            return
        p_cum, p_chg, p_prev = (_pct({c: r[k] for c, r in rows.items()}) for k in (0, 1, 2))
        score = {c: (p_cum[c] + p_chg[c] + p_prev[c]) / 3 for c in rows}
        top = sorted(score, key=lambda c: -score[c])[:TOP]
        self.conn.executemany("INSERT OR REPLACE INTO early_leaders (date, t, rank, code, name, score, cum_val, chg, prev_val, price) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              [(self.today, f"{t:%H:%M}", n + 1, c, self.names.get(c, by[c].name if c in by else c), score[c], *rows[c])
                               for n, c in enumerate(top)])
        logging.info("🔬 조기 주도주 점수 %s: %s", f"{t:%H:%M}", ", ".join(f"{self.names.get(c, c)} {rows[c][1]:+.1%}" for c in top[:5]))

    def _fill_result(self, value_top: list[RankItem]) -> None:
        stocks = [i for i in sorted(value_top, key=lambda i: i.rank) if i.code in self.names and i.code[-1] not in "579K"]
        frank = {i.code: n + 1 for n, i in enumerate(stocks)}
        by = {i.code: i for i in stocks}
        codes = [c for (c,) in self.conn.execute("SELECT DISTINCT code FROM early_leaders WHERE date = ?", [self.today]).fetchall()]
        for c in codes:
            hi = None
            try:
                q = self.market.quote(c, integrated=False)
                hi = float(q.high) if q else None
            except Exception:
                pass
            r = frank.get(c)
            chg = by[c].change_rate if c in by else None
            close = float(by[c].price) if c in by and by[c].price else None
            l1 = bool(r is not None and r <= 20 and chg is not None and chg >= 0.05)
            l2 = bool(l1 and close and hi and close >= hi * 0.9)
            self.conn.execute("UPDATE early_leaders SET final_rank = ?, final_chg = ?, close = ?, high = ?, l1 = ?, l2 = ? WHERE date = ? AND code = ?",
                              [r, chg, close, hi, l1, l2, self.today, c])
        logging.info("🔬 조기 주도주 결과 기록 %s종목", len(codes))

    def _fill_next_open(self) -> None:
        prev = self.conn.execute("SELECT max(date) FROM early_leaders WHERE date < ?", [self.today]).fetchone()[0]
        if not prev:
            return
        for c, close in self.conn.execute("SELECT DISTINCT code, close FROM early_leaders WHERE date = ? AND next_open_chg IS NULL AND close IS NOT NULL",
                                          [prev]).fetchall():
            try:
                q = self.market.quote(c, integrated=False)
            except Exception:
                q = None
            if q and q.open and close:
                self.conn.execute("UPDATE early_leaders SET next_open_chg = ? WHERE date = ? AND code = ?", [q.open / close - 1, prev, c])
