"""🐢 터틀 돌파 가짜 데이터 시험 — 선(20·55일 최고가, 10·20일 최저가, N)·직전 신호 건너뛰기·추가 매수와 손절선 올림·최저가 이탈 매도·업종 6단위 한도.
주문·시세·DB 모두 가짜 (임시 duckdb). 백테스트 아님.

    set PYTHONPATH=. && .venv\\Scripts\\python.exe tests/test_turtle.py          # pytest 없이 함수 직접 실행
"""
import os
import shutil
import tempfile
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import duckdb

from kiwoom_trading.common import cafe_universe as C
from kiwoom_trading.execution import paper as P
from kiwoom_trading.execution import strict_select
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.store import ScreenerStore
from kiwoom_trading.strategies.turtle import live as T

DAY = date(2026, 11, 16)


def bdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def flat(days, px=100.0, w=1.0):
    return [(d, px, px + w, px - w, px) for d in days]


# ---------------------------------------------------------------- 순수 함수
def test_lines_and_n():
    days = bdays(date(2026, 6, 1), 60)
    bars = [(d, 100 + k, 101 + k, 99 + k, 100.5 + k) for k, d in enumerate(days)]   # 매일 1씩 오름, 폭 2
    v = T.lines(bars)
    assert v["hi20"] == 101 + 59 and v["hi55"] == 101 + 59
    assert v["lo10"] == 99 + 50 and v["lo20"] == 99 + 40
    # 진짜 폭 = max(2, |고가−전일 종가|=1.5, |저가−전일 종가|=0.5) = 2 → N = 2 (단순 20일 평균)
    assert abs(v["n"] - 2.0) < 1e-9
    # 갭: 전일 종가 100 → 오늘 고가 110·저가 106 → 진짜 폭 10 (고가−저가 4 보다 큼)
    g = flat(days[:30]) + [(days[30], 107, 110, 106, 108)]
    assert T.true_ranges(g)[-1] == 10
    assert T.lines(bars[:T.MIN_ROWS - 1]) is None                       # 55일 선에 일봉 56개 필요


def test_prev_signal_win_loss_open():
    days = bdays(date(2026, 3, 2), 80)
    base = flat(days[:30])                                             # 고가 101 · 저가 99 · N 2
    # 이김: 30일째 105 돌파(산 값 101, 손절 97) → 쭉 오름 → 10일 최저가 이탈로 이익 매도 → 그 뒤 내려앉아 새 돌파 없음
    up = [(d, 101 + 2 * k, 103 + 2 * k, 100 + 2 * k, 102 + 2 * k) for k, d in enumerate(days[30:45])]
    drop = [(days[45], 120, 121, 100, 101)] + flat(days[46:60], 100, 1)
    win = T.prev_signal(base + up + drop)
    assert win and win["date"] == days[30] and win["entry"] == 101 and win["result"] == "이김", win
    assert win["how"] == "10일 최저가 이탈" and win["exit"] > win["entry"] and T.is_win(win)
    # 짐: 25일째 꼬리(저가 90)로 10일 최저가가 90 → 손절선 101 − 2 × 2.45 = 96.1 이 더 높음 → 돌파 다음 날 저가 95 에 손절
    deep = list(base)
    deep[25] = (days[25], 100, 101, 90, 100)                           # 진짜 폭 11 → N = (19 × 2 + 11) / 20 = 2.45
    lose = deep + [(days[30], 100, 105, 99, 104), (days[31], 103, 103, 95, 96)] + flat(days[32:40], 96, 1)
    p = T.prev_signal(lose)
    assert p["result"] == "짐" and p["how"] == "손절" and abs(p["exit"] - 96.1) < 1e-9 and not T.is_win(p), p
    # 진행 중: 돌파 뒤 계속 들고 있음 → 어제 종가가 산 값 위면 '이김(진행 중)'
    run = base + [(days[30], 100, 105, 99, 104)] + [(d, 104, 106, 103, 105) for d in days[31:36]]
    p = T.prev_signal(run)
    assert p["result"] == "이김(진행 중)" and T.is_win(p)
    assert T.prev_signal(base) is None and not T.is_win(None)          # 앞선 신호 없음 → 건너뛰지 않음
    # 같은 날 손절선(97)·10일 최저가(99) 둘 다 닿으면 손절이 먼저라고 봄 (일봉으로는 순서를 몰라 보수적으로, 문서 ③ A)
    both = base + [(days[30], 100, 105, 99, 104), (days[31], 104, 104, 90, 92)] + flat(days[32:36], 92, 1)
    p = T.prev_signal(both)
    assert p["how"] == "손절" and p["exit"] == 97 and p["result"] == "짐", p
    # 10일 최저가만 깨지면(손절선 위) 이탈 매도 — 산 값보다 낮으면 '짐'
    only = base + [(days[30], 100, 105, 99, 104), (days[31], 104, 104, 98, 98.5)] + flat(days[32:36], 98.5, 0.2)
    p = T.prev_signal(only)
    assert p["how"] == "10일 최저가 이탈" and p["exit"] == 99 and p["result"] == "짐", p


def test_jump_shrink_parse():
    days = bdays(date(2026, 6, 1), 60)
    ok = flat(days)
    assert T.price_jump(ok) is None
    split = flat(days[:30], 50_000, 500) + flat(days[30:], 10_000, 100)  # 1/5 액면분할이 일봉 이음매에서 섞임
    assert "튐" in T.price_jump(split)
    assert T.shrink(1_000_000, 1_000_000) == (1.0, 0)
    assert T.shrink(950_000, 1_000_000) == (1.0, 0)
    f, s = T.shrink(900_000, 1_000_000)
    assert s == 1 and abs(f - 0.8) < 1e-9
    f, s = T.shrink(850_000, 1_000_000)
    assert s == 1 and abs(f - 0.8) < 1e-9
    f, s = T.shrink(810_000, 1_000_000)
    assert s == 2 and abs(f - 0.64) < 1e-9
    assert T.unit_qty(10_000, 50_000) == 5 and T.unit_qty(70_000, 50_000) == 1 and T.unit_qty(10_000, 40_000) == 4
    assert T.unit_qty(10_000, 50_000, 500, 1_000_000) == 5          # 계좌 1%(1만) ÷ N 500 = 20주 > 5만 원어치 5주
    assert T.unit_qty(10_000, 50_000, 2_500, 1_000_000) == 4        # N 이 값의 25% 인 거친 종목: 1만 ÷ 2,500 = 4주 < 5주
    assert T.unit_qty(200_000, 50_000, 14_000, 1_000_000) == 1      # 둘 다 1주 안 됨 → 1주
    note = T.entry_tag(55, 512.34, 10_000) + " · " + T.add_tag(2, datetime(2026, 11, 16, 10, 31), 4, 10_300)
    st = T.parse(note, 10_050)
    assert st == {"entry": 55, "n": 512.3, "units": 2, "last": 10_300.0}, st
    assert T.entry_of("🐢 터틀 돌파 55일") == 55 and T.entry_of("🐢 터틀 돌파 20일") == 20


# ---------------------------------------------------------------- 일봉 이어 붙이기 (가짜 DB)
def _mkdb(tmp):
    daily = os.path.join(tmp, "daily.duckdb")
    reg = os.path.join(tmp, "regular.duckdb")
    minute = os.path.join(tmp, "minute.duckdb")
    old_days = bdays(date(2026, 6, 1), 80)
    old_days = [d for d in old_days if d < T.NXT_SWITCH]
    new_days = [d for d in bdays(T.NXT_SWITCH, 60) if d < DAY]
    c = duckdb.connect(daily)
    c.execute("CREATE TABLE daily_ohlcv (code VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)")
    for code in ("000001", "000002"):
        for d in old_days:
            c.execute("INSERT INTO daily_ohlcv VALUES (?, ?, 100, 101, 99, 100, 1000)", [code, d])
        for d in new_days:   # 9-14 뒤 통합 값 — 고가 999 로 넣어 두고, 가격으로 쓰이면 시험이 깨지게
            c.execute("INSERT INTO daily_ohlcv VALUES (?, ?, 100, 999, 1, 100, 1000)", [code, d])
    c.close()
    r = duckdb.connect(reg)
    r.execute("CREATE TABLE daily_regular (code VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE)")
    gap = new_days[10]
    for d in new_days:
        if d != gap:
            r.execute("INSERT INTO daily_regular VALUES ('000001', ?, 100, 102, 98, 100)", [d])
    for d in new_days[:20]:                       # 000002: 9-14 뒤 20일째부터 5배 (병합이 섞임) → 가격 튐
        r.execute("INSERT INTO daily_regular VALUES ('000002', ?, 100, 101, 99, 100)", [d])
    for d in new_days[20:]:
        r.execute("INSERT INTO daily_regular VALUES ('000002', ?, 500, 505, 495, 500)", [d])
    r.close()
    m = duckdb.connect(minute)
    m.execute("CREATE TABLE minute_ohlcv (code VARCHAR, exchange VARCHAR, ts TIMESTAMP, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)")
    for k in range(40):                             # 빈 날 하나를 1분봉 40개(09:00~09:39)로 — 고가 103·저가 97
        ts = datetime.combine(gap, time(9, 0)) + timedelta(minutes=k)
        m.execute("INSERT INTO minute_ohlcv VALUES ('000001', 'AL', ?, 100, ?, ?, 100, 10)", [ts, 103 if k == 5 else 100.5, 97 if k == 7 else 99.5])
    m.execute("INSERT INTO minute_ohlcv VALUES ('000001', 'AL', ?, 100, 200, 1, 100, 10)", [datetime.combine(gap, time(18, 0))])   # 애프터 봉은 안 씀
    m.close()
    return daily, reg, minute, new_days, gap


def test_context_stitch_gap_and_jump():
    tmp = tempfile.mkdtemp(prefix="turtle_ctx_")
    try:
        daily, reg, minute, new_days, gap = _mkdb(tmp)
        ctx = T.TurtleContext(DAY, db_path=daily, regular_db=reg, minute_db=minute, cache_path=os.path.join(tmp, "fill.json"),
                              sectors={"000001": "반도체"})
        used = ctx.prepare(["000001", "000002"], budget=5, client=None)
        assert used == 0
        v = ctx.info["000001"]
        assert v["hi55"] == 103 and v["lo20"] <= 98 and v["hi20"] in (102, 103), v   # 통합 값 999 는 안 씀, 빈 날은 1분봉 정규장 값(103·97)
        assert ctx.filled_local == 1 and v["last"] == new_days[-1]
        if gap >= new_days[-20]:
            assert v["lo20"] == 97
        assert "000002" in ctx.bad and "튐" in ctx.bad["000002"], ctx.bad
        assert ctx.sector("000001") == "반도체" and ctx.sector("000009") == "종목 000009"
        assert ctx.exit_line("000001", 20) == v["lo10"] and ctx.exit_line("000001", 55) == v["lo20"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_context_fetch_gap_with_budget_and_cache():
    tmp = tempfile.mkdtemp(prefix="turtle_fetch_")
    try:
        daily, reg, _, new_days, gap = _mkdb(tmp)
        calls = []

        def fake_fetch(client, code, d, ex):
            calls.append((code, d))
            return [{"ts": datetime.combine(d, time(9, 0)) + timedelta(minutes=k), "open": 100, "high": 104 if k == 3 else 100, "low": 99, "close": 100}
                    for k in range(35)]
        import kiwoom_trading.ingestion.collectors.minute_collector as MC
        orig = MC.fetch_minute_bars
        MC.fetch_minute_bars = fake_fetch
        try:
            cache = os.path.join(tmp, "fill.json")
            ctx = T.TurtleContext(DAY, db_path=daily, regular_db=reg, minute_db=os.path.join(tmp, "없음.duckdb"), cache_path=cache, sectors={})
            assert ctx.prepare(["000001"], budget=0, client=object()) == 0 and "000001" not in ctx.info   # 조회 한도 0 → 다음 확인 때
            assert ctx.prepare(["000001"], budget=3, client=object()) == 1 and ctx.info["000001"]["hi55"] == 104
            assert calls == [("000001", gap)] and os.path.exists(cache)
            ctx2 = T.TurtleContext(DAY, db_path=daily, regular_db=reg, minute_db=os.path.join(tmp, "없음.duckdb"), cache_path=cache, sectors={})
            assert ctx2.prepare(["000001"], budget=3, client=object()) == 0 and ctx2.info["000001"]["hi55"] == 104   # 파일 캐시 → 다시 안 받음
            assert len(calls) == 1
        finally:
            MC.fetch_minute_bars = orig
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- 감시 (신호)
class Quote(SimpleNamespace):
    pass


class FakeMarket:
    def __init__(self, prices, highs=None):
        self.prices = dict(prices)
        self.highs = dict(highs or {})
        self.client = None
        self.quotes = 0

    def quote(self, code, integrated=False):
        self.quotes += 1
        p = self.prices.get(code)
        if not p:
            return None
        return Quote(price=p, base_price=None, upper=int(p * 1.3), high=self.highs.get(code, p), open=p, volume=1000)


class FakeSel:
    def __init__(self, items):
        self.items = items

    def pick(self, value_top, limit=100, theme=True):
        return [x for x in value_top if x.code in {v.code for v in self.items}]   # 지금 대금 순위 값(현재가) 그대로


def item(code, price, value=5e10):
    return SimpleNamespace(code=code, name=f"종목{code}", price=price, trade_value=value, change_rate=0.03)


def test_watcher_20_skip_55():
    ctx = SimpleNamespace(day=DAY, info={}, bad={}, fetched=0, filled_local=0, sector=lambda c: "반도체",
                          prepare=lambda codes, budget, client: 0)
    ctx.info["A"] = {"hi20": 10_000, "hi55": 11_000, "lo10": 9_000, "lo20": 8_500, "n": 300, "close": 9_900, "prev": None, "prev_win": False}
    won = {"date": date(2026, 10, 1), "entry": 9_000, "exit": 9_800, "exit_date": date(2026, 10, 20), "how": "10일 최저가 이탈", "result": "이김", "n": 300, "stop": 8_400}
    ctx.info["B"] = {"hi20": 10_000, "hi55": 11_000, "lo10": 9_000, "lo20": 8_500, "n": 300, "close": 9_900, "prev": won, "prev_win": True}
    ctx.info["C"] = {"hi20": 10_000, "hi55": 10_500, "lo10": 9_000, "lo20": 8_500, "n": 300, "close": 9_900, "prev": None, "prev_win": False}
    mk = FakeMarket({"A": 9_950, "B": 9_950, "C": 10_100}, highs={"C": 10_600})
    w = T.TurtleWatcher(mk, FakeSel([item("A", 9_950), item("B", 9_950), item("C", 10_100)]), ctx)
    at = datetime(2026, 11, 16, 9, 30)
    vt = [item("A", 9_950), item("B", 9_950), item("C", 10_100)]
    out = w.check(at, vt)
    # A·B 는 아직 안 넘음 · C 는 오늘 고가 10,600 이 55일 선 10,500 을 이미 넘었다 내려옴 → 55일은 끝,
    # 20일 선 10,000 은 지금가 10,100 (선 +1% 안) 이라 처음 볼 때 바로 20일 신호
    assert [(c, src) for c, _, src, _ in out] == [("C", "🐢 터틀 돌파 20일")], out
    assert ("C", 55) in w.late and w.late[("C", 55)].startswith("이미")
    assert mk.quotes == 3
    vt = [item("A", 10_050), item("B", 10_050), item("C", 10_700)]
    out = w.check(at + timedelta(minutes=1), vt)
    got = {c: (src, s) for c, _, src, s in out}
    assert set(got) == {"A"}, got                                        # B 는 직전 신호 이김 → 건너뜀, C 는 두 선 다 오늘 끝
    src, s = got["A"]
    assert src == "🐢 터틀 돌파 20일" and s.kind == T.KIND and s.level == 10_000 and s.price == 10_000 and s.stop == 10_000 - 600
    assert "B" in w.skipped and "이김" in w.skipped["B"]
    assert mk.quotes == 3                                                # 두 번째부터는 대금 순위 현재가만 씀
    # B 는 55일 최고가를 넘으면 건너뛰기와 상관없이 삼
    vt = [item("A", 10_050), item("B", 11_050), item("C", 10_200)]
    out = w.check(at + timedelta(minutes=2), vt)
    got = {c: (src, s) for c, _, src, s in out}
    assert "B" in got and got["B"][0] == "🐢 터틀 돌파 55일" and got["B"][1].level == 11_000
    assert w.check(at + timedelta(minutes=3), vt) == []                 # 선마다 하루 한 번
    assert w.check(datetime(2026, 11, 16, 15, 19), vt) == []            # 15:19 부터 안 삼


def test_watcher_first_look_signal_now():
    ctx = SimpleNamespace(day=DAY, info={"C": {"hi20": 10_000, "hi55": 12_000, "lo10": 9_000, "lo20": 8_500, "n": 300, "close": 9_900, "prev": None, "prev_win": False}},
                          bad={}, fetched=0, filled_local=0, sector=lambda c: "x", prepare=lambda codes, budget, client: 0)
    mk = FakeMarket({"C": 10_050})
    w = T.TurtleWatcher(mk, FakeSel([item("C", 10_050)]), ctx)
    out = w.check(datetime(2026, 11, 16, 9, 1), [item("C", 10_050)])
    assert len(out) == 1 and out[0][2] == "🐢 터틀 돌파 20일"          # 처음 볼 때 선 +1% 안 → 바로 신호
    mk2 = FakeMarket({"C": 10_200})
    w2 = T.TurtleWatcher(mk2, FakeSel([item("C", 10_200)]), ctx)
    assert w2.check(datetime(2026, 11, 16, 9, 1), [item("C", 10_200)]) == [] and w2.late[("C", 20)].startswith("늦게")


# ---------------------------------------------------------------- 모의·🧾 계좌 (가짜 주문)
class FakeMock:
    def __init__(self, market, cash=10_000_000):
        self.market, self._cash, self.orders, self.hold = market, cash, [], {}

    def account(self):
        return 10_000_000, {c: (q, avg, q, c) for c, (q, avg) in self.hold.items() if q}

    def cash(self):
        return self._cash

    def market_order(self, side, code, qty):
        px = self.market.prices[code]
        self.orders.append((side, code, qty, px))
        q, avg = self.hold.get(code, (0, 0.0))
        if side == "buy":
            self.hold[code] = (q + qty, (q * avg + qty * px) / (q + qty))
        else:
            self.hold[code] = (0, 0.0)
        return str(len(self.orders))

    def fill_price(self, order_no, code):
        return self.orders[int(order_no) - 1][3]


class Env:
    def __init__(self, prices, sectors=None, exits=None):
        self.tmp = tempfile.mkdtemp(prefix="turtle_paper_")
        self.store = ScreenerStore(os.path.join(self.tmp, "scr.duckdb"))
        self.market = FakeMarket(prices)
        self._orig_strict = strict_select.skip_reason
        strict_select.skip_reason = lambda *a, **k: None
        self._orig_out = C.OUT_PATH
        C.OUT_PATH = os.path.join(self.tmp, "cafe_universe.json")
        C._CACHE.clear()
        self.mock = FakeMock(self.market)
        self.trader = P.PaperTrader(self.mock, self.market, self.store, DAY)
        self.trader.regime = SimpleNamespace(strong_up=False, strong_down=True, trend_weak=True, done=set(), trend_text=lambda: "약세")   # 강한 하락장이어도 삼
        self.sectors = dict(sectors or {})
        self.exits = dict(exits or {})
        self.trader.turtle_ctx = SimpleNamespace(sector=lambda c: self.sectors.get(c, f"종목 {c}"),
                                                 exit_line=lambda c, e: self.exits.get((c, e)))

    def close(self):
        strict_select.skip_reason = self._orig_strict
        C.OUT_PATH = self._orig_out
        C._CACHE.clear()
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def tsig(code, line, n, ts, lt=20):
    return (code, f"종목{code}", f"🐢 터틀 돌파 {lt}일", Signal(ts=ts, kind=T.KIND, price=line, level=line, stop=line - 2 * n, reason="시험"))


def at(h, m, day=DAY):
    return datetime(day.year, day.month, day.day, h, m)


def acct_trade(e, code):
    return next(t for t in e.trader.accounts.trades if t.code == code and t.status in ("open", "closed"))


def test_paper_buy_add_stop_raise_and_stop_sell():
    e = Env({"000001": 10_000}, exits={("000001", 20): 9_000})
    try:
        e.trader.on_signals(at(9, 5), [tsig("000001", 10_000, 500, at(9, 5))], {})   # 09:10 전·강한 하락장·하락 흐름이어도 삼
        m = next(t for t in e.trader.trades if t.code == "000001")
        assert m.status == "ordered" and m.mode == "TURTLE" and m.qty == 5, (m.status, m.note)   # 5만 ÷ 1만 = 5주
        assert "[계획]" in m.note and "R6" not in m.note and "🐢 진입 20일 · N 500.0" in m.note and "10일 최저가 9,000원" in m.note, m.note
        e.trader.tick(at(9, 6), force=True)                                # 체결 확인 → 손절선 = 체결가 − 2N
        assert m.status == "open" and m.buy_price == 10_000 and m.stop == 9_000
        a = acct_trade(e, "000001")
        assert a.id.startswith("A:") and a.qty == 5 and a.stop == 9_000
        # +½N(250) 마다 1단위 — 10,250 → 2단위, 손절선 9,250
        for k, px in enumerate((10_250, 10_500, 10_750), start=2):
            e.market.prices["000001"] = px
            e.trader.tick(at(10, k), force=True)
            assert T.parse(m.note, m.buy_price)["units"] == k and m.stop == px - 1_000, (k, m.note, m.stop)
            assert T.parse(a.note, a.buy_price)["units"] == k and a.stop == px - 1_000
        buys = [o for o in e.mock.orders if o[0] == "buy"]
        assert len(buys) == 4 and [o[2] for o in buys] == [5, 4, 4, 4], buys   # 5만 ÷ 10,250 = 4주 …
        e.market.prices["000001"] = 11_500                                 # 4단위 다 참 → 더 안 삼
        e.trader.tick(at(10, 30), force=True)
        assert len([o for o in e.mock.orders if o[0] == "buy"]) == 4 and T.parse(m.note, m.buy_price)["units"] == 4
        e.trader.tick(at(15, 25), force=True)                              # 15:19 정리 없음
        assert m.status == "open" and a.status == "open"
        # 다음 날: 다시 켜도 장부에서 읽고, 손절선(마지막 산 값 10,750 − 2N = 9,750) 닿으면 전부
        nxt = DAY + timedelta(days=1)
        tr = P.PaperTrader(e.mock, e.market, e.store, nxt)
        tr.turtle_ctx = e.trader.turtle_ctx
        m2 = next(t for t in tr.trades if t.code == "000001")
        assert m2.status == "open" and m2.stop == 9_750
        e.market.prices["000001"] = 9_740
        tr.tick(at(9, 1, nxt), force=True)
        assert m2.status == "selling" and "손절" in m2.sell_reason and "4단위" in m2.sell_reason, m2.sell_reason
        assert e.mock.orders[-1][:3] == ("sell", "000001", 17)            # 5+4+4+4 주 전부
        a2 = next(t for t in tr.accounts.trades if t.code == "000001")
        assert a2.status == "closed" and a2.sell_price == 9_740 and a2.qty == 17
    finally:
        e.close()


def test_paper_exit_on_10day_low_and_55_uses_20day_low():
    e = Env({"000001": 10_000, "000002": 20_000}, exits={("000001", 20): 9_800, ("000002", 55): 19_000, ("000002", 20): 19_900})
    try:
        e.trader.on_signals(at(10, 0), [tsig("000001", 10_000, 500, at(10, 0)), tsig("000002", 20_000, 1_000, at(10, 0), lt=55)], {})
        a1, a2 = acct_trade(e, "000001"), acct_trade(e, "000002")
        assert a1.stop == 9_000 and a2.stop == 18_000
        e.market.prices.update({"000001": 9_790, "000002": 19_850})        # 000001: 10일 최저가 9,800 아래 → 매도 / 000002: 55일 진입이라 20일 최저가 19,000 만 봄
        e.trader.accounts.tick(at(10, 30))
        assert a1.status == "closed" and "10일 최저가 이탈" in a1.sell_reason, a1.sell_reason
        assert a2.status == "open"
        e.market.prices["000002"] = 18_990
        e.trader.accounts.tick(at(11, 0))
        assert a2.status == "closed" and "20일 최저가 이탈" in a2.sell_reason, a2.sell_reason
        from kiwoom_trading.execution import full_report as F
        assert F.sell_cat(a1.sell_reason).startswith("최저가 이탈")
    finally:
        e.close()


def test_sector_six_units():
    prices = {"000001": 10_000, "000002": 10_000, "000003": 10_000, "000004": 10_000}
    e = Env(prices, sectors={"000001": "반도체", "000002": "반도체", "000003": "반도체", "000004": "조선"})
    try:
        acc = e.trader.accounts
        e.trader.on_signals(at(10, 0), [tsig("000001", 10_000, 500, at(10, 0))], {})
        a1 = acct_trade(e, "000001")
        for k, px in enumerate((10_250, 10_500, 10_750), start=1):        # 000001 → 4단위
            e.market.prices["000001"] = px
            acc.tick(at(10, k))
        assert T.parse(a1.note, a1.buy_price)["units"] == 4
        e.trader.on_signals(at(10, 10), [tsig("000002", 10_000, 500, at(10, 10))], {})
        a2 = acct_trade(e, "000002")                                       # 4 + 1 = 5단위
        e.market.prices["000002"] = 10_250
        acc.tick(at(10, 11))                                               # 6단위 (한도)
        assert T.parse(a2.note, a2.buy_price)["units"] == 2
        e.market.prices["000002"] = 10_500
        acc.tick(at(10, 12))                                               # 7단위가 되므로 안 삼
        assert T.parse(a2.note, a2.buy_price)["units"] == 2
        e.trader.on_signals(at(10, 13), [tsig("000003", 10_000, 500, at(10, 13)), tsig("000004", 10_000, 500, at(10, 13))], {})
        by = {t.code: t for t in acc.trades if t.code in ("000003", "000004")}
        assert by["000003"].status == "skipped" and by["000003"].note.startswith("🐢 같은 업종 '반도체' 합계 6단위"), by["000003"].note
        assert by["000004"].status == "open"                               # 다른 업종은 따로
        # 키움 모의 쪽도 같은 한도 (업종 한도는 규칙상 건너뜀 → 알림 없음)
        m3 = next(t for t in e.trader.trades if t.code == "000003")
        assert m3.status == "ordered"                                     # 키움 모의는 000001·000002 가 1단위씩뿐 (추가는 모의 tick 에서) → 아직 한도 안
        assert P.RULE_SKIPS and any("🐢 같은 업종".startswith(x) for x in P.RULE_SKIPS)
    finally:
        e.close()


def test_account_shrink_after_drawdown():
    e = Env({"000001": 10_000})
    try:
        acc = e.trader.accounts
        acc.base_realized[T.KIND] = -100_000                               # 🐢 계좌 90만 → 단위 0.8배 = 4만 → 4주
        e.trader.on_signals(at(10, 0), [tsig("000001", 10_000, 500, at(10, 0))], {})
        assert acct_trade(e, "000001").qty == 4
        m = next(t for t in e.trader.trades if t.code == "000001")
        assert m.qty == 4 and "단위 0.80배" in m.note, m.note             # 키움 모의도 같은 배수
    finally:
        e.close()


def test_crash_add_still_works_through_merge_add():
    """🪃 급락 반등 나머지 1/2 추가가 공용 _merge_add 로 옮긴 뒤에도 그대로 (첫 1/2 → C 신호에 같은 금액 더)."""
    from kiwoom_trading.strategies.crash_rebound.live import ADD_TAG, HALF_TAG, KIND as CRASH_KIND
    e = Env({"000001": 10_000})
    try:
        s1 = Signal(ts=at(10, 0), kind=CRASH_KIND, price=10_000, level=0, stop=9_500, reason="시험")
        e.trader.on_signals(at(10, 0), [("000001", "종목000001", "급락 반등 A", s1)], {})
        m = next(t for t in e.trader.trades if t.code == "000001")
        assert m.qty == 50 and HALF_TAG in m.note, (m.qty, m.note)        # 100만 × 1/2 ÷ 1만
        e.trader.tick(at(10, 1), force=True)
        assert m.status == "open"
        s2 = Signal(ts=at(10, 5), kind=CRASH_KIND, price=10_000, level=0, stop=9_500, reason="시험")
        e.trader.on_signals(at(10, 5), [("000001", "종목000001", "급락 반등 C", s2)], {})
        assert m.qty == 100 and ADD_TAG in m.note and e.mock.orders[-1][:3] == ("buy", "000001", 50), (m.qty, m.note)
    finally:
        e.close()


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("통과", name)
