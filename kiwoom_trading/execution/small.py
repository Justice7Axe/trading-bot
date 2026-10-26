"""💰 10만 원 가상 계좌 — 한 번에 1종목에 전액, ⑥ 주도주 신고가 · ② 저항 돌파 · ⑤ 약세장 인버스 중 그날 먼저 온 신호를 산다
(2026-10-25 사용자: "10만 원으로 매매 빈도를 높이면서 크게 버는 매매" → 이 조합을 모의투자와 별개의 가상 계좌로 매일 기록).

규칙 (스캐너가 낸 신호를 그대로 받아 주문 없이 기록만 한다):
- 들고 있는 종목이 없고 오늘 아직 안 샀으면, 신호가 온 순서대로 첫 신호를 산다 (현재가, 정수 주, 1주도 못 사면 다음 신호).
  신호가 대비 +1% 넘게 오른 뒤면 추격 안 함 (모의투자와 같음). 매수는 정규장 09:00~15:19.
- 매도는 각 매매 규칙: ⑥ 익절 없음 · −4% / ② +7% · −5% / ⑤ +5% · −3% (15:19 까지, 닿은 때의 가격), 못 닿으면 다음 날 09:00 첫 확인 때.
- 손익은 비용을 뺀다 (주식 왕복 0.25%, ETF 0.05%). 잔고 = 10만 원 + 지금까지 실현 손익 (번 돈을 계속 굴림).
- 2026-10-27: 공용 가상 장부(execution/ledger.py, book '10만 원')로 옮김. 예전 표 small_trades 의 거래(보유 중 포함)는 처음 한 번 넘겨받는다.
1년 백테스트 (스크래치 small.py·small2.py, 신호 시각 순서, 정수 주): 10만 → 808,902원 (8.1배), 최대 낙폭 18.2%, 166건,
앞 반기 3.9배 / 뒤 반기 2.1배. ⚠️ 381 조합 중 1등이고 큰 수익은 상승장 날 ⑥ 에서 — 최근 약세장 석 달은 1.1~1.3배.
"""
import logging
from datetime import datetime, time
from typing import Callable, Optional

from kiwoom_trading.execution.ledger import Ledger, Plan, price_source
from kiwoom_trading.strategies.inverse.live import WEAK_KIND, WEAK_TP
from kiwoom_trading.strategies.regime_plays.live import NEWHIGH_KIND
from kiwoom_trading.strategies.resistance_retest.live import RETEST_KIND, RETEST_TP

TAG = "💰"
BOOK = "10만 원"
START_CASH = 100_000
KINDS = (NEWHIGH_KIND, RETEST_KIND, WEAK_KIND)
TP = {NEWHIGH_KIND: None, RETEST_KIND: RETEST_TP, WEAK_KIND: WEAK_TP}
ETF_CODES = {"123310"}
MAX_CHASE = 0.01
OPEN, LAST_BUY, CLOSE, REPORT_AT = time(9, 0), time(15, 19), time(15, 30), time(15, 40)


def _cost(code: str) -> float:
    return 0.0005 if code in ETF_CODES else 0.0025


def _plan(price: float, stop: Optional[float], tp: Optional[float]) -> Plan:
    return Plan(stop=stop, target=price * (1 + tp) if tp else None, next_day=True, until=LAST_BUY.strftime("%H:%M"), target_fill="price")


class SmallAccount:
    def __init__(self, store, market, today, notify: Optional[Callable[[str], object]] = None) -> None:
        self.conn = store.conn
        self.market = market
        self.today = today
        self.notify = notify or (lambda text: None)
        self.ledger = Ledger(self.conn, BOOK, TAG, today, START_CASH, slots=1, notify=self.notify, cost_of=_cost)
        self._migrate()
        self.reported = self.ledger.reported()

    def _migrate(self) -> None:
        """예전 표 small_trades → 공용 장부 (장부에 아직 아무 거래도 없을 때 한 번)."""
        if self.conn.execute("SELECT count(*) FROM ledger_trades WHERE book = ?", [BOOK]).fetchone()[0]:
            return
        try:
            rows = self.conn.execute("""SELECT id, date, code, name, kind, buy_ts, buy_price, qty, stop, tp, sell_ts, sell_price, reason, pnl, status
                                        FROM small_trades""").fetchall()
        except Exception:
            return                                   # 예전 표 없음
        for tid, d, code, name, kind, bts, bp, qty, stop, tp, sts, sp, reason, pnl, status in rows:
            self.conn.execute("""INSERT OR REPLACE INTO ledger_trades (id, book, date, code, name, buy_ts, buy_price, qty, plan, part_qty,
                                 sell_ts, sell_price, reason, pnl, status, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                              [f"{tid}-{BOOK}", BOOK, d, code, name, bts, bp, qty, _plan(bp, stop, tp).dumps(), sts, sp, reason, pnl, status,
                               f"[{kind}] small_trades 에서 옮김"])
        if rows:
            logging.info("10만 원 계좌: 예전 표 small_trades %s건을 공용 장부로 옮김", len(rows))

    # ------------------------------------------------------------ 상태 (예전 이름 유지)
    def cash(self) -> float:
        return self.ledger.cash()

    def open_trade(self) -> Optional[tuple]:
        """(id, date, code, name, kind, buy_ts, buy_price, qty, stop, tp) — 예전 모양."""
        t = next(iter(self.ledger.open_trades()), None)
        if not t:
            return None
        plan = Plan.loads(t["plan"])
        kind = (t["note"] or "").split("]")[0].lstrip("[") if (t["note"] or "").startswith("[") else ""
        tp = plan.target / t["buy_price"] - 1 if plan.target else None
        return (t["id"], t["date"], t["code"], t["name"], kind, t["buy_ts"], t["buy_price"], t["qty"], plan.stop, tp)

    def bought_today(self) -> bool:
        return self.ledger.bought_today()

    # ------------------------------------------------------------ 매수
    def on_signals(self, now: datetime, items) -> None:
        tm = now.time()
        if not (OPEN <= tm < LAST_BUY) or self.ledger.open_trades() or self.bought_today():
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
            self.ledger.buy(now, code, name, price, _plan(price, stop, tp), qty=qty, note=f"[{s.kind}] {s.ts:%H:%M} 신호"
                            + "".join(f"\n{l}" for l in (getattr(s, "reason", "") or "").splitlines() if "🇺🇸" in l))
            return

    # ------------------------------------------------------------ 매도
    def tick(self, now: datetime) -> None:
        self.ledger.manage(now, price_source(self.market, ()))
        if now.time() >= REPORT_AT and not self.reported:
            self.reported = True
            self.ledger.mark_reported()
            self.notify(self.summary())

    def summary(self) -> str:
        return f"💰 10만 원 계좌 {self.today:%m-%d} 마감\n" + self.ledger.summary_line()
