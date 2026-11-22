"""🧪 수동 인버스 3분할 (manual_plan.py) 시나리오 시험 — 임시 폴더·임시 DB·가짜 키움 클라이언트·가짜 시세만 씀 (실주문·실서버 없음).

    .venv\\Scripts\\python.exe tests\\test_manual_plan.py
"""
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import duckdb

from kiwoom_trading.execution import manual_plan as M
from kiwoom_trading.execution import real as R

D1, D2 = date(2026, 11, 23), date(2026, 11, 24)
CODE = "114800"


def at(d: date, hm: str, s: int = 0) -> datetime:
    h, m = map(int, hm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, s)


@dataclass
class Q:
    price: int
    base_price: int = 1_309
    volume: int = 1_000
    upper: int = 1_701


class FakeClient:
    """주문은 기록만. fill_mode: 'full' 주문 즉시 다 체결 / 'none' 체결 안 됨. 체결가 = 주문 때 시세."""

    def __init__(self, market, cash=47_646, hold=0):
        self.market = market
        self.allowed = set()
        self.orders = []
        self.fills = {}
        self.cash_amt, self.hold = cash, hold
        self.fill_mode = "full"
        self.fail_next = 0

    def cash(self):
        return self.cash_amt

    def holding_qty(self, code):
        return self.hold

    def limit_buy(self, code, qty, price, exchange="KRX"):
        assert code in self.allowed, f"허용 안 된 종목 {code}"
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("주문 거부: 가짜 오류")
        no = f"B{len(self.orders) + 1}"
        self.orders.append(("buy", code, qty, price, no))
        if self.fill_mode == "full":
            px = self.market.px
            self.fills[no] = (qty, float(px))
            self.cash_amt -= qty * px
            self.hold += qty
        return no

    def market_order(self, side, code, qty):
        assert code in self.allowed, f"허용 안 된 종목 {code}"
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("주문 거부: 가짜 매도 오류")
        no = f"S{len(self.orders) + 1}"
        self.orders.append((side, code, qty, None, no))
        self.fills[no] = (qty, float(self.market.px))
        self.hold -= qty
        return no

    def fill_info(self, no, code):
        return self.fills.get(no, (0, None))

    def fill_price(self, no, code):
        return self.fills.get(no, (0, None))[1]

    def best_quote(self, code):
        return float(self.market.px + 1), float(self.market.px)

    def cancel(self, *a, **k):
        return "C"

    def buys(self):
        return [o for o in self.orders if o[0] == "buy"]

    def sells(self):
        return [o for o in self.orders if o[0] == "sell"]


class FakeMarket:
    def __init__(self):
        self.px = 1_382
        self.volume = 0
        self.client = None
        self.bars = []

    def quote(self, code, integrated=False):
        assert code == CODE
        return Q(self.px, volume=self.volume)


def bar(d, hm, o, h, l, c):
    return {"ts": at(d, hm), "open": o, "high": h, "low": l, "close": c, "volume": 100}


PLAN = {"id": "2026-11-23_inverse_split", "type": "inverse_split3", "enabled": True, "date": "2026-11-23", "exit_date": "2026-11-24",
        "code": CODE, "name": "KODEX 인버스", "parts": 3, "dip_pct": 0.005, "stop_pct": 0.02, "limit_up": 0.01,
        "fill_wait_sec": 120, "buy_until": "14:30", "exit_time": "09:00"}


class Env:
    def __init__(self, plan=None, cash=47_646, hold=0):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "2026-11-23_inverse_split.json")
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(plan or PLAN, f, ensure_ascii=False)
        self.conn = duckdb.connect(os.path.join(self.dir, "s.duckdb"))
        self.market = FakeMarket()
        self.client = FakeClient(self.market, cash, hold)
        self.msgs = []
        self.paused = False

    def runner(self, today, now):
        rs = M.load_runners(today, self.market, self.conn, notify=self.msgs.append, client_factory=lambda: self.client,
                            plan_dir=self.dir, state_dir=self.dir, now=now, bars_fn=lambda c, d: self.market.bars, pause_fn=lambda: self.paused)
        return rs[0] if rs else None

    def rows(self):
        return self.conn.execute("SELECT id, kind, qty, status, buy_price, fill_price, signal_price, order_price, ask1, bid1, sell_price, pnl, "
                                 "sell_signal_price, sell_bid1 FROM real_trades ORDER BY id").fetchall()


def tick(r, now):
    r._last_tick = None
    r.tick(now)


def open_day(e):
    """07:50 시작 → 08:55 기준 금액 → 09:00 첫 체결 → 1차 체결."""
    r = e.runner(D1, at(D1, "07:50"))
    assert r is not None and "47,646" in r.card_line(), r.card_line()
    tick(r, at(D1, "08:30"))
    assert not e.client.orders
    tick(r, at(D1, "08:56"))
    assert r.st["base_final"] and r.st["base_cash"] == 47_646 and r.st["baseline_qty"] == 0
    e.market.volume = 0
    tick(r, at(D1, "09:00", 1))
    assert not e.client.orders, "첫 체결(거래량) 전에는 안 삼"
    e.market.volume = 5_000
    tick(r, at(D1, "09:00", 6))
    assert len(e.client.buys()) == 1
    _, code, qty, limit, _ = e.client.buys()[0]
    assert code == CODE and limit == R.tick_up(1_382 * 1.01) == 1_396 and qty == (47_646 // 3) // 1_396 == 11, (qty, limit)
    tick(r, at(D1, "09:00", 12))   # 체결 확인
    assert r.tr(1)["status"] == "open" and r.tr(1)["fill_price"] == 1_382
    return r


def test_first_only():
    e = Env()
    r = open_day(e)
    # 값이 안 빠지고 계속 오름 → 2차 없음, 14:30 뒤 새 매수 없음, 15:19 정리 안 함
    e.market.px = 1_400
    e.market.bars = [bar(D1, "09:00", 1382, 1385, 1380, 1384), bar(D1, "09:01", 1384, 1390, 1383, 1389), bar(D1, "09:02", 1389, 1401, 1388, 1400)]
    for hm in ("09:03", "10:00", "14:31", "15:19", "15:25"):
        tick(r, at(D1, hm, 5))
    assert len(e.client.buys()) == 1 and not e.client.sells()
    rows = e.rows()
    assert len(rows) == 1 and rows[0][1] == R.MANUAL_KIND and rows[0][3] == "open"
    assert rows[0][6] == 1_382 and rows[0][7] == 1_396 and rows[0][8] == 1_383 and rows[0][9] == 1_382   # 신호가·주문가·1호가
    assert any("1차" in m and "매수 주문" in m for m in e.msgs) and any("매수 체결" in m for m in e.msgs)
    print("ok 1차만 (오르기만 함 → 2·3차 없음, 15:19 정리 안 함)")


def test_two_and_three():
    e = Env()
    r = open_day(e)
    thr = 1_382 * 0.995   # 1,375.09
    # 09:01 봉 저가 1,375 (눌림) → 09:02 봉 종가 < 09:01 종가 (아직) → 09:03 봉 종가 > 09:02 종가 → 2차
    e.market.px = 1_378
    e.market.bars = [bar(D1, "09:00", 1382, 1390, 1380, 1383), bar(D1, "09:01", 1383, 1384, 1375, 1377)]
    tick(r, at(D1, "09:02", 3))
    assert r.st["dip_ts"], "봉 저가로 눌림 확인"
    assert len(e.client.buys()) == 1
    e.market.bars.append(bar(D1, "09:02", 1377, 1378, 1372, 1374))
    tick(r, at(D1, "09:03", 3))
    assert len(e.client.buys()) == 1, "직전 봉보다 낮게 마감 → 아직"
    e.market.bars.append(bar(D1, "09:03", 1374, 1379, 1373, 1378))
    e.market.px = 1_379
    tick(r, at(D1, "09:04", 3))
    assert len(e.client.buys()) == 2, e.client.orders
    assert e.client.buys()[1][2] == (47_646 // 3) // R.tick_up(1_379 * 1.01)
    tick(r, at(D1, "09:04", 10))
    assert r.tr(2)["status"] == "open"
    # 3차: 2차 체결 뒤 끝난 봉 종가가 그 전 고점 1,390 을 넘어야
    e.market.bars += [bar(D1, "09:04", 1378, 1388, 1377, 1387)]
    tick(r, at(D1, "09:05", 3))
    assert len(e.client.buys()) == 2, "고점 1,390 아직 못 넘음"
    e.market.bars += [bar(D1, "09:05", 1387, 1395, 1386, 1393)]
    e.market.px = 1_394
    tick(r, at(D1, "09:06", 3))
    assert len(e.client.buys()) == 3
    spent = sum(r.tr(k)["fill_qty"] * r.tr(k)["fill_price"] for k in (1, 2))
    lim3 = R.tick_up(1_394 * 1.01)
    assert e.client.buys()[2][2] == int(min(47_646 - spent, e.client.cash_amt + e.client.buys()[2][2] * 1_394) // lim3)
    tick(r, at(D1, "09:06", 10))
    assert r.tr(3)["status"] == "open"
    tick(r, at(D1, "09:30", 10))
    assert len(e.client.buys()) == 3 and len(e.rows()) == 3
    print(f"ok 1·2·3차 (수량 {[r.tr(k)['fill_qty'] for k in (1, 2, 3)]}, 평균 {r.avg_price():,.1f}원)")
    return e, r


def test_stop():
    e = Env()
    r = open_day(e)
    e.market.px = 1_378
    e.market.bars = [bar(D1, "09:00", 1382, 1390, 1380, 1383), bar(D1, "09:01", 1383, 1384, 1375, 1377),
                     bar(D1, "09:02", 1377, 1379, 1374, 1378)]
    tick(r, at(D1, "09:02", 3))
    tick(r, at(D1, "09:03", 3))
    assert len(e.client.buys()) == 2
    tick(r, at(D1, "09:03", 10))
    avg = r.avg_price()
    e.market.px = int(avg * 0.98) + 1
    tick(r, at(D1, "09:10"))
    assert not e.client.sells(), "−2% 안 닿음"
    e.market.px = int(avg * 0.98)
    tick(r, at(D1, "09:11"))
    assert len(e.client.sells()) == 1 and e.client.sells()[0][2] == r.tr(1)["fill_qty"] + r.tr(2)["fill_qty"]
    tick(r, at(D1, "09:11", 10))
    assert r.st["done"] and e.client.hold == 0
    rows = e.rows()
    assert all(x[3] == "closed" and x[11] < 0 and x[12] == e.market.px and x[13] == e.market.px for x in rows), rows
    # 손절 뒤엔 값이 돌아와도 다시 안 삼
    e.market.px = 1_500
    tick(r, at(D1, "10:00"))
    assert len(e.client.buys()) == 2
    assert any("손절" in m and "매도 주문" in m for m in e.msgs) and any("매도 체결" in m for m in e.msgs)
    print(f"ok 손절 −2% (평균 {avg:,.1f} → {int(avg * 0.98):,}, 손익 {sum(x[11] for x in rows):+,.0f}원)")


def test_after_1430():
    e = Env()
    r = open_day(e)
    e.market.px = 1_370   # 눌림은 있었지만 반등 봉이 14:30 뒤
    tick(r, at(D1, "14:20"))
    assert r.st["dip_ts"]
    e.market.bars = [bar(D1, "14:29", 1370, 1371, 1368, 1369), bar(D1, "14:30", 1369, 1375, 1369, 1374)]
    tick(r, at(D1, "14:31", 3))
    assert len(e.client.buys()) == 1, "14:30 뒤 2차 안 삼"
    print("ok 14:30 뒤 2·3차 안 삼")


def test_restart_no_duplicate():
    e = Env()
    r = open_day(e)
    # 다시 켬 → 같은 상태 파일, 1차 다시 안 삼
    r2 = e.runner(D1, at(D1, "09:20"))
    tick(r2, at(D1, "09:20", 5))
    assert len(e.client.buys()) == 1 and r2.tr(1)["status"] == "open"
    # 주문 보내는 중 꺼진 기록('sending') → 다시 켜도 안 보냄
    r2.tr(2)["status"] = "sending"
    r2._save()
    r3 = e.runner(D1, at(D1, "09:30"))
    assert r3.tr(2)["status"] == "unknown" and any("다시 주문하지 않음" in m for m in e.msgs)
    e.market.px = 1_370
    e.market.bars = [bar(D1, "09:30", 1372, 1373, 1369, 1370), bar(D1, "09:31", 1370, 1376, 1370, 1375)]
    tick(r3, at(D1, "09:31", 30))
    tick(r3, at(D1, "09:32", 3))
    assert len(e.client.buys()) == 1
    print("ok 재시작 중복 방지 (상태 파일 · 'sending' → 확인 필요)")


def test_retry_once_and_skip():
    e = Env()
    r = e.runner(D1, at(D1, "07:50"))
    tick(r, at(D1, "08:56"))
    e.market.volume = 1
    e.client.fail_next = 2
    tick(r, at(D1, "09:00", 5))
    assert r.tr(1)["status"] == "retry" and not e.client.orders
    tick(r, at(D1, "09:00", 30))
    assert r.tr(1)["attempts"] == 1, "1분 안에는 다시 안 함"
    tick(r, at(D1, "09:01", 6))
    assert r.tr(1)["status"] == "gave_up" and r.tr(1)["attempts"] == 2
    tick(r, at(D1, "09:03"))
    assert r.tr(1)["attempts"] == 2 and not e.client.orders
    # 1주도 못 삼
    e2 = Env(cash=2_000)
    r2 = e2.runner(D1, at(D1, "08:56"))
    tick(r2, at(D1, "08:57"))
    e2.market.volume = 1
    tick(r2, at(D1, "09:00", 5))
    assert r2.tr(1)["status"] == "skipped" and not e2.client.orders and any("1주도 못 삼" in m for m in e2.msgs)
    print("ok 주문 실패 1분 뒤 한 번만 재시도 · 1주도 못 사면 건너뜀")


def test_stale_preopen_volume():
    """장 전에도 지난 거래일 거래량이 보이는 경우 — 09:00 지나도 그 값 그대로면 안 삼, 바뀌면 삼."""
    e = Env()
    r = e.runner(D1, at(D1, "07:50"))
    e.market.volume = 873_462_882
    tick(r, at(D1, "08:58"))
    assert r.st["preopen_volume"] == 873_462_882
    tick(r, at(D1, "09:00", 1))
    assert not e.client.orders, "지난 거래일 거래량 그대로 → 아직 첫 체결 아님"
    e.market.volume = 2_100_000
    tick(r, at(D1, "09:00", 6))
    assert len(e.client.buys()) == 1
    print("ok 장 전 지난 거래일 거래량 그대로면 안 삼, 첫 체결 뒤 삼")
    # 기준 금액을 한 번도 못 읽었으면 1차 안 함 (0원으로 건너뛰지 않음) → 읽히면 그때 삼
    e2 = Env()
    real_cash = e2.client.cash
    e2.client.cash = lambda: (_ for _ in ()).throw(RuntimeError("조회 실패"))
    r2 = e2.runner(D1, at(D1, "07:50"))
    assert r2.st["base_cash"] is None
    e2.market.volume = 1
    tick(r2, at(D1, "09:00", 5))
    assert not e2.client.orders and r2.tr(1)["status"] == "pending" and sum("기준 금액 조회 실패" in m for m in e2.msgs) == 1
    tick(r2, at(D1, "09:00", 15))
    assert sum("기준 금액 조회 실패" in m for m in e2.msgs) == 1, "실패 알림은 한 번만"
    e2.client.cash = real_cash
    tick(r2, at(D1, "09:00", 25))
    tick(r2, at(D1, "09:00", 35))
    assert len(e2.client.buys()) == 1 and r2.st["base_cash"] == 47_646
    print("ok 기준 금액 못 읽으면 기다렸다가 읽히면 1차")


def test_unfilled_cancel_retry():
    e = Env()
    r = e.runner(D1, at(D1, "08:56"))
    tick(r, at(D1, "08:57"))
    e.market.volume = 1
    e.client.fill_mode = "none"
    tick(r, at(D1, "09:00", 5))
    assert r.tr(1)["status"] == "ordered"
    tick(r, at(D1, "09:01", 0))
    assert r.tr(1)["status"] == "ordered", "2분 전엔 기다림"
    tick(r, at(D1, "09:02", 10))
    assert r.tr(1)["status"] == "retry" and e.rows()[0][3] == "failed"
    e.client.fill_mode = "full"
    tick(r, at(D1, "09:03", 15))
    tick(r, at(D1, "09:03", 25))
    assert len(e.client.buys()) == 2 and r.tr(1)["status"] == "open" and r.tr(1)["tid"].endswith("-1b")
    print("ok 지정가 2분 미체결 → 취소 → 1분 뒤 한 번 다시 (기록 failed + 새 줄)")


def test_pause_and_wrong_day():
    e = Env()
    assert e.runner(date(2026, 11, 20), at(date(2026, 11, 20), "09:00")) is None, "계획 날짜 전엔 안 돎"
    r = e.runner(D1, at(D1, "08:56"))
    tick(r, at(D1, "08:57"))
    e.paused = True
    e.market.volume = 1
    tick(r, at(D1, "09:00", 5))
    assert not e.client.orders, "실전 쉼 → 새 매수 없음"
    # 보유 없는 채로 다음 날 → 실행기 없음
    assert e.runner(D2, at(D2, "07:50")) is None
    # 다른 종목 계획은 무시
    bad = dict(PLAN, code="005930")
    e3 = Env(plan=bad)
    assert e3.runner(D1, at(D1, "07:50")) is None
    print("ok 실전 쉼 새 매수 멈춤 · 계획 날짜 아닌 날 안 돎 · 다른 종목 계획 무시")


def test_next_day_sell():
    e, r = test_two_and_three()
    total = sum(r.tr(k)["fill_qty"] for k in (1, 2, 3))
    assert e.client.hold == total
    # 11-23 15:19·15:25 → 안 팜
    tick(r, at(D1, "15:19", 30))
    assert not e.client.sells()
    # 11-24 07:50 다시 켬 → 이어받음, 08:59 안 팜, 09:00 전량 시장가
    r2 = e.runner(D2, at(D2, "07:50"))
    assert r2 is not None and "09:00 전량 매도" in r2.card_line(), r2.card_line()
    tick(r2, at(D2, "08:59", 50))
    assert not e.client.sells()
    e.market.px = 1_420
    e.client.fail_next = 1   # 첫 매도 주문 실패 → 1분 뒤 다시
    tick(r2, at(D2, "09:00", 2))
    assert not e.client.sells() and r2.st["exit"]["status"] == "pending"
    tick(r2, at(D2, "09:00", 30))
    assert not e.client.sells()
    tick(r2, at(D2, "09:01", 5))
    assert len(e.client.sells()) == 1 and e.client.sells()[0][2] == total
    tick(r2, at(D2, "09:01", 15))
    assert r2.st["done"] and e.client.hold == 0
    rows = e.rows()
    assert all(x[3] == "closed" and x[10] == 1_420 for x in rows)
    # RealTrader.actives 는 이 kind 를 안 봄
    assert e.conn.execute("SELECT count(*) FROM real_trades WHERE kind = ?", [R.MANUAL_KIND]).fetchone()[0] == 3
    # 끝난 뒤 다시 켜도 실행기 없음
    assert e.runner(D2, at(D2, "10:00")) is None
    print(f"ok 11-24 09:00 전량 매도 (매도 실패 1분 뒤 재시도, {total}주, 손익 {sum(x[11] for x in rows):+,.0f}원)")


def test_baseline_existing_holding():
    e = Env(hold=5)    # 계획 전부터 들고 있던 5주는 안 팜
    r = e.runner(D1, at(D1, "08:56"))
    tick(r, at(D1, "08:57"))
    e.market.volume = 1
    tick(r, at(D1, "09:00", 5))
    tick(r, at(D1, "09:00", 12))
    e.market.px = int(1_382 * 0.98)
    tick(r, at(D1, "09:05"))
    assert e.client.sells()[0][2] == 11 and e.client.hold == 5
    print("ok 계획 전 보유분은 안 팜 (baseline)")


def test_repo_plan_file():
    """저장소에 넣은 실제 계획 파일이 그대로 읽히고, 상태 파일은 state_dir 로 감 (실제 data/ 는 안 건드림)."""
    files = M.plan_files(M.PLAN_DIRS[1:])
    names = [os.path.basename(p) for p in files]
    assert "2026-11-23_inverse_split.json" in names, names
    with open(files[names.index("2026-11-23_inverse_split.json")], encoding="utf-8") as f:
        plan = json.load(f)
    assert plan["code"] == CODE and plan["date"] == "2026-11-23" and plan["exit_date"] == "2026-11-24" and plan["type"] == "inverse_split3"
    assert plan["stop_pct"] == 0.02 and plan["dip_pct"] == 0.005 and plan["buy_until"] == "14:30" and plan["enabled"] is True
    e = Env()
    rs = M.load_runners(D1, e.market, e.conn, notify=e.msgs.append, client_factory=lambda: e.client, plan_dir=M.PLAN_DIRS[1:],
                        state_dir=e.dir, now=at(D1, "07:50"))
    assert len(rs) == 1 and rs[0].state_path.startswith(e.dir) and e.client.allowed == {CODE}
    assert M.load_runners(date(2026, 11, 25), e.market, e.conn, client_factory=lambda: 1 / 0, plan_dir=M.PLAN_DIRS[1:], state_dir=e.dir) == []
    print("ok 저장소 계획 파일 읽힘 · 상태 파일은 data 쪽 · 다른 날엔 실계좌 클라이언트도 안 만듦")


def test_real_actives_excludes_manual():
    conn = duckdb.connect(":memory:")
    conn.execute(R.SCHEMA)
    conn.execute("INSERT INTO real_trades (id, date, code, kind, qty, status) VALUES ('x', DATE '2026-11-23', '114800', ?, 3, 'open')", [R.MANUAL_KIND])
    store = type("S", (), {"conn": conn})()
    rt = R.RealTrader.__new__(R.RealTrader)
    rt.conn = conn
    assert rt.actives() == []
    assert R.PLAYS[R.MANUAL_KIND][0] == "🧪 수동 인버스 3분할" and R.MANUAL_KIND in R.REAL_OFF and R._cost("114800") == 0.0005
    from kiwoom_trading.execution.journal import label
    assert label(R.MANUAL_KIND) == "🧪 수동 인버스 3분할"
    print("ok RealTrader 는 수동 계획 줄을 관리 안 함 · 이름표 · ETF 비용")


if __name__ == "__main__":
    test_first_only()
    test_stop()
    test_after_1430()
    test_restart_no_duplicate()
    test_retry_once_and_skip()
    test_unfilled_cancel_retry()
    test_stale_preopen_volume()
    test_pause_and_wrong_day()
    test_next_day_sell()
    test_baseline_existing_holding()
    test_repo_plan_file()
    test_real_actives_excludes_manual()
    print("모두 통과")
