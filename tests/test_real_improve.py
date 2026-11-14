"""실전 개선 (2026-11-14): 실전 범위 1️⃣ 상승장 장 초·🪜 애프터 정배열 · 자동 멈춤(5연패·이번 주 −3%) · 체결 차이 기록.
임시 DB 와 가짜 키움 클라이언트·시세로만 확인 (실서버·data/screener.duckdb 안 건드림).

    .venv\\Scripts\\python.exe tests\\test_real_improve.py
"""
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import duckdb

from kiwoom_trading.execution import real as R
from kiwoom_trading.execution import strict_select
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.strategies.after_align.live import KIND as ALIGN_KIND
from kiwoom_trading.strategies.regime_plays.live import NEWHIGH_KIND, UP_KIND

MON = date(2026, 11, 16)


@dataclass
class Q:
    price: int
    base_price: int = 0
    upper: int = 0


class FakeClient:
    def __init__(self):
        self.allowed = set()
        self.orders = []
        self.fills = {}
        self.cash_amt = 100_000
        self.hold = {}

    def cash(self):
        return self.cash_amt

    def limit_buy(self, code, qty, price, exchange="KRX"):
        assert code in self.allowed
        no = f"B{len(self.orders) + 1}"
        self.orders.append(("buy", code, qty, price, exchange, no))
        return no

    def market_order(self, side, code, qty):
        no = f"S{len(self.orders) + 1}"
        self.orders.append((side, code, qty, None, "KRX", no))
        return no

    def fill_info(self, no, code):
        return self.fills.get(no, (0, None))

    def fill_price(self, no, code):
        return self.fills.get(no, (0, None))[1]

    def holding_qty(self, code):
        return self.hold.get(code, 0)

    def best_quote(self, code):
        return 10_050.0, 10_000.0

    def cancel(self, *a, **k):
        return ""


class FakeMarket:
    def __init__(self):
        self.px = {}
        self.client = None

    def quote(self, code, integrated=False):
        p = self.px.get(code)
        return Q(p, base_price=p) if p else None


def _store():
    path = os.path.join(tempfile.mkdtemp(), "t.duckdb")
    return SimpleNamespace(conn=duckdb.connect(path))


def _trader(store, today=MON, notes=None):
    strict_select.load_context = lambda d, *a, **k: strict_select.Context()   # 엄격 선정 자료 없이 (신규 상장 검사 건너뜀)
    R.strict_select.load_context = strict_select.load_context
    notes = notes if notes is not None else []
    t = R.RealTrader(FakeClient(), FakeMarket(), store, today, notify=notes.append)
    return t, notes


def _closed(conn, n, pnls, start=datetime(2026, 11, 16, 10, 0)):
    from datetime import timedelta
    conn.execute(R.SCHEMA)
    for i, p in enumerate(pnls):
        ts = start + timedelta(hours=i)
        conn.execute("INSERT INTO real_trades (id, date, code, qty, buy_price, sell_ts, pnl, status, kind) VALUES (?, ?, ?, 1, 10000, ?, ?, 'closed', ?)",
                     [f"x{n}-{i}", ts.date(), f"{i:06d}", ts, p, UP_KIND])


def test_scope_only_up_and_align():
    assert set(R.REAL_ON) == {UP_KIND, ALIGN_KIND}
    assert ALIGN_KIND in R.PLAYS and R.PLAYS[ALIGN_KIND] == ("🪜 애프터 정배열", None, 0.03)
    assert NEWHIGH_KIND in R.REAL_OFF and UP_KIND not in R.REAL_OFF and ALIGN_KIND not in R.REAL_OFF
    t, _ = _trader(_store())
    assert set(t.kinds) == {UP_KIND, ALIGN_KIND}


def test_align_buy_fill_stop_and_records():
    store = _store()
    t, notes = _trader(store)
    t.market.px["111111"] = 10_000
    now = datetime(2026, 11, 16, 9, 45)
    sig = Signal(now, ALIGN_KIND, 9_990.0, 9_900.0, 9_990 * 0.97, "🪜 애프터 정배열 — GC")
    other = Signal(now, NEWHIGH_KIND, 10_000.0, 0, 0, "6️⃣ 대금 3위")
    t.on_signals(now, [("111111", "가짜종목", "애프터 정배열", sig), ("222222", "꺼진매매", "주도주 신고가", other)])
    buys = [o for o in t.client.orders if o[0] == "buy"]
    assert len(buys) == 1 and buys[0][1] == "111111", buys     # 6️⃣ 은 실전에서 안 삼
    assert buys[0][3] == 10_100 and buys[0][2] == 2              # 현재가 +1% 지정가, 3만 원 안 2주
    row = store.conn.execute("SELECT kind, signal_price, order_price, ask1, bid1, status FROM real_trades").fetchone()
    assert row == (ALIGN_KIND, 9_990.0, 10_100.0, 10_050.0, 10_000.0, "ordered"), row
    assert any("🪜 애프터 정배열" in n and "−3% 손절" in n for n in notes), notes
    # 체결
    t.client.fills["B1"] = (2, 10_020.0)
    t.tick(datetime(2026, 11, 16, 9, 46))
    row = store.conn.execute("SELECT buy_price, fill_price, peak, status FROM real_trades").fetchone()
    assert row == (10_020.0, 10_020.0, 10_020.0, "open"), row
    # 오르면 peak, −3% 닿으면 손절
    t._vwap_reason = lambda *a, **k: None
    t.market.px["111111"] = 10_300
    t.tick(datetime(2026, 11, 16, 10, 0))
    assert store.conn.execute("SELECT peak FROM real_trades").fetchone()[0] == 10_300
    t.market.px["111111"] = 9_700   # 10,020 × 0.97 = 9,719.4 아래
    t.client.hold["111111"] = 2
    t.tick(datetime(2026, 11, 16, 10, 5))
    row = store.conn.execute("SELECT status, reason, sell_signal_price, sell_order_price, sell_ask1, sell_bid1 FROM real_trades").fetchone()
    assert row == ("selling", "손절 −3%", 9_700.0, None, 10_050.0, 10_000.0), row
    sell_no = [o for o in t.client.orders if o[0] == "sell"][0][5]
    t.client.fills[sell_no] = (2, 9_690.0)
    t.tick(datetime(2026, 11, 16, 10, 6))
    st, pnl = store.conn.execute("SELECT status, pnl FROM real_trades").fetchone()
    assert st == "closed" and pnl < 0


def test_align_next_day_sell():
    store = _store()
    t, _ = _trader(store)
    store.conn.execute("""INSERT INTO real_trades (id, date, code, name, kind, qty, buy_order_no, buy_ts, buy_price, status)
                          VALUES ('20261116-111111', '2026-11-16', '111111', '가짜', ?, 2, 'B1', '2026-11-16 09:45:00', 10000, 'open')""", [ALIGN_KIND])
    t2, _ = _trader(store, today=date(2026, 11, 17))
    t2.market.px["111111"] = 10_100
    t2.client.hold["111111"] = 2
    t2.tick(datetime(2026, 11, 17, 9, 0, 5))
    st, why, sp = store.conn.execute("SELECT status, reason, sell_signal_price FROM real_trades").fetchone()
    assert st == "selling" and why == "다음 날 시초 매도" and sp == 10_100.0, (st, why, sp)


def test_auto_stop_ignores_before_start():
    store = _store()
    _closed(store.conn, "old", [-100] * 7, start=datetime(2026, 11, 10, 10, 0))   # 11-16 전 7연패는 안 셈
    t, notes = _trader(store)
    assert not R.auto_stop_active(store.conn) and not R.is_paused(store.conn, MON)
    assert not any("자동 멈춤" in n for n in notes)


def test_auto_stop_five_losses_and_resume():
    store = _store()
    _closed(store.conn, "a", [-100, -200, 300, -100, -100, -100, -100])   # 마지막 4연패 → 아직
    assert R.auto_stop_reason(store.conn, MON) is None
    _closed(store.conn, "b", [-50], start=datetime(2026, 11, 16, 18, 0))  # 5연패
    t, notes = _trader(store)                     # 스캐너 시작 때 판정
    assert R.auto_stop_active(store.conn).startswith("5연패")
    assert R.is_paused(store.conn, MON)
    stops = [n for n in notes if n.startswith("🛑 실전 자동 멈춤 — 5연패")]
    assert len(stops) == 1 and "'실전 재개'" in stops[0], notes
    # 다시 판정해도 알림은 한 번
    t.check_auto_stop(datetime(2026, 11, 16, 19, 0))
    assert len([n for n in notes if n.startswith("🛑")]) == 1
    # 멈춤 중에는 새 매수 안 함
    t.market.px["111111"] = 10_000
    now = datetime(2026, 11, 17, 9, 10)
    t.today = date(2026, 11, 17)
    t.check_auto_stop(now)   # 다음 날 시작: 저절로 안 풀림 → 그날도 쉼
    assert R.is_paused(store.conn, date(2026, 11, 17))
    t.on_signals(now, [("111111", "가짜", "상승장 장 초", Signal(now, UP_KIND, 10_000.0, 0, 0, "대금 3위"))])
    assert not [o for o in t.client.orders if o[0] == "buy"]
    assert any(n.startswith("🛑 실전 자동 멈춤 중이라 안 삼") for n in notes)
    # 사용자 '실전 재개' → 풀리고 그 뒤부터 다시 셈
    R.set_pause(store.conn, date(2026, 11, 17), False)
    assert not R.auto_stop_active(store.conn) and not R.is_paused(store.conn, date(2026, 11, 17))
    store.conn.execute("UPDATE real_auto_stop SET cleared_ts = '2026-11-17 09:20:00'")   # 시험 날짜에 맞춰 재개 시각을 옮김 (set_pause 는 지금 시각)
    assert R.auto_stop_reason(store.conn, date(2026, 11, 17)) is None


def test_auto_stop_weekly_loss_on_sell_fill():
    store = _store()
    _closed(store.conn, "w", [-1_500, 200, -1_600])   # 합 −2,900 → 아직 (시드 10만 −3% = −3,000)
    t, notes = _trader(store)
    assert not R.auto_stop_active(store.conn)
    store.conn.execute("""INSERT INTO real_trades (id, date, code, name, kind, qty, buy_order_no, buy_ts, buy_price, sell_order_no, sell_ts, status)
                          VALUES ('s1', '2026-11-16', '333333', '가짜3', ?, 1, 'B9', '2026-11-16 09:30:00', 10000, 'S9', '2026-11-16 14:00:00', 'selling')""", [UP_KIND])
    t.client.fills["S9"] = (1, 9_900.0)
    t.tick(datetime(2026, 11, 16, 14, 1))          # 매도 체결 확정 → −125원 더해 −3,025
    why = R.auto_stop_active(store.conn)
    assert why and why.startswith("이번 주 손실"), why
    assert any(n.startswith("🛑 실전 자동 멈춤 — 이번 주 손실") for n in notes), notes
    # 다음 주가 되어도 저절로 안 풀림
    assert R.is_paused(store.conn, date(2026, 11, 23)) and R.auto_stop_active(store.conn)


def test_weekly_resets_next_week():
    store = _store()
    _closed(store.conn, "p", [-3_500], start=datetime(2026, 11, 16, 10, 0))
    assert R.auto_stop_reason(store.conn, MON).startswith("이번 주 손실")
    assert R.auto_stop_reason(store.conn, date(2026, 11, 23)) is None   # 다음 주 셈엔 안 들어감


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)):
        try:
            fn()
            print("OK  ", name)
        except Exception as exc:
            fails += 1
            import traceback
            traceback.print_exc()
            print("FAIL", name, exc)
    print("실패", fails)
    sys.exit(1 if fails else 0)
