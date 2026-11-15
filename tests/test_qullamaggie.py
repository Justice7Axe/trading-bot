"""🏄 쿨라매기 돌파 가짜 데이터 시험 — 쉬는 구간 찾기·대상 판정·수량·가상 매수(손절폭 ≤ ADR20)·손절·5거래일째 절반과 본전 손절·10일선 이탈 매도.
주문·시세·DB 모두 가짜 (메모리·임시 duckdb). 백테스트 아님.

    set PYTHONPATH=. && .venv\\Scripts\\python.exe tests/test_qullamaggie.py          # pytest 없이 함수 직접 실행
"""
import os
import tempfile
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import duckdb

from kiwoom_trading.execution.ledger import Plan
from kiwoom_trading.screener.market_data import Quote
from kiwoom_trading.strategies.qullamaggie import live as Q

DAY = date(2026, 11, 16)
CODE = "111111"


def bdays(start: date, n: int) -> list:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def base_bars() -> list:
    """40일 100 → 160 오름 + 30일 쉬는 구간 (조금씩 오르며 흔들림이 줄어듦)."""
    days = bdays(date(2026, 7, 1), 70)
    bars = []
    for k, d in enumerate(days):
        if k < 40:
            c = 100 + 1.5 * k
        else:
            j = k - 40
            amp = 6 - j * (5.7 / 29)
            c = 155 + 0.15 * j + amp * (-1) ** j
        bars.append((d, c, c + 1, c - 1, c))
    return bars


# ---------------------------------------------------------------- 순수 함수
def test_find_base_and_features():
    bars = base_bars()
    b = Q.find_base(bars)
    assert b is not None and Q.BASE_MIN <= b["len"] <= Q.BASE_MAX
    seg = bars[-b["len"]:]
    assert b["top"] == max(x[2] for x in seg)
    assert b["width"] <= Q.BASE_WIDTH and b["w2"] < b["w1"] and b["lo2"] > b["lo1"]
    v = Q.features(bars)
    assert v["ok"] and v["ret63"] >= Q.MIN_GAIN63 and v["close"] > v["ma20"] and v["ma10"] and v["adr"] > 0


def test_features_reject():
    days = bdays(date(2026, 7, 1), 70)
    flat = [(d, 100.0, 101.0, 99.0, 100.0) for d in days]
    v = Q.features(flat)
    assert not v["ok"] and "63일" in v["why"] and v["ma10"] == 100.0       # 매도용 10일선은 채움
    assert not Q.features(flat[:30])["ok"]
    # 최근 5일 중 하루라도 20일선 아래면 쉬는 구간 없음
    bars = base_bars()
    d, *_ = bars[-3]
    bars[-3] = (d, 140.0, 141.0, 139.0, 140.0)
    assert Q.find_base(bars) is None


def test_qty_and_days():
    assert Q.order_qty(10_000, 1_000_000, 0.02) == 20          # 공식 50만 → 한도 20만 → 20주
    assert Q.order_qty(10_000, 1_000_000, 0.08) == 12          # 공식 12.5만 → 12주
    assert Q.order_qty(300_000, 1_000_000, 0.02) == 0          # 1주가 20만 넘음 → 안 삼
    cal = bdays(date(2026, 11, 10), 4)                          # 11-10 ~ 11-13
    assert Q.held_days(date(2026, 11, 12), DAY, cal) == 3       # 12·13·16일
    assert abs(Q.stop_width(100, 97) - 0.03) < 1e-12


# ---------------------------------------------------------------- 장부
class FakeMarket:
    def __init__(self):
        self.q = {}

    def quote(self, code, integrated=False):
        return self.q.get(code)


def make_book(info: dict, notes: list):
    path = os.path.join(tempfile.mkdtemp(), "d.duckdb")
    c = duckdb.connect(path)
    c.execute("CREATE TABLE daily_ohlcv (code VARCHAR, date DATE, close DOUBLE)")
    for d in bdays(date(2026, 10, 1), 40):
        if d < DAY:
            c.execute("INSERT INTO daily_ohlcv VALUES ('005930', ?, 1)", [d])
    c.close()
    ctx = SimpleNamespace(info={CODE: info}, bad={}, prepare=lambda *a, **k: 0)
    ranks = {CODE: {"name": "가짜", "ret": {21: 0.4, 63: 0.6, 126: 1.2}, "rank": {63: (3, 2500)}}}
    m = FakeMarket()
    book = Q.QullaBook(SimpleNamespace(conn=duckdb.connect()), m, DAY, ctx, ranks, 2500, notify=notes.append, db_path=path)
    return book, m


INFO = {"ok": True, "close": 10_000.0, "ma10": 9_800.0, "ma20": 9_500.0, "adr": 0.05, "ret63": 0.6, "last": date(2026, 11, 13),
        "base": {"len": 20, "top": 10_100.0, "width": 0.12, "w1": 0.1, "w2": 0.05, "lo1": 9_000.0, "lo2": 9_400.0,
                 "start": date(2026, 10, 16), "end": date(2026, 11, 13)}}


def test_buy_then_stop():
    notes = []
    book, m = make_book(dict(INFO), notes)
    Q.fetch_minute_bars = lambda client, code, day, ex: [{"ts": datetime(2026, 11, 16, 9, k), "high": 10_150 + k} for k in range(8)]
    now = datetime(2026, 11, 16, 9, 6, 5)
    m.q[CODE] = Quote(CODE, "", 10_000, 10_160, 9_950, 10_160, 9_900, 0)
    book.tick(now, [])                                          # 5분 고점(09:00~09:04) 10,154 · 윗선 10,100
    assert len(book.open_trades()) == 1                         # max(10,100, 10,154) = 10,154 < 현재가 10,160 → 삼
    t = book.open_trades()[0]
    assert Plan.loads(t["plan"]).stop == 9_950 and t["qty"] == int(200_000 // 10_160)
    assert notes and notes[0].startswith("🟣 가상 매수 가짜") and "🏄 쿨라매기 돌파" in notes[0] and "포착:" in notes[0]
    m.q[CODE] = Quote(CODE, "", 10_000, 10_160, 9_900, 9_900, 9_900, 0)
    book.tick(now.replace(minute=30), [])
    assert not book.open_trades()
    assert notes[-1].startswith("🟣 가상 매도 가짜") and "손절" in notes[-1]


def test_no_buy_when_stop_wider_than_adr_or_below_trigger():
    notes = []
    info = dict(INFO, adr=0.01)
    book, m = make_book(info, notes)
    Q.fetch_minute_bars = lambda client, code, day, ex: [{"ts": datetime(2026, 11, 16, 9, 0), "high": 10_150}]
    m.q[CODE] = Quote(CODE, "", 10_000, 10_140, 9_950, 10_140, 9_900, 0)
    book.tick(datetime(2026, 11, 16, 9, 6, 5), [])              # 10,140 < 5분 고점 10,150 → 판정 안 함
    assert not book.open_trades() and CODE not in book.done
    m.q[CODE] = Quote(CODE, "", 10_000, 10_200, 9_950, 10_200, 9_900, 0)
    book.tick(datetime(2026, 11, 16, 9, 7, 5), [])              # 손절폭 2.5% > ADR 1% → 안 삼, 알림 없음
    assert not book.open_trades() and CODE in book.done and not notes


def _insert(book, buy_day: date, qty=20, buy=10_000.0, stop=9_700.0):
    book.ledger.today = buy_day
    book.ledger.buy(datetime.combine(buy_day, datetime.min.time()).replace(hour=10), CODE, "가짜", buy, Plan(stop=stop, next_day=False),
                    note="시험", qty=qty, quiet=True)
    book.ledger.today = DAY


def test_day5_half_breakeven_then_stop():
    notes = []
    book, m = make_book(dict(INFO), notes)
    _insert(book, date(2026, 11, 10))                           # 10·11·12·13·16 → 오늘 5거래일째
    m.q[CODE] = Quote(CODE, "", 10_500, 10_600, 10_400, 10_550, 10_300, 0)
    book.tick(datetime(2026, 11, 16, 9, 0, 5), [])
    t = book.open_trades()[0]
    assert t["part_qty"] == 10 and t["part_price"] == 10_500 and Plan.loads(t["plan"]).stop == 10_000
    assert notes[0].startswith("🟣 가상 절반 매도 가짜")
    m.q[CODE] = Quote(CODE, "", 10_500, 10_600, 9_990, 9_990, 10_300, 0)
    book.tick(datetime(2026, 11, 16, 11, 0, 5), [])
    assert not book.open_trades() and "본전 손절" in notes[-1]


def test_close_below_ma10_sells_all_next_open():
    notes = []
    book, m = make_book(dict(INFO, close=9_700.0, ma10=9_800.0), notes)
    _insert(book, date(2026, 11, 12))                           # 절반 매도 전이어도 10일선 이탈이면 → 전부
    m.q[CODE] = Quote(CODE, "", 9_650, 9_700, 9_600, 9_680, 9_700, 0)
    book.tick(datetime(2026, 11, 16, 9, 0, 5), [])
    assert not book.open_trades()
    r = book.conn.execute("SELECT sell_price, part_qty, reason FROM ledger_trades").fetchone()
    assert r[0] == 9_650 and not r[1] and "10일선" in r[2]


def test_day4_keeps_holding():
    notes = []
    book, m = make_book(dict(INFO), notes)
    _insert(book, date(2026, 11, 11))                           # 11·12·13·16 → 4거래일째, 아무것도 안 함
    m.q[CODE] = Quote(CODE, "", 10_200, 10_300, 10_100, 10_250, 10_000, 0)
    book.tick(datetime(2026, 11, 16, 9, 0, 5), [])
    t = book.open_trades()[0]
    assert not t["part_qty"] and Plan.loads(t["plan"]).stop == 9_700 and not notes


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
