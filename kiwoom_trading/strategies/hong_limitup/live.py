"""📕 [홍인기] 상한가 풀림 매수 — 1천만 원 가상 장부 두 개 (키움 모의·실계좌와 별도 기록, 주문 없음).
(2026-10-27 사용자: 홍인기 매매일지 10-26 루닛 상따를 '홍인기 매매 전략'으로 프로그래밍·스킬화, 스킬 hong)

규칙 (strategies/hong_limitup/rules.py 와 같은 숫자, 1년 백테스트 strategies/hong_limitup/backtest.py):
  대상 = 매분 받는 KRX 거래대금 상위 200 중 상한가(기준가 × 1.3, 호가 단위 내림)에 닿은 **첫 상한가** 종목
         (전날 상한가였던 종목 제외 — 2연상 이후 1년 건당 −0.95%).
  상한가에 MIN_LOCK(5)분 이상 잠겼다가(매분 확인 가격 = 상한가) 풀리면(가격 < 상한가) 그 가격에 가상 매수.
  장부 두 개 (각 1천만, 하루 3종목, 종목당 잔고 ÷ 3, 종목당 하루 1번) — 공용 가상 장부(execution/ledger.py) book:
    '수급 확인' = 홍인기 원칙: 그 시각까지 나온 기관 가집계 순매수 > 0 이고 프로그램 순매수 > 0 일 때만.
                 기관 가집계는 보통 09:50 무렵 처음 나오고 약 500종목만 온다. 가집계가 없으면 6분 기다린다(5분마다 저장).
    '수급 없이' = 1년 백테스트 규칙 그대로. 이 장부가 사는 순간 🔴 실전 매매(6️⃣2️⃣5️⃣📕)로도 신호를 넘긴다(on_real).
  매도: 다시 상한가 닿으면 절반을 상한가에, 나머지는 다음 날 09:00 첫 확인 가격. 손절 없음. 비용 0.25%.
모든 풀림(산 것·안 산 것)을 hg_events 에 수급과 함께 남긴다 → 수급 조건 검증용.
"""
import logging
from datetime import date, datetime, time, timedelta
from typing import Callable, Optional

from kiwoom_trading.common.krx import upper_limit
from kiwoom_trading.execution.ledger import Ledger, Plan, price_source

TAG = "📕 [홍인기]"
HONG_KIND = "📕 상한가 풀림"   # 실전 매매(real_inverse) 신호 종류 — '수급 없이' 장부가 살 때 함께 넘긴다 (2026-10-27 사용자)
REAL_BOOK = "수급 없이"
BOOKS = ("수급 확인", "수급 없이")
START_CASH = 10_000_000
SLOTS = 3
MIN_LOCK = 5           # 풀리기 전 상한가에 잠긴 분 수 (매분 확인 가격 = 상한가인 횟수)
BUY_FROM, BUY_UNTIL = time(9, 0), time(15, 0)
OPEN, CLOSE, REPORT_AT = time(9, 0), time(15, 30), time(15, 40)
WATCH_CHG = 0.25       # 이 등락률부터 기준가를 받아 상한가를 계산해 둔다
FLOW_WAIT_MIN = 6      # 풀렸는데 기관 가집계가 아직 없으면 이만큼 기다림 (가집계는 5분마다 저장 → 09:52 발표가 09:56 에 들어옴)

SCHEMA = """
CREATE TABLE IF NOT EXISTS hg_events (     -- 상한가 풀림마다 (산 것·안 산 것) — 수급 조건 검증용
    date DATE, ts TIMESTAMP, code VARCHAR, name VARCHAR, price DOUBLE, limit_price DOUBLE, locked_min INTEGER,
    inst DOUBLE, foreign_ DOUBLE, program DOUBLE, decision VARCHAR
);
"""


SPAC_WORDS = ("스팩", "기업인수목적", "SPAC")


def is_plain_stock(code: str, name: str) -> bool:
    """백테스트 대상과 같은 보통주만 — 스팩(기업인수목적회사)·우선주(끝자리 5·7·9·K) 제외.
    2026-10-27 실전에서 에스케이증권제14호기업인수목적(스팩)을 상한가 풀림으로 샀다 — 1년 백테스트(종목 목록에 스팩 없음)에서 한 번도 본 적 없는 종류.
    대금 상위 순위에는 스팩·ETF 도 들어오므로 여기서 거른다."""
    return code[-1] not in "579K" and not any(w in (name or "") for w in SPAC_WORDS)


def load_prev_limitups(conn, today: date) -> set[str]:
    """전 거래일 상한가(종가 기준 +29%↑) 종목 — 일봉 DB 에서. 9-14 이후 일봉 종가는 애프터 종가라 +29% 로 넉넉히 본다."""
    rows = conn.execute("""
        WITH d AS (SELECT code, date, close, lag(close) OVER (PARTITION BY code ORDER BY date) AS pc
                   FROM daily_ohlcv WHERE date >= ? - INTERVAL 15 DAY AND date < ?)
        SELECT code FROM d WHERE date = (SELECT max(date) FROM d) AND pc > 0 AND close / pc - 1 >= 0.29""", [today, today]).fetchall()
    return {r[0] for r in rows}


class HongAccount:
    def __init__(self, store, market, today: date, prev_limitups: Optional[set] = None,
                 notify: Optional[Callable[[str], object]] = None,
                 on_real: Optional[Callable[[datetime, str, str, float, int], object]] = None) -> None:
        self.conn = store.conn
        self.market = market
        self.today = today
        self.prev_limitups = prev_limitups or set()
        self.notify = notify or (lambda text: None)
        self.on_real = on_real                 # (now, code, name, price, 상한가) → 🔴 실전 매매로 신호 넘김
        self.conn.execute(SCHEMA)
        self.books = {b: Ledger(self.conn, b, TAG, today, START_CASH, SLOTS, notify=self.notify) for b in BOOKS}
        self.reported = all(l.reported() for l in self.books.values())
        self.limits: dict[str, int] = {}      # code → 상한가
        self.names: dict[str, str] = {}
        self.locked: dict[str, int] = {}      # code → 지금 연속으로 상한가인 분 수
        self.touched: set[str] = set()
        self.wait: dict[str, datetime] = {}   # '수급 확인' 장부: 가집계 기다리는 종목 → 기다림 끝 시각

    # ------------------------------------------------------------ 상태 (예전 이름 유지)
    def cash(self, book: str) -> float:
        return self.books[book].cash()

    def open_trades(self) -> list[dict]:
        return [t for l in self.books.values() for t in l.open_trades()]

    def flow(self, code: str, now: datetime):
        """지금까지 저장된 오늘 마지막 기관·외국인 가집계, 프로그램 순매수 (원). 없으면 None."""
        ts = now.replace(tzinfo=None)
        q = """SELECT net_amount FROM investor_intraday WHERE date = ? AND code = ? AND investor = ? AND ts <= ?
               ORDER BY ts DESC LIMIT 1"""
        try:
            inst = self.conn.execute(q, [self.today, code, "institution", ts]).fetchone()
            fo = self.conn.execute(q, [self.today, code, "foreign", ts]).fetchone()
            pg = self.conn.execute("""SELECT net_amount FROM program_intraday WHERE date = ? AND code = ? AND ts <= ?
                                      ORDER BY ts DESC LIMIT 1""", [self.today, code, ts]).fetchone()
        except Exception:      # 수급 표가 아직 없는 경우
            return None, None, None
        return (inst[0] if inst else None), (fo[0] if fo else None), (pg[0] if pg else None)

    # ------------------------------------------------------------ 매분
    def tick(self, now: datetime, value_top=()) -> None:
        tm = now.time()
        price_of = price_source(self.market, value_top)
        for l in self.books.values():
            l.manage(now, price_of)
        if OPEN <= tm < CLOSE and BUY_FROM <= tm <= BUY_UNTIL:
            self._watch(now, value_top)
        if tm >= REPORT_AT and not self.reported:
            self.reported = True
            note = self._today_note()
            for l in self.books.values():
                l.mark_reported(note)
            self.notify(self.summary())

    def _watch(self, now: datetime, value_top) -> None:
        for r in value_top:
            if r.change_rate is None or r.price is None or r.change_rate < WATCH_CHG:
                continue
            code = r.code
            if not is_plain_stock(code, r.name):
                continue
            self.names[code] = r.name
            if code not in self.limits:
                try:
                    q = self.market.quote(code, integrated=False)
                except Exception:
                    logging.warning("홍인기 계좌: %s 시세 조회 실패", code)
                    continue
                if not q or not q.base_price:
                    continue
                calc = upper_limit(float(q.base_price))
                if q.upper and abs(q.upper / calc - 1) > 0.01:
                    # 거래소 상한가가 기준가 +30% 가 아님 = 신규 상장 첫날(공모가 60~400%) 등 → 백테스트에 없는 날, 감시 안 함
                    # (2026-10-27 에스케이증권제14호 상장 첫날: 실제 상한가 8,000 인데 2,600 으로 계산해 '상한가 풀림'으로 잘못 삼)
                    logging.info("홍인기 계좌: %s 상한가 %s ≠ 기준가 +30%% %s (신규 상장 등) → 제외", r.name, q.upper, calc)
                    self.limits[code] = None
                    continue
                self.limits[code] = calc
            elif self.limits[code] is None:
                continue
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
        l = self.books[book]
        if code in self.prev_limitups:
            return "2연상 이후 제외"
        if l.bought_today(code):
            return "이미 삼"
        if book == "수급 확인":
            if inst is None:
                return "기관 가집계 없음"
            if inst <= 0:
                return "기관 순매도"
            if pg is None or pg <= 0:
                return "프로그램 순매도·없음"
        if l.full():
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
        if decisions.get(REAL_BOOK) == "매수" and self.on_real is not None:
            try:
                self.on_real(now, code, name, price, lim)
            except Exception:
                logging.exception("홍인기 → 실전 신호 넘기기 실패 %s", name)
        for book, decision in decisions.items():
            if decision != "매수":
                continue
            self.books[book].buy(now, code, name, price, Plan(half_at=float(lim), next_day=True),
                                 note=f"상한가 {lim:,} 풀림 {price / lim - 1:+.1%} (잠김 {run}분)",
                                 extra=f"\n  수급: 기관 가집계 {fmt(inst)} · 외국인 {fmt(fo)} · 프로그램 {fmt(pg)}")

    def _today_note(self) -> str:
        n = self.conn.execute("SELECT count(*) FROM hg_events WHERE date = ?", [self.today]).fetchone()[0]
        bought = [(b, l.n_today()) for b, l in self.books.items() if l.n_today()]
        return f"상한가 풀림 {n}번, 매수 " + (", ".join(f"{b} {k}건" for b, k in bought) if bought else "없음")

    def summary(self) -> str:
        return (f"{TAG} 1천만 가상 장부 {self.today:%m-%d} 마감 — {self._today_note()}\n"
                + "\n".join(l.summary_line() for l in self.books.values()) + "\n  보유 종목은 다음 날 09:00 매도 (주문 없는 가상 기록)")
