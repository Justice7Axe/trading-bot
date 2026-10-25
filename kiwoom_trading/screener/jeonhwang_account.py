"""📘 [전황] 11시 당일 주도주 — 1천만 원 가상 계좌 (키움 모의 계좌와 현금을 나누지 않는 별도 기록, 주문 없음)
(2026-10-25 사용자: 지금 매매표와 같은 계좌로 넣으면 현금을 뺏어 손해 → 따로 떼어 둔 계좌로 모의매매. 스킬 jeonhwang 7·7-2장).

선정 (전 거래일 장 마감 일봉, 스킬 jeonhwang 6장):
  관심종목 = 최근 120거래일 안에 '대금 35위 · 상승률 100위 · 시총 3조 · 상승 마감 · 일봉 60일선 > 120일선' 이었던 종목
  매매 대상 = 그중 전날 종가 > 20일선 · 60일선 > 120일선 · 전날 대금 200위 안
  지수 = 전날 코스피가 20·60·120일선 정배열(1구간)인 날만 산다. 2·3구간은 쉰다 (백테스트 2구간 −0.57%, 3구간 −0.32%).
매수: 11:00 첫 확인 때 KRX 현재가 ≥ 그날 고가 × 0.99 · 전날보다 상승 · 20일선 위 → 현재가로 가상 매수.
  하루 3종목(그날 대금 순위 높은 순), 종목당 잔고 ÷ 3 (번 돈을 계속 굴림).
매도: 매수가 −2% 또는 20일선 아래로 내려가면 그 자리에서 손절, 아니면 다음 날 09:00 첫 확인 때 판다. 비용 0.25%.
1년 백테스트 (run_jeonhwang_backtest.py, 코스피 1구간): 932건 건당 +0.55%, 손익비 1.69, 앞 +0.35% / 뒤 +1.46%,
  1천만 하루 3종목 → 2,088만 (+109%, 최대 낙폭 7.9%). ⚠️ 설정 82개 중 고른 값이라 우연일 수 있음 → 이 기록으로 확인.
"""
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Callable, Optional

import duckdb

from kiwoom_trading.analysis.indicators.jeonhwang import ScreenParams, index_zone
from kiwoom_trading.common.daily_store import PROJECT_ROOT

TAG = "📘 [전황]"
START_CASH = 10_000_000
SLOTS = 3
NEAR_HIGH = 0.01
STOP_PCT = 0.02
COST = 0.0025
WATCH_DAYS = 120
BUY_AT, BUY_UNTIL = time(11, 0), time(11, 10)
OPEN, CLOSE, REPORT_AT = time(9, 0), time(15, 30), time(15, 40)
INDEX_DB = os.path.join(PROJECT_ROOT, "data", "index.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jh_trades (     -- 📘 전황 1천만 원 가상 계좌 (주문 없음)
    id          VARCHAR PRIMARY KEY,
    date        DATE,
    code        VARCHAR,
    name        VARCHAR,
    buy_ts      TIMESTAMP,
    buy_price   DOUBLE,
    qty         INTEGER,
    stop        DOUBLE,
    ma20        DOUBLE,
    sell_ts     TIMESTAMP,
    sell_price  DOUBLE,
    reason      VARCHAR,
    pnl         DOUBLE,
    status      VARCHAR      -- open / closed
);
CREATE TABLE IF NOT EXISTS jh_days (date DATE PRIMARY KEY, checked BOOLEAN, reported BOOLEAN, note VARCHAR);
"""


@dataclass
class JhTarget:
    code: str
    name: str
    prev_close: float
    ma20: float
    cand_date: date


@dataclass
class JhContext:
    day: Optional[date]           # 기준 (전 거래일)
    zone: Optional[int]           # 코스피 구간
    targets: list[JhTarget]


def load_jh_context(conn, today: date, index_db: str = INDEX_DB, sp: ScreenParams = ScreenParams()) -> JhContext:
    """today 전 마지막 거래일 장 마감 기준 관심종목·매매 대상·코스피 구간."""
    day = conn.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [today]).fetchone()[0]
    if day is None:
        return JhContext(None, None, [])
    start = conn.execute("""SELECT min(date) FROM (SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date <= ?
                            ORDER BY date DESC LIMIT 260)""", [day]).fetchone()[0]
    rows = conn.execute(f"""
        WITH d AS (
            SELECT code, date, close, value,
                   close / lag(close) OVER w - 1 AS chg,
                   avg(close) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
                   avg(close) OVER (w ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) AS ma60,
                   avg(close) OVER (w ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS ma120,
                   count(*) OVER (w ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS n
            FROM daily_ohlcv WHERE date >= ? AND date <= ? AND close > 0
            WINDOW w AS (PARTITION BY code ORDER BY date)),
        r AS (SELECT d.*, s.name, d.close * s.listed_shares AS cap,
                     row_number() OVER (PARTITION BY date ORDER BY value DESC) AS vrank,
                     row_number() OVER (PARTITION BY date ORDER BY chg DESC NULLS LAST) AS crank
              FROM d JOIN stocks s USING (code)),
        days AS (SELECT DISTINCT date FROM r ORDER BY date DESC LIMIT {WATCH_DAYS}),
        cand AS (SELECT code, max(date) AS cand_date FROM r
                 WHERE date IN (SELECT date FROM days) AND vrank <= ? AND crank <= ? AND cap >= ? AND chg > 0
                       AND n >= 120 AND ma60 > ma120 GROUP BY code)
        SELECT r.code, r.name, r.close, r.ma20, c.cand_date FROM r JOIN cand c USING (code)
        WHERE r.date = ? AND r.close > r.ma20 AND r.ma60 > r.ma120 AND r.vrank <= 200
        ORDER BY r.vrank""", [start, day, sp.value_rank, sp.chg_rank, sp.min_cap, day]).fetchall()
    targets = [JhTarget(c, n, float(cl), float(m), cd) for c, n, cl, m, cd in rows]
    zone = None
    try:
        ix = duckdb.connect(index_db, read_only=True)
        try:
            closes = [r[0] for r in ix.execute("SELECT close FROM idx_daily WHERE code='001' AND date <= ? ORDER BY date", [day]).fetchall()]
        finally:
            ix.close()
        zone = index_zone(closes)
    except Exception:
        logging.exception("전황: 코스피 지수 일봉을 못 읽음 (오늘은 쉼)")
    return JhContext(day, zone, targets)


class JeonhwangAccount:
    def __init__(self, store, market, today: date, ctx: JhContext, notify: Optional[Callable[[str], object]] = None) -> None:
        self.conn = store.conn
        self.market = market
        self.today = today
        self.ctx = ctx
        self.notify = notify or (lambda text: None)
        self.conn.execute(SCHEMA)
        row = self.conn.execute("SELECT checked, reported FROM jh_days WHERE date = ?", [today]).fetchone()
        self.checked = bool(row and row[0])
        self.reported = bool(row and row[1])

    # ------------------------------------------------------------ 상태
    def cash(self) -> float:
        return START_CASH + (self.conn.execute("SELECT coalesce(sum(pnl), 0) FROM jh_trades WHERE status = 'closed'").fetchone()[0] or 0)

    def open_trades(self) -> list[tuple]:
        return self.conn.execute("""SELECT id, date, code, name, buy_price, qty, stop, ma20 FROM jh_trades
                                    WHERE status = 'open' ORDER BY buy_ts""").fetchall()

    def _mark(self, note: Optional[str] = None) -> None:
        old = self.conn.execute("SELECT note FROM jh_days WHERE date = ?", [self.today]).fetchone()
        note = note if note is not None else (old[0] if old else "")
        self.conn.execute("INSERT OR REPLACE INTO jh_days VALUES (?, ?, ?, ?)", [self.today, self.checked, self.reported, note])

    # ------------------------------------------------------------ 매일 1분마다
    def tick(self, now: datetime, value_top=()) -> None:
        tm = now.time()
        if OPEN <= tm < CLOSE:
            self._sell(now)
        if BUY_AT <= tm <= BUY_UNTIL and not self.checked:
            self.checked = True
            note = self._buy(now, value_top)
            self._mark(note)
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            self._mark()
            self.notify(self.summary())

    def _sell(self, now: datetime) -> None:
        for tid, d, code, name, buy_price, qty, stop, ma20 in self.open_trades():
            try:
                q = self.market.quote(code, integrated=False)
            except Exception:
                logging.warning("전황 계좌: %s 시세 조회 실패", code)
                continue
            if not q or not q.price:
                continue
            price = float(q.price)
            reason = None
            if d < self.today:
                reason = "다음 날 시초 매도"
            elif stop and price <= stop:
                reason = "손절 (−2% 또는 20일선)"
            if not reason:
                continue
            pnl = qty * (price - buy_price) - qty * buy_price * COST
            self.conn.execute("""UPDATE jh_trades SET sell_ts = ?, sell_price = ?, reason = ?, pnl = ?, status = 'closed' WHERE id = ?""",
                              [now.replace(tzinfo=None), price, reason, pnl, tid])
            cash = self.cash()
            self.notify(f"{TAG} 매도 {name}({code}) {qty}주 × {price:,.0f}원 — {reason}, {price / buy_price - 1 - COST:+.2%} ({pnl:+,.0f}원)"
                        f" → 잔고 {cash:,.0f}원 (시작 1천만 대비 {cash / START_CASH - 1:+.1%}, 가상 기록)")
            logging.info("전황 계좌 매도 %s %s — %s, %+.0f원", name, price, reason, pnl)

    def _buy(self, now: datetime, value_top) -> str:
        if self.ctx.zone != 1:
            note = f"코스피 {self.ctx.zone or '?'}구간 (20·60·120일선 정배열 아님) → 오늘은 쉼"
            self.notify(f"{TAG} 11시 주도주: {note} (가상 계좌)")
            return note
        if self.open_trades():                     # 전날 산 종목이 아직 안 팔렸으면 (09:00 매도 실패 등)
            logging.warning("전황 계좌: 보유 종목이 남아 있어 오늘 매수 건너뜀")
            return "보유 남음 → 매수 건너뜀"
        rank = {r.code: r.rank for r in value_top}
        hits = []
        for t in self.ctx.targets:
            try:
                q = self.market.quote(t.code, integrated=False)
            except Exception:
                logging.warning("전황 계좌: %s 시세 조회 실패", t.code)
                continue
            if not q or not q.price or not q.high:
                continue
            price, prev = float(q.price), float(q.base_price or t.prev_close)
            if price >= q.high * (1 - NEAR_HIGH) and price > prev and price > t.ma20:
                hits.append((rank.get(t.code, 999), t, q))
        hits.sort(key=lambda x: x[0])
        if not hits:
            note = f"대상 {len(self.ctx.targets)}종목 중 11시에 고가 −1% 안·상승인 종목 없음"
            self.notify(f"{TAG} 11시 주도주: {note} (가상 계좌)")
            return note
        cash = self.cash()
        bought = []
        for rk, t, q in hits[:SLOTS]:
            price = float(q.price)
            qty = int(cash / SLOTS // price)
            if qty < 1:
                continue
            stop = max(price * (1 - STOP_PCT), t.ma20)
            tid = f"{now:%Y%m%d}-{t.code}"
            self.conn.execute("""INSERT OR REPLACE INTO jh_trades (id, date, code, name, buy_ts, buy_price, qty, stop, ma20, status)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
                              [tid, self.today, t.code, q.name or t.name, now.replace(tzinfo=None), price, qty, stop, t.ma20])
            bought.append(f"  {q.name or t.name}({t.code}) {qty}주 × {price:,.0f}원 = {qty * price:,.0f}원 "
                          f"({f'대금 {rk}위' if rk < 999 else '대금 200위 밖'}, 고가 {q.high:,} 대비 {price / q.high - 1:+.1%}, "
                          f"전날 대비 {price / float(q.base_price or t.prev_close) - 1:+.1%}, 손절 {stop:,.0f})")
        rest = f"\n  (조건 맞은 {len(hits)}종목 중 대금 순위 높은 {SLOTS}종목)" if len(hits) > SLOTS else ""
        self.notify(f"{TAG} 11시 주도주 가상 매수 (잔고 {cash:,.0f}원, 종목당 1/{SLOTS})\n" + "\n".join(bought) + rest +
                    "\n  매도: −2%·20일선 아래면 즉시 손절, 아니면 다음 날 09:00 (주문 없는 가상 기록, 1년 백테스트 1구간 건당 +0.55%)")
        logging.info("전황 계좌 매수 %s", ", ".join(b.strip() for b in bought))
        return f"{len(bought)}종목 매수"

    def summary(self) -> str:
        cash = self.cash()
        n, w = self.conn.execute("SELECT count(*), count(*) FILTER (WHERE pnl > 0) FROM jh_trades WHERE status = 'closed'").fetchone()
        held = self.open_trades()
        hold = ("\n  보유: " + ", ".join(f"{h[3]} {h[5]}주 × {h[4]:,.0f}원" for h in held) + " — 다음 날 09:00 매도") if held else "\n  보유 없음"
        note = self.conn.execute("SELECT note FROM jh_days WHERE date = ?", [self.today]).fetchone()
        return (f"{TAG} 1천만 가상 계좌 {self.today:%m-%d} 마감: 잔고 {cash:,.0f}원 (시작 대비 {cash / START_CASH - 1:+.1%}), "
                f"끝난 매매 {n}건 중 수익 {w}건, 오늘: {(note[0] if note and note[0] else '-')}{hold}")
