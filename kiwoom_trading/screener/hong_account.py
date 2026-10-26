"""📕 [홍인기] 상한가 풀림 매수 — 1천만 원 가상 계좌 두 장부 (키움 모의·실계좌와 별도 기록, 주문 없음).
(2026-10-27 사용자: 홍인기 매매일지 10-26 루닛 상따를 '홍인기 매매 전략'으로 프로그래밍·스킬화, 스킬 hong)

규칙 (indicators/hong.py 와 같은 숫자, 1년 백테스트 run_hong_backtest.py):
  대상 = 매분 받는 KRX 거래대금 상위 200 중 상한가(기준가 × 1.3, 호가 단위 내림)에 닿은 **첫 상한가** 종목
         (전날 상한가였던 종목 제외 — 2연상 이후 1년 건당 −0.95%).
  상한가에 MIN_LOCK(5)분 이상 잠겼다가(매분 확인 가격 = 상한가) 풀리면(가격 < 상한가) 그 가격에 가상 매수.
  장부 두 개 (각 1천만, 하루 SLOTS 종목, 종목당 잔고 ÷ SLOTS, 종목당 하루 1번):
    '수급 확인' = 홍인기 원칙: 그 시각까지 나온 기관 가집계 순매수 > 0 이고 프로그램 순매수 > 0 일 때만
                 (일지: 9:52 2차 가집계 기관 +20.1만 주·프로그램 9:22부터 매수 확인 뒤 비중 낮춰 매수).
                 기관 가집계는 보통 09:50 무렵 처음 나오고, 기관이 거래한 약 500종목만 온다 → 작은 종목은 대부분 못 삼.
    '수급 없이' = 1년 백테스트 규칙 그대로 (5분↑ 잠김 + 호가 2칸 비싸게 잡아도 건당 +1.14%, 앞·뒤 기간 모두 +).
  매도: 다시 상한가 닿으면 절반을 상한가에, 나머지는 다음 날 09:00 첫 확인 가격. 손절 없음(1년: −5% 손절은 나빠짐). 비용 0.25%.
모든 풀림(산 것·안 산 것)을 hg_events 에 수급과 함께 남긴다 → 수급 조건 검증용 (과거 장중 수급은 조회가 안 돼 쌓아야 함).
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from kiwoom_trading.analysis.indicators.hong import upper_limit

TAG = "📕 [홍인기]"
BOOKS = ("수급 확인", "수급 없이")
START_CASH = 10_000_000
SLOTS = 3
MIN_LOCK = 5           # 풀리기 전 상한가에 잠긴 분 수 (매분 확인 가격 = 상한가인 횟수)
COST = 0.0025
BUY_FROM, BUY_UNTIL = time(9, 0), time(15, 0)
OPEN, CLOSE, REPORT_AT = time(9, 0), time(15, 30), time(15, 40)
WATCH_CHG = 0.25       # 이 등락률부터 기준가를 받아 상한가를 계산해 둔다
FLOW_WAIT_MIN = 6      # 풀렸는데 기관 가집계가 아직 없으면 이만큼 기다림 (가집계는 5분마다 저장 → 09:52 발표가 09:56 에 들어옴)

SCHEMA = """
CREATE TABLE IF NOT EXISTS hg_trades (     -- 📕 홍인기 상한가 풀림 1천만 원 가상 계좌 (주문 없음)
    id          VARCHAR PRIMARY KEY,
    book        VARCHAR,       -- 수급 확인 / 수급 없이
    date        DATE,
    code        VARCHAR,
    name        VARCHAR,
    buy_ts      TIMESTAMP,
    buy_price   DOUBLE,
    qty         INTEGER,
    limit_price DOUBLE,
    half_ts     TIMESTAMP,     -- 다시 상한가 닿아 절반 판 시각
    half_qty    INTEGER,
    sell_ts     TIMESTAMP,
    sell_price  DOUBLE,        -- 나머지 판 가격
    reason      VARCHAR,
    pnl         DOUBLE,
    status      VARCHAR        -- open / closed
);
CREATE TABLE IF NOT EXISTS hg_events (     -- 상한가 풀림마다 (산 것·안 산 것) — 수급 조건 검증용
    date DATE, ts TIMESTAMP, code VARCHAR, name VARCHAR, price DOUBLE, limit_price DOUBLE, locked_min INTEGER,
    inst DOUBLE, foreign_ DOUBLE, program DOUBLE, decision VARCHAR
);
CREATE TABLE IF NOT EXISTS hg_days (date DATE PRIMARY KEY, reported BOOLEAN, note VARCHAR);
"""


def load_prev_limitups(conn, today: date) -> set[str]:
    """전 거래일 상한가(종가 기준 +29%↑) 종목 — 일봉 DB 에서. 9-14 이후 일봉 종가는 애프터 종가라 +29% 로 넉넉히 본다."""
    rows = conn.execute("""
        WITH d AS (SELECT code, date, close, lag(close) OVER (PARTITION BY code ORDER BY date) AS pc
                   FROM daily_ohlcv WHERE date >= ? - INTERVAL 15 DAY AND date < ?)
        SELECT code FROM d WHERE date = (SELECT max(date) FROM d) AND pc > 0 AND close / pc - 1 >= 0.29""", [today, today]).fetchall()
    return {r[0] for r in rows}


class HongAccount:
    def __init__(self, store, market, today: date, prev_limitups: Optional[set] = None,
                 notify: Optional[Callable[[str], object]] = None) -> None:
        self.conn = store.conn
        self.market = market
        self.today = today
        self.prev_limitups = prev_limitups or set()
        self.notify = notify or (lambda text: None)
        self.conn.execute(SCHEMA)
        row = self.conn.execute("SELECT reported FROM hg_days WHERE date = ?", [today]).fetchone()
        self.reported = bool(row and row[0])
        self.limits: dict[str, int] = {}      # code → 상한가
        self.names: dict[str, str] = {}
        self.locked: dict[str, int] = {}      # code → 지금 연속으로 상한가인 분 수
        self.touched: set[str] = set()
        self.wait: dict[str, datetime] = {}   # '수급 확인' 장부: 가집계 기다리는 종목 → 기다림 끝 시각

    # ------------------------------------------------------------ 상태
    def cash(self, book: str) -> float:
        return START_CASH + (self.conn.execute("SELECT coalesce(sum(pnl), 0) FROM hg_trades WHERE status = 'closed' AND book = ?",
                                               [book]).fetchone()[0] or 0)

    def open_trades(self) -> list[tuple]:
        return self.conn.execute("""SELECT id, book, date, code, name, buy_price, qty, limit_price, half_qty FROM hg_trades
                                    WHERE status = 'open' ORDER BY buy_ts""").fetchall()

    def bought_today(self, book: str) -> set[str]:
        return {c for (c,) in self.conn.execute("SELECT code FROM hg_trades WHERE date = ? AND book = ?", [self.today, book]).fetchall()}

    def flow(self, code: str, now: datetime):
        """지금까지 저장된 오늘 마지막 기관·외국인 가집계, 프로그램 순매수 (원). 없으면 None."""
        ts = now.replace(tzinfo=None)
        q = """SELECT net_amount FROM investor_intraday WHERE date = ? AND code = ? AND investor = ? AND ts <= ?
               ORDER BY ts DESC LIMIT 1"""
        inst = self.conn.execute(q, [self.today, code, "institution", ts]).fetchone()
        fo = self.conn.execute(q, [self.today, code, "foreign", ts]).fetchone()
        pg = self.conn.execute("""SELECT net_amount FROM program_intraday WHERE date = ? AND code = ? AND ts <= ?
                                  ORDER BY ts DESC LIMIT 1""", [self.today, code, ts]).fetchone()
        return (inst[0] if inst else None), (fo[0] if fo else None), (pg[0] if pg else None)

    # ------------------------------------------------------------ 매분
    def tick(self, now: datetime, value_top=()) -> None:
        tm = now.time()
        if OPEN <= tm < CLOSE:
            self._manage(now, value_top)
            if BUY_FROM <= tm <= BUY_UNTIL:
                self._watch(now, value_top)
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            self.conn.execute("INSERT OR REPLACE INTO hg_days VALUES (?, ?, ?)", [self.today, True, self._today_note()])
            self.notify(self.summary())

    def _watch(self, now: datetime, value_top) -> None:
        for r in value_top:
            if r.change_rate is None or r.price is None or r.change_rate < WATCH_CHG:
                continue
            code = r.code
            self.names[code] = r.name
            if code not in self.limits:
                try:
                    q = self.market.quote(code, integrated=False)
                except Exception:
                    logging.warning("홍인기 계좌: %s 시세 조회 실패", code)
                    continue
                if not q or not q.base_price:
                    continue
                self.limits[code] = upper_limit(float(q.base_price))
            lim = self.limits[code]
            price = float(r.price)
            if price >= lim:
                self.touched.add(code)
                self.locked[code] = self.locked.get(code, 0) + 1
                continue
            run = self.locked.get(code, 0)
            self.locked[code] = 0
            if code in self.touched and run >= MIN_LOCK:
                self._on_break(now, code, price, lim, run)
            elif code in self.wait and now <= self.wait[code] and self.flow(code, now)[0] is not None:
                self.wait.pop(code)             # 기다리던 가집계가 들어왔고 아직 상한가 아래 → '수급 확인' 장부만 다시 판단
                self._on_break(now, code, price, lim, run, books=("수급 확인",))

    def _decide(self, book: str, code: str, inst, pg) -> str:
        if code in self.prev_limitups:
            return "2연상 이후 제외"
        if code in self.bought_today(book):
            return "이미 삼"
        if book == "수급 확인":
            if inst is None:
                return "기관 가집계 없음"
            if inst <= 0:
                return "기관 순매도"
            if pg is None or pg <= 0:
                return "프로그램 순매도·없음"
        if len(self.bought_today(book)) >= SLOTS:
            return f"오늘 {SLOTS}종목 다 참"
        return "매수"

    def _on_break(self, now: datetime, code: str, price: float, lim: int, run: int, books=BOOKS) -> None:
        inst, fo, pg = self.flow(code, now)
        name = self.names.get(code, code)
        decisions = {b: self._decide(b, code, inst, pg) for b in books}
        if decisions.get("수급 확인") == "기관 가집계 없음" and now > self.wait.get(code, datetime.min.replace(tzinfo=now.tzinfo)):
            self.wait[code] = now + timedelta(minutes=FLOW_WAIT_MIN)
            decisions["수급 확인"] = f"기관 가집계 없음 → {FLOW_WAIT_MIN}분 기다림"
        self.conn.execute("INSERT INTO hg_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          [self.today, now.replace(tzinfo=None), code, name, price, lim, run, inst, fo, pg,
                           " / ".join(f"{b}: {d}" for b, d in decisions.items())])
        logging.info("홍인기 계좌: %s 상한가 %s 풀림 %s (잠김 %s분, 기관 %s, 프로그램 %s) → %s", name, lim, price, run, inst, pg, decisions)
        fmt = lambda v: "-" if v is None else f"{v / 1e8:+,.0f}억"
        for book, decision in decisions.items():
            if decision != "매수":
                continue
            cash = self.cash(book)
            qty = int(cash / SLOTS // price)
            if qty < 1:
                continue
            tid = f"{now:%Y%m%d}-{code}-{'A' if book == '수급 확인' else 'B'}"
            self.conn.execute("""INSERT OR REPLACE INTO hg_trades (id, book, date, code, name, buy_ts, buy_price, qty, limit_price, half_qty, status)
                                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'open')""",
                              [tid, book, self.today, code, name, now.replace(tzinfo=None), price, qty, lim])
            self.notify(f"{TAG}·{book} 상한가 풀림 가상 매수 {name}({code}) {qty}주 × {price:,.0f}원 (상한가 {lim:,} 대비 {price / lim - 1:+.1%}, "
                        f"잠김 {run}분)\n  수급: 기관 가집계 {fmt(inst)} · 외국인 {fmt(fo)} · 프로그램 {fmt(pg)}\n"
                        f"  매도: 다시 상한가면 절반, 나머지 다음 날 09:00 (주문 없는 가상 기록, 잔고 {cash:,.0f}원)")

    def _manage(self, now: datetime, value_top) -> None:
        px = {r.code: r.price for r in value_top if r.price}
        quotes: dict[str, Optional[float]] = {}
        for tid, book, d, code, name, buy, qty, lim, half_qty in self.open_trades():
            price = px.get(code)
            if d < self.today or price is None:
                if code not in quotes:
                    try:
                        q = self.market.quote(code, integrated=False)
                        quotes[code] = float(q.price) if q and q.price else None
                    except Exception:
                        logging.warning("홍인기 계좌: %s 시세 조회 실패", code)
                        quotes[code] = None
                price = quotes[code]
            if not price:
                continue
            price = float(price)
            if d < self.today:
                self._close(now, tid, book, name, code, buy, qty, half_qty or 0, lim, price, "다음 날 09:00 매도")
            elif not half_qty and price >= lim and qty >= 2:
                h = qty // 2
                self.conn.execute("UPDATE hg_trades SET half_ts = ?, half_qty = ? WHERE id = ?", [now.replace(tzinfo=None), h, tid])
                self.notify(f"{TAG}·{book} {name} 다시 상한가 {lim:,.0f} → 절반 {h}주 매도 ({lim / buy - 1 - COST:+.2%}), "
                            f"나머지 {qty - h}주 다음 날 09:00 (가상)")

    def _close(self, now, tid, book, name, code, buy, qty, half_qty, lim, price, reason) -> None:
        rest = qty - half_qty
        pnl = half_qty * (lim - buy) + rest * (price - buy) - qty * buy * COST
        self.conn.execute("""UPDATE hg_trades SET sell_ts = ?, sell_price = ?, reason = ?, pnl = ?, status = 'closed' WHERE id = ?""",
                          [now.replace(tzinfo=None), price, reason, pnl, tid])
        cash = self.cash(book)
        self.notify(f"{TAG}·{book} 매도 {name}({code}) {rest}주 × {price:,.0f}원 — {reason}"
                    f"{f' (절반 {half_qty}주는 상한가 {lim:,.0f})' if half_qty else ''}, 합계 {pnl / (qty * buy):+.2%} ({pnl:+,.0f}원)"
                    f" → 잔고 {cash:,.0f}원 (시작 1천만 대비 {cash / START_CASH - 1:+.1%}, 가상 기록)")
        logging.info("홍인기 계좌(%s) 매도 %s %s — %s, %+.0f원", book, name, price, reason, pnl)

    def _today_note(self) -> str:
        n = self.conn.execute("SELECT count(*) FROM hg_events WHERE date = ?", [self.today]).fetchone()[0]
        bought = self.conn.execute("SELECT book, count(*) FROM hg_trades WHERE date = ? GROUP BY 1", [self.today]).fetchall()
        return f"상한가 풀림 {n}번, 매수 " + (", ".join(f"{b} {k}건" for b, k in bought) if bought else "없음")

    def summary(self) -> str:
        lines = [f"{TAG} 1천만 가상 계좌 {self.today:%m-%d} 마감 — {self._today_note()}"]
        held = self.open_trades()
        for book in BOOKS:
            cash = self.cash(book)
            n, w = self.conn.execute("""SELECT count(*), count(*) FILTER (WHERE pnl > 0) FROM hg_trades
                                        WHERE status = 'closed' AND book = ?""", [book]).fetchone()
            hb = [h for h in held if h[1] == book]
            hold = ", ".join(f"{h[4]} {h[6] - (h[8] or 0)}주 × {h[5]:,.0f}원" for h in hb) if hb else "없음"
            lines.append(f"  {book}: 잔고 {cash:,.0f}원 (시작 대비 {cash / START_CASH - 1:+.1%}), 끝난 매매 {n}건 중 수익 {w}건, "
                         f"보유 {hold}")
        return "\n".join(lines) + "\n  보유 종목은 다음 날 09:00 매도 (주문 없는 가상 기록)"
