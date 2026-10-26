"""💰 10만 원 가상 계좌 — 한 번에 1종목에 전액, ⑥ 주도주 신고가 · ② 저항 돌파 · ⑤ 약세장 인버스 중 그날 먼저 온 신호를 산다
(2026-10-25 사용자: "10만 원으로 매매 빈도를 높이면서 크게 버는 매매" → 이 조합을 모의투자와 별개의 가상 계좌로 매일 기록).

규칙 (스캐너가 낸 신호를 그대로 받아 주문 없이 기록만 한다):
- 들고 있는 종목이 없고 오늘 아직 안 샀으면, 신호가 온 순서대로 첫 신호를 산다 (현재가, 정수 주, 1주도 못 사면 다음 신호).
  신호가 대비 +1% 넘게 오른 뒤면 추격 안 함 (모의투자와 같음). 매수는 정규장 09:00~15:19.
- 매도는 각 매매 규칙: ⑥ 익절 없음 · −4% / ② +7% · −5% / ⑤ +5% · −3%, 그날 못 닿으면 15:19 에 팔지 않고 다음 날 09:00 첫 확인 때 판다.
- 손익은 비용을 뺀다 (주식 왕복 0.25%, ETF 0.05%). 잔고 = 10만 원 + 지금까지 실현 손익 (번 돈을 계속 굴림).
1년 백테스트 (스크래치 small.py·small2.py, 신호 시각 순서, 정수 주): 10만 → 808,902원 (8.1배), 최대 낙폭 18.2%, 166건,
앞 반기 3.9배 / 뒤 반기 2.1배. ⚠️ 381 조합 중 1등이고 큰 수익은 상승장 날 ⑥ 에서 — 최근 약세장 석 달은 1.1~1.3배.
"""
import logging
from datetime import datetime, time
from typing import Callable, Optional

from kiwoom_trading.strategies.inverse.live import WEAK_KIND, WEAK_TP
from kiwoom_trading.strategies.regime_plays.live import NEWHIGH_KIND
from kiwoom_trading.strategies.resistance_retest.live import RETEST_KIND, RETEST_TP

START_CASH = 100_000
KINDS = (NEWHIGH_KIND, RETEST_KIND, WEAK_KIND)
TP = {NEWHIGH_KIND: None, RETEST_KIND: RETEST_TP, WEAK_KIND: WEAK_TP}
ETF_CODES = {"123310"}
MAX_CHASE = 0.01
OPEN, LAST_BUY, CLOSE, REPORT_AT = time(9, 0), time(15, 19), time(15, 30), time(15, 40)

SCHEMA = """
CREATE TABLE IF NOT EXISTS small_trades (   -- 💰 10만 원 가상 계좌 (주문 없음)
    id          VARCHAR PRIMARY KEY,
    date        DATE,
    code        VARCHAR,
    name        VARCHAR,
    kind        VARCHAR,
    buy_ts      TIMESTAMP,
    buy_price   DOUBLE,
    qty         INTEGER,
    stop        DOUBLE,
    tp          DOUBLE,
    sell_ts     TIMESTAMP,
    sell_price  DOUBLE,
    reason      VARCHAR,
    pnl         DOUBLE,
    status      VARCHAR      -- open / closed
);
CREATE TABLE IF NOT EXISTS small_days (date DATE PRIMARY KEY, reported BOOLEAN);
"""


def _cost(code: str) -> float:
    return 0.0005 if code in ETF_CODES else 0.0025


class SmallAccount:
    def __init__(self, store, market, today, notify: Optional[Callable[[str], object]] = None) -> None:
        self.conn = store.conn
        self.market = market
        self.today = today
        self.notify = notify or (lambda text: None)
        self.conn.execute(SCHEMA)
        row = self.conn.execute("SELECT reported FROM small_days WHERE date = ?", [today]).fetchone()
        self.reported = bool(row and row[0])

    # ------------------------------------------------------------ 상태
    def cash(self) -> float:
        return START_CASH + (self.conn.execute("SELECT coalesce(sum(pnl), 0) FROM small_trades WHERE status = 'closed'").fetchone()[0] or 0)

    def open_trade(self) -> Optional[tuple]:
        return self.conn.execute("""SELECT id, date, code, name, kind, buy_ts, buy_price, qty, stop, tp FROM small_trades
                                    WHERE status = 'open' ORDER BY buy_ts LIMIT 1""").fetchone()

    def bought_today(self) -> bool:
        return bool(self.conn.execute("SELECT count(*) FROM small_trades WHERE date = ?", [self.today]).fetchone()[0])

    # ------------------------------------------------------------ 매수
    def on_signals(self, now: datetime, items) -> None:
        tm = now.time()
        if not (OPEN <= tm < LAST_BUY) or self.open_trade() or self.bought_today():
            return
        cash = self.cash()
        for code, name, _source, s in sorted((x for x in items if x[3].kind in KINDS), key=lambda x: x[3].ts):
            try:
                q = self.market.quote(code, integrated=False)
            except Exception:
                logging.warning("10만 원 계좌: %s 시세 조회 실패", code)
                continue
            if not q or not q.price:
                continue
            price = float(q.price)
            if price > s.price * (1 + MAX_CHASE):
                logging.info("10만 원 계좌: %s 신호가보다 %+.1f%% — 추격 안 함", name, (price / s.price - 1) * 100)
                continue
            qty = int(cash // price)                                     # 비용은 팔 때 손익에서 뺀다
            if qty < 1:
                logging.info("10만 원 계좌: %s 1주 %s원 > 잔고 %s원 — 다음 신호", name, f"{price:,.0f}", f"{cash:,.0f}")
                continue
            stop = price * (s.stop / s.price) if s.stop else None      # 신호의 손절 비율을 현재가에 적용
            tp = TP.get(s.kind)
            tid = f"{now:%Y%m%d}-{code}-{s.kind}"
            self.conn.execute("""INSERT OR REPLACE INTO small_trades (id, date, code, name, kind, buy_ts, buy_price, qty, stop, tp, status)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
                              [tid, self.today, code, name, s.kind, now.replace(tzinfo=None), price, qty, stop, tp])
            how = (f"익절 +{tp:.0%} / " if tp else "장중 익절 없이 다음 날 시가 매도 / ") + (f"손절 {stop:,.0f}원 ({stop / price - 1:+.0%})" if stop else "손절 없음")
            self.notify(f"💰 10만 원 계좌 매수 {name}({code}) {qty}주 × {price:,.0f}원 = {qty * price:,.0f}원 (잔고 {cash:,.0f}원)\n"
                        f"  [{s.kind} {s.ts:%H:%M}] {how}, 못 닿으면 다음 날 09:00 매도 (주문 없는 가상 기록)")
            logging.info("10만 원 계좌 매수 %s %s주 × %s", name, qty, price)
            return

    # ------------------------------------------------------------ 매도
    def tick(self, now: datetime) -> None:
        tm = now.time()
        t = self.open_trade()
        if t and OPEN <= tm < CLOSE:
            tid, d, code, name, kind, buy_ts, buy_price, qty, stop, tp = t
            reason = None
            q = None
            try:
                q = self.market.quote(code, integrated=False)
            except Exception:
                logging.warning("10만 원 계좌: %s 시세 조회 실패", code)
            if q and q.price:
                price = float(q.price)
                if d < self.today:
                    reason = "다음 날 시초 매도"
                elif tm < LAST_BUY:
                    if stop and price <= stop:
                        reason = "손절"
                    elif tp and price >= buy_price * (1 + tp):
                        reason = f"익절 +{tp:.0%}"
                if reason:
                    pnl = qty * (price - buy_price) - qty * buy_price * _cost(code)
                    self.conn.execute("""UPDATE small_trades SET sell_ts = ?, sell_price = ?, reason = ?, pnl = ?, status = 'closed'
                                         WHERE id = ?""", [now.replace(tzinfo=None), price, reason, pnl, tid])
                    cash = self.cash()
                    self.notify(f"💰 10만 원 계좌 매도 {name}({code}) {qty}주 × {price:,.0f}원 — {reason}, "
                                f"{price / buy_price - 1 - _cost(code):+.2%} ({pnl:+,.0f}원) → 잔고 {cash:,.0f}원 "
                                f"(시작 10만 원 대비 {cash / START_CASH - 1:+.1%})")
                    logging.info("10만 원 계좌 매도 %s %s — %s, %+.0f원", name, price, reason, pnl)
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            self.conn.execute("INSERT OR REPLACE INTO small_days VALUES (?, true)", [self.today])
            self.notify(self.summary())

    def summary(self) -> str:
        cash = self.cash()
        n, w = self.conn.execute("SELECT count(*), count(*) FILTER (WHERE pnl > 0) FROM small_trades WHERE status = 'closed'").fetchone()
        t = self.open_trade()
        hold = f"\n  보유: {t[3]}({t[2]}) {t[7]}주 × {t[6]:,.0f}원 [{t[4]}] — 다음 날 09:00 매도" if t else "\n  보유 없음"
        return (f"💰 10만 원 계좌 {self.today:%m-%d} 마감: 잔고 {cash:,.0f}원 (시작 대비 {cash / START_CASH - 1:+.1%}), "
                f"끝난 매매 {n}건 중 수익 {w}건{hold}")
