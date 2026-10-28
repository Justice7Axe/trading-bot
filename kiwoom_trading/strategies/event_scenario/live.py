"""📅 [일정] 일정 시나리오 가상 장부 — DART 공시 사건을 보고 09:00 에 사고 정해진 날 09:00 에 판다 (주문 없음, 2026-10-29 사용자 '추천대로').

백테스트(backtest.py, 2024-11~2026-10 일봉)에서 시장 대비로도 ★ 였던 네 가지만, 장부 하나씩 (각 1천만, 종목당 잔고 ÷ 5):
  무상 권리락   무상증자 신주배정 기준일로 권리락일을 구해, 권리락 전 거래일 09:00 매수 → 권리락일 09:00 매도   67건 +7.9%/건
  무상증자      무상증자 결정 공시 다음 거래일 09:00 매수 → 5거래일 보유 뒤 09:00 매도                          78건 +4.9%
  자사주 신탁   자기주식취득 신탁계약 체결 공시 → 같은 방식 5거래일                                              262건 +1.8%
  고배당 결정   현금배당 결정 중 시가배당률 4%↑ → 같은 방식 5거래일                                             179건 +1.5%
  (모두 손절·익절 없음 — 백테스트에서 손절을 붙이면 나빠짐. 비용 0.25%)

백테스트와 같게 맞춘 것:
  · '공시 날' = 접수일 이후 첫 거래일 (주말 공시는 월요일) → 그다음 거래일 09:00 에 산다. 그래서 08:00 에 접수일이 전 거래일(또는 그 뒤 휴일)인 것만 산다.
  · 대상: 보통주, 전 거래일 대금 ≥ 10억·시총 ≥ 500억, 정정·자회사 공시 제외, 같은 장부·종목 10거래일 안 중복 제외.
  · 보유 일수 = 매수일부터 센 거래일 (일봉 달력 + 오늘).
앞날 달력: 권리락일은 기준일에서 거꾸로 세야 해서 평일 − 아래 HOLIDAYS 로 짐작한다 (틀리면 하루 어긋남 → 알림에 권리락일을 같이 보인다).
⚠️ 상승장 2년 결과이고 9-14 뒤 몇 건은 손실 → 이 장부로 20~30건 쌓아 실전 여부를 정한다 (스킬 event-scenario).
"""
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

import duckdb

from kiwoom_trading.execution.ledger import Ledger, Plan, price_source

TAG = "📅 [일정]"
START_CASH = 10_000_000
SLOTS = 5
HOLD = 5
FETCH_AT, BUY_AT, BUY_UNTIL, REPORT_AT = time(8, 0), time(9, 0), time(9, 10), time(15, 40)
MIN_VALUE, MIN_CAP = 1e9, 5e10
BOOKS = {"ex": "무상 권리락", "bonus": "무상증자", "trust": "자사주 신탁", "div": "고배당 결정"}
KIND_OF = {"bonus": "bonus", "trust": "buyback_trust", "div": "dividend"}
# KRX 휴장일 (주말 제외) — 앞날 권리락일 짐작용. 해마다 거래소 공지로 고친다.
HOLIDAYS = {date(2026, 12, 25), date(2026, 12, 31), date(2027, 1, 1), date(2027, 2, 8), date(2027, 2, 9), date(2027, 3, 1),
            date(2027, 5, 5), date(2027, 5, 13), date(2027, 6, 3), date(2027, 8, 16), date(2027, 9, 14), date(2027, 9, 15),
            date(2027, 9, 16), date(2027, 10, 4), date(2027, 10, 11), date(2027, 12, 31)}


@dataclass
class EventContext:
    today: date
    cal: list                                   # 지난 거래일 (일봉 달력, 오늘 전까지)
    univ: dict = field(default_factory=dict)    # code → (name, 전날 대금, 전날 시총)


def load_event_context(conn, today: date) -> EventContext:
    cal = [d for (d,) in conn.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' AND date < ? ORDER BY 1",
                                      [today]).fetchall()]
    if not cal:
        return EventContext(today, [])
    rows = conn.execute("""SELECT d.code, s.name, d.value, d.close * s.listed_shares FROM daily_ohlcv d JOIN stocks s USING(code)
                           WHERE d.date = ?""", [cal[-1]]).fetchall()
    return EventContext(today, cal, {c: (n, v or 0, m or 0) for c, n, v, m in rows})


def is_trading(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def next_trading(d: date, n: int = 1) -> date:
    while n:
        d += timedelta(days=1)
        if is_trading(d): n -= 1
    return d


def ex_date(record: date, cal: list, today: date) -> Optional[date]:
    """권리·배당락일 = 기준일 이전 마지막 거래일의 전 거래일 (backtest.ex_date 와 같음). 지난 날은 일봉 달력, 앞날은 평일 − 휴장일."""
    past = set(cal) | {today}
    def trading(d): return d in past if d <= today else is_trading(d)
    d = record
    for _ in range(15):
        if trading(d): break
        d -= timedelta(days=1)
    else:
        return None
    d -= timedelta(days=1)
    for _ in range(15):
        if trading(d): return d
        d -= timedelta(days=1)
    return None


class EventScenarioBooks:
    def __init__(self, store, market, today: date, ctx: EventContext, notify: Optional[Callable[[str], object]] = None,
                 events_db: Optional[str] = None, fetch: Optional[Callable] = None) -> None:
        from kiwoom_trading.ingestion.collectors import dart_events
        self.conn = store.conn
        self.market = market
        self.today = today
        self.ctx = ctx
        self.notify = notify or (lambda text: None)
        self.events_db = events_db or dart_events.DB
        self.fetch = fetch or dart_events.fetch_recent
        self.books = {k: Ledger(self.conn, f"일정 {v}", TAG, today, START_CASH, SLOTS, notify=self.notify) for k, v in BOOKS.items()}
        self.ready = False
        self.thread: Optional[threading.Thread] = None
        self.picks: list = []                   # (key, code, name, note, sell_rule)
        self.bought = False
        self.reported = False
        self.prev = ctx.cal[-1] if ctx.cal else None

    # ------------------------------------------------------------ 08:00 공시 받기 (따로 도는 스레드 — 1분 확인을 막지 않게)
    def _prepare(self) -> None:
        try:
            a = (self.prev or self.today) - timedelta(days=10)
            n = self.fetch(a, self.today, ["bonus", "buyback_trust", "dividend"], db=self.events_db)
            logging.info("일정 가상 장부: DART %s~%s 받음, 새 원문 %s건", a, self.today, n)
        except Exception:
            logging.exception("일정 가상 장부: DART 공시 받기 실패 — 전에 쌓인 공시로만 판단")
        try:
            self.picks = self._select()
            logging.info("일정 가상 장부 오늘 대상 %s건: %s", len(self.picks), ", ".join(f"{BOOKS[k]} {n}" for k, _, n, _, _ in self.picks))
        except Exception:
            logging.exception("일정 가상 장부: 대상 고르기 실패")
        self.ready = True

    def _event_day(self, d: date) -> Optional[date]:
        """접수일 → 그 뒤 첫 거래일 (백테스트 trade_day)."""
        past = set(self.ctx.cal) | {self.today}
        for _ in range(10):
            if (d in past) if d <= self.today else is_trading(d):
                return d
            d += timedelta(days=1)
        return None

    def _ok(self, code: str) -> Optional[str]:
        if code[-1] in "579K": return "우선주"
        u = self.ctx.univ.get(code)
        if not u: return "전날 일봉 없음"
        if u[1] < MIN_VALUE: return f"전날 대금 {u[1] / 1e8:.0f}억 < 10억"
        if u[2] < MIN_CAP: return f"시총 {u[2] / 1e8:.0f}억 < 500억"
        return None

    def _recent(self, key: str, code: str) -> bool:
        return bool(self.conn.execute("SELECT count(*) FROM ledger_trades WHERE book = ? AND code = ? AND date >= ?",
                                      [self.books[key].book, code, self.today - timedelta(days=14)]).fetchone()[0])

    def _select(self) -> list:
        ev = duckdb.connect(self.events_db, read_only=True)
        try:
            rows = ev.execute("""SELECT d.rcept_dt, d.code, d.corp_name, d.kind, d.title, e.yield_pct, e.record, e.per_share
                FROM disclosures d LEFT JOIN event_details e USING(rcept_no)
                WHERE d.kind IN ('bonus','buyback_trust','dividend') AND NOT d.fixed AND d.title NOT LIKE '%자회사%'
                  AND d.rcept_dt >= ? ORDER BY d.rcept_dt, d.rcept_no""", [self.today - timedelta(days=90)]).fetchall()
        finally:
            ev.close()
        picks, seen = [], set()
        for rdt, code, name, kind, title, yld, record, ps in rows:
            day = self._event_day(rdt)
            # 따라가기: 공시 날 = 전 거래일 → 오늘 09:00 매수
            if day == self.prev:
                key = {"bonus": "bonus", "buyback_trust": "trust", "dividend": "div"}[kind]
                if key == "div" and not (yld or 0) >= 4:
                    continue
                note = {"bonus": f"무상증자 결정 (1주당 {ps or '?'}주)", "trust": "자사주 신탁 계약",
                        "div": f"현금배당 결정 시가배당률 {yld:.1f}%" if yld else "현금배당"}[key]
                picks.append((key, code, name, f"{note} · 공시 {rdt:%m-%d}", ("hold", HOLD)))
            # 사두기: 무상증자 권리락 전 거래일 = 오늘 → 오늘 09:00 매수, 권리락일 09:00 매도
            if kind == "bonus" and record and day and day < self.today:
                ex = ex_date(record, self.ctx.cal, self.today)
                if ex and ex > self.today and next_trading(self.today) == ex and (code, ex) not in seen:
                    seen.add((code, ex))
                    picks.append(("ex", code, name, f"무상증자 권리락 {ex:%m-%d} (기준일 {record:%m-%d}, 1주당 {ps or '?'}주)", ("ex", ex)))
        out = []
        for p in picks:
            why = self._ok(p[1])
            if why:
                logging.info("일정 가상 장부: %s %s 대상 아님 (%s)", BOOKS[p[0]], p[2], why)
                continue
            out.append(p)
        return out

    # ------------------------------------------------------------ 1분마다
    def tick(self, now: datetime, value_top=()) -> None:
        tm = now.time()
        if tm >= FETCH_AT and self.thread is None:
            self.thread = threading.Thread(target=self._prepare, name="event-scenario", daemon=True)
            self.thread.start()
        if BUY_AT <= tm < time(15, 30):
            self._sell(now, value_top)
        if BUY_AT <= tm <= BUY_UNTIL and self.ready and not self.bought:
            self.bought = True
            self._buy(now, value_top)
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            sink = getattr(self, "summary_sink", None)
            if any(b.open_trades() or b.bought_today() for b in self.books.values()):
                (sink.append if sink is not None else self.notify)(self.summary())

    def _held_days(self, buy_day: date) -> int:
        return sum(1 for d in self.ctx.cal if d >= buy_day) + 1          # 매수일 포함, 오늘까지

    def _sell(self, now: datetime, value_top) -> None:
        px = price_source(self.market, value_top)
        for key, lg in self.books.items():
            for t in lg.open_trades():
                if t["date"] >= self.today:
                    continue
                m = re.search(r"\[(ex|hold)=([^\]]+)\]", t["note"] or "")
                if not m:
                    continue
                due = (self.today >= date.fromisoformat(m[2])) if m[1] == "ex" else (self._held_days(t["date"]) > int(m[2]))
                if not due:
                    continue
                p = px(t["code"], False)
                if p:
                    lg._close(now, t, p, "권리락일 09:00 매도" if m[1] == "ex" else f"{m[2]}거래일 보유 뒤 09:00 매도")

    def _buy(self, now: datetime, value_top) -> None:
        if not self.picks:
            return
        px = price_source(self.market, value_top)
        lines, miss = [], []
        for key, code, name, note, rule in self.picks:
            lg = self.books[key]
            if lg.bought_today(code):          # 실행기를 다시 켠 경우
                continue
            if self._recent(key, code):
                logging.info("일정 가상 장부: %s %s 10거래일 안 같은 종목 → 안 삼", BOOKS[key], name); continue
            p = px(code, False)
            if not p:
                miss.append(f"  {BOOKS[key]} {name}({code}): 시세 못 받음"); continue
            tag = f"[ex={rule[1]}]" if rule[0] == "ex" else f"[hold={rule[1]}]"
            qty = int(lg.cash() / SLOTS // p)
            tid = lg.buy(now, code, name, p, Plan(next_day=False), note=f"{note} {tag}", qty=qty, quiet=True)
            if not tid:
                miss.append(f"  {BOOKS[key]} {name}({code}): " + ("오늘 5종목 다 참" if lg.full() else "1주도 못 삼" if qty < 1 else "오늘 이미 삼"))
                continue
            sell = f"권리락일 {rule[1]:%m-%d} 09:00 매도" if rule[0] == "ex" else f"{rule[1]}거래일 뒤 09:00 매도"
            lines.append(f"  {BOOKS[key]} · {name}({code}) {qty}주 × {p:,.0f}원 — {note}\n     → {sell} (손절·익절 없음)")
        if lines or miss:
            self.notify(f"{TAG} 가상 매수 {now:%m-%d %H:%M} (장부마다 1천만, 종목당 1/{SLOTS}, 주문 없음)\n" + "\n".join(lines)
                        + (("\n⏭ 대상인데 못 삼\n" + "\n".join(miss)) if miss else "")
                        + "\n  근거: 2년 백테스트 시장 대비 ★ (권리락 +7.9% · 무상 +4.9% · 신탁 +1.8% · 고배당 +1.5%/건)")

    def summary(self) -> str:
        return f"{TAG} 일정 시나리오 가상 장부 {self.today:%m-%d}\n" + "\n".join(b.summary_line() for b in self.books.values())
