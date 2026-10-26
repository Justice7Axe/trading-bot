"""가상 장부 하나 — 주문 없이 매매를 기록하는 공용 장부 (docs/architecture.md 4단계, 2026-10-27).

매매법은 '언제·무엇을·얼마에 사고, 어떻게 팔지(Plan)'만 정하고, 잔고·매도·손익·알림·마감 요약은 여기서 한다.
표: ledger_trades (장부 이름 book 칸), ledger_days. 장부 = 이름·시작 금액·하루 종목 수·건당 비율.

매도 계획(Plan) — 매분 manage() 가 가격을 보고 판단 (같은 확인에서 손절이 먼저):
  stop       이 가격 이하 → 남은 전부 매도 (손절)
  half_at    이 가격 이상 → 절반 매도 (한 번)
  target     이 가격 이상 → 남은 전부 매도 (익절 · '하락폭 절반 회복' 등)
  next_day   그날 못 팔면 다음 날 09:00 첫 확인 가격에 매도
  session    'regular' = 정규장(09:00~15:30) KRX 가격으로 관리 / 'after' = 애프터(15:40~until) 통합 가격으로 관리
비용 0.25% (매수 금액 기준, 백테스트와 같음).
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from typing import Callable, Optional

COST = 0.0025
OPEN, CLOSE = time(9, 0), time(15, 30)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_trades (     -- 가상 장부 (주문 없음) — 매매법·장부별 book
    id VARCHAR PRIMARY KEY, book VARCHAR, date DATE, code VARCHAR, name VARCHAR,
    buy_ts TIMESTAMP, buy_price DOUBLE, qty INTEGER, plan VARCHAR,
    part_ts TIMESTAMP, part_qty INTEGER, part_price DOUBLE,
    sell_ts TIMESTAMP, sell_price DOUBLE, reason VARCHAR, pnl DOUBLE, status VARCHAR, note VARCHAR
);
CREATE TABLE IF NOT EXISTS ledger_days (book VARCHAR, date DATE, reported BOOLEAN, note VARCHAR, PRIMARY KEY (book, date));
"""


@dataclass
class Plan:
    stop: Optional[float] = None
    half_at: Optional[float] = None
    target: Optional[float] = None
    next_day: bool = True
    session: str = "regular"            # 'regular' / 'after'
    until: Optional[str] = None          # 'HH:MM' — 그날 손절·익절을 보는 마지막 시각 (regular 기본 15:30 전, after 기본 19:55)
    target_fill: str = "target"          # 'target' = 목표가에 매도 / 'price' = 닿은 때의 가격에 매도 (💰 10만 원 계좌)

    def dumps(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def loads(s: Optional[str]) -> "Plan":
        return Plan(**json.loads(s)) if s else Plan()

    def describe(self) -> str:
        parts = []
        if self.stop:
            parts.append(f"손절 {self.stop:,.0f}")
        if self.half_at:
            parts.append(f"{self.half_at:,.0f} 닿으면 절반")
        if self.target:
            parts.append(f"목표 {self.target:,.0f}")
        if not parts:
            parts.append("손절·익절 없음")
        if self.next_day:
            parts.append("아니면 다음 날 09:00")
        return " · ".join(parts)


def price_source(market, value_top=()) -> Callable[[str, bool], Optional[float]]:
    """지금 가격 함수: 정규장은 이번 분 대금 순위 가격(없으면 KRX 시세 조회), 애프터는 통합(NXT) 시세 조회. 같은 분 같은 조회는 한 번."""
    px = {r.code: float(r.price) for r in value_top if getattr(r, "price", None)}
    cache: dict = {}

    def price_of(code: str, integrated: bool = False) -> Optional[float]:
        if not integrated and code in px:
            return px[code]
        key = (code, integrated)
        if key not in cache:
            try:
                q = market.quote(code, integrated=integrated)
                cache[key] = float(q.price) if q and q.price else None
            except Exception:
                logging.warning("가상 장부: %s 시세 조회 실패", code)
                cache[key] = None
        return cache[key]
    return price_of


class Ledger:
    """장부 하나. 같은 표를 여러 장부가 함께 쓴다 (book 칸으로 구분)."""

    def __init__(self, conn, book: str, tag: str, today: date, start_cash: float = 10_000_000, slots: int = 3,
                 notify: Optional[Callable[[str], object]] = None, cost_of: Optional[Callable[[str], float]] = None) -> None:
        self.conn = conn
        self.book = book
        self.tag = tag
        self.today = today
        self.start_cash = start_cash
        self.slots = slots
        self.notify = notify or (lambda text: None)
        self.cost_of = cost_of or (lambda code: COST)     # 왕복 비용 (ETF 0.05% 등 장부별로)
        self.conn.execute(SCHEMA)

    # ------------------------------------------------------------ 상태
    def cash(self) -> float:
        return self.start_cash + (self.conn.execute("SELECT coalesce(sum(pnl), 0) FROM ledger_trades WHERE status = 'closed' AND book = ?",
                                                    [self.book]).fetchone()[0] or 0)

    def open_trades(self) -> list[dict]:
        cols = ("id", "date", "code", "name", "buy_ts", "buy_price", "qty", "plan", "part_qty", "part_price", "note")
        rows = self.conn.execute(f"SELECT {', '.join(cols)} FROM ledger_trades WHERE status = 'open' AND book = ? ORDER BY buy_ts",
                                 [self.book]).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def bought_today(self, code: Optional[str] = None) -> bool:
        q = "SELECT count(*) FROM ledger_trades WHERE date = ? AND book = ?" + (" AND code = ?" if code else "")
        return bool(self.conn.execute(q, [self.today, self.book] + ([code] if code else [])).fetchone()[0])

    def n_today(self) -> int:
        return self.conn.execute("SELECT count(*) FROM ledger_trades WHERE date = ? AND book = ?", [self.today, self.book]).fetchone()[0]

    def full(self) -> bool:
        return self.n_today() >= self.slots

    def reported(self) -> bool:
        r = self.conn.execute("SELECT reported FROM ledger_days WHERE book = ? AND date = ?", [self.book, self.today]).fetchone()
        return bool(r and r[0])

    def mark_reported(self, note: str = "") -> None:
        self.conn.execute("INSERT OR REPLACE INTO ledger_days VALUES (?, ?, ?, ?)", [self.book, self.today, True, note])

    # ------------------------------------------------------------ 매수
    def buy(self, now: datetime, code: str, name: str, price: float, plan: Plan, note: str = "",
            qty: Optional[int] = None, extra: str = "", quiet: bool = False) -> Optional[str]:
        """잔고 ÷ slots 만큼(정수 주) 가상 매수. 하루 종목 수가 찼거나 오늘 이미 산 종목이면 안 산다."""
        if self.full() or self.bought_today(code):
            return None
        cash = self.cash()
        qty = qty if qty is not None else int(cash / self.slots // price)
        if qty < 1:
            return None
        tid = f"{now:%Y%m%d}-{code}-{self.book}"
        self.conn.execute("""INSERT OR REPLACE INTO ledger_trades (id, book, date, code, name, buy_ts, buy_price, qty, plan, part_qty, status, note)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'open', ?)""",
                          [tid, self.book, self.today, code, name, now.replace(tzinfo=None), float(price), qty, plan.dumps(), note])
        if not quiet:     # 매매법이 여러 종목을 묶어 따로 알리면 quiet
            self.notify(f"{self.tag}·{self.book} 가상 매수 {name}({code}) {qty}주 × {price:,.0f}원 — {note}{extra}\n"
                        f"  {plan.describe()} (주문 없는 가상 기록, 잔고 {cash:,.0f}원)")
        logging.info("%s·%s 가상 매수 %s %s × %s — %s", self.tag, self.book, name, qty, price, note)
        return tid

    # ------------------------------------------------------------ 매도
    def manage(self, now: datetime, price_of: Callable[[str, bool], Optional[float]]) -> None:
        """price_of(code, integrated) → 지금 가격. 정규장 KRX(False) / 애프터 통합(True)."""
        tm = now.time()
        for t in self.open_trades():
            plan = Plan.loads(t["plan"])
            buy, qty, part = t["buy_price"], t["qty"], t["part_qty"] or 0
            if t["date"] < self.today:
                if plan.next_day and OPEN <= tm < CLOSE:
                    p = price_of(t["code"], False)
                    if p:
                        self._close(now, t, p, "다음 날 09:00 매도")
                continue
            if plan.session == "after":
                if not (time(15, 40) <= tm <= (time.fromisoformat(plan.until) if plan.until else time(19, 55))):
                    continue
                p = price_of(t["code"], True)
            else:
                if not (OPEN <= tm < (time.fromisoformat(plan.until) if plan.until else CLOSE)):
                    continue
                p = price_of(t["code"], False)
            if not p:
                continue
            if plan.stop and p <= plan.stop:
                self._close(now, t, p, "손절")
            elif plan.target and p >= plan.target:
                self._close(now, t, p if plan.target_fill == "price" else plan.target, "목표가")
            elif plan.half_at and not part and p >= plan.half_at and qty >= 2:
                h = qty // 2
                self.conn.execute("UPDATE ledger_trades SET part_ts = ?, part_qty = ?, part_price = ? WHERE id = ?",
                                  [now.replace(tzinfo=None), h, float(plan.half_at), t["id"]])
                self.notify(f"{self.tag}·{self.book} {t['name']} {plan.half_at:,.0f} → 절반 {h}주 매도 ({plan.half_at / buy - 1 - self.cost_of(t['code']):+.2%}), "
                            f"나머지 {qty - h}주 {'다음 날 09:00' if plan.next_day else '계속 관리'} (가상)")

    def _close(self, now: datetime, t: dict, price: float, reason: str) -> None:
        buy, qty, part = t["buy_price"], t["qty"], t["part_qty"] or 0
        rest = qty - part
        pnl = part * ((t["part_price"] or buy) - buy) + rest * (price - buy) - qty * buy * self.cost_of(t["code"])
        self.conn.execute("UPDATE ledger_trades SET sell_ts = ?, sell_price = ?, reason = ?, pnl = ?, status = 'closed' WHERE id = ?",
                          [now.replace(tzinfo=None), float(price), reason, pnl, t["id"]])
        part_txt = f" (절반 {part}주는 {t['part_price']:,.0f})" if part else ""
        self.notify(f"{self.tag}·{self.book} 매도 {t['name']}({t['code']}) {rest}주 × {price:,.0f}원 — {reason}{part_txt}"
                    f", 합계 {pnl / (qty * buy):+.2%} ({pnl:+,.0f}원) → 잔고 {self.cash():,.0f}원 (시작 대비 {self.cash() / self.start_cash - 1:+.1%}, 가상)")
        logging.info("%s·%s 매도 %s %s — %s, %+.0f원", self.tag, self.book, t["name"], price, reason, pnl)

    # ------------------------------------------------------------ 요약
    def summary_line(self) -> str:
        n, w = self.conn.execute("SELECT count(*), count(*) FILTER (WHERE pnl > 0) FROM ledger_trades WHERE status='closed' AND book = ?",
                                 [self.book]).fetchone()
        held = self.open_trades()
        hold = ", ".join(f"{h['name']} {h['qty'] - (h['part_qty'] or 0)}주" for h in held) or "없음"
        cash = self.cash()
        return f"  {self.book}: 잔고 {cash:,.0f}원 (시작 대비 {cash / self.start_cash - 1:+.1%}), 끝난 매매 {n}건 중 수익 {w}건, 보유 {hold}"
