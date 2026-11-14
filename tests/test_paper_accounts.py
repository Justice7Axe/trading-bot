"""매매별 가상 계좌(A)·카페 종목 제한(C) 가짜 데이터 시험 — 주문·시세·DB 모두 가짜 (임시 duckdb).

    .venv\\Scripts\\python.exe -m pytest tests/test_paper_accounts.py -q
    .venv\\Scripts\\python.exe tests/test_paper_accounts.py          # pytest 없이 함수 직접 실행
"""
import json
import os
import shutil
import tempfile
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from kiwoom_trading.common import cafe_universe as C
from kiwoom_trading.execution import paper as P
from kiwoom_trading.execution import strict_select
from kiwoom_trading.screener.intraday_signals import Signal
from kiwoom_trading.screener.store import ScreenerStore
from kiwoom_trading.strategies.regime_plays.live import BLOCK_KIND
from kiwoom_trading.strategies.resistance_retest.live import RETEST_KIND

DAY = date(2026, 11, 16)


class FakeMock:
    def __init__(self, cash=10_000_000):
        self._cash = cash
        self.orders = []

    def account(self):
        return 10_000_000, {}

    def cash(self):
        return self._cash

    def market_order(self, side, code, qty):
        self.orders.append((side, code, qty))
        return str(len(self.orders))

    def fill_price(self, order_no, code):
        return None


class FakeMarket:
    def __init__(self, prices):
        self.prices = dict(prices)
        self.client = None

    def quote(self, code, integrated=False):
        p = self.prices.get(code)
        return SimpleNamespace(price=p, base_price=p, upper=None) if p else None


class Env:
    """임시 DB + 가짜 시장 + 키움 모의(가짜) + 매매별 가상 계좌."""

    def __init__(self, prices, cafe_path=None, mock_cash=10_000_000):
        self.tmp = tempfile.mkdtemp(prefix="acct_test_")
        self.store = ScreenerStore(os.path.join(self.tmp, "scr.duckdb"))
        self.market = FakeMarket(prices)
        self._orig_strict = strict_select.skip_reason
        strict_select.skip_reason = lambda *a, **k: None          # 엄격 선정 자료(일봉 DB)가 없는 시험 환경 — 끔
        self._orig_out = C.OUT_PATH
        C.OUT_PATH = cafe_path or os.path.join(self.tmp, "cafe_universe.json")
        C._CACHE.clear()
        self.trader = P.PaperTrader(FakeMock(mock_cash), self.market, self.store, DAY)
        self.trader.regime = SimpleNamespace(strong_up=True, strong_down=False, trend_weak=False, done=set(), trend_text=lambda: "")

    def reopen(self, day):
        """다음 날 스캐너를 다시 켠 것처럼."""
        t = P.PaperTrader(FakeMock(), self.market, self.store, day)
        t.regime = self.trader.regime
        self.trader = t
        return t

    def close(self):
        strict_select.skip_reason = self._orig_strict
        C.OUT_PATH = self._orig_out
        C._CACHE.clear()
        self.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def sig(code, kind, ts, price, stop=None):
    return (code, f"종목{code}", "시험", Signal(ts=ts, kind=kind, price=price, level=price, stop=stop if stop is not None else price * 0.95, reason="시험 신호"))


def at(h, m, day=DAY):
    return datetime(day.year, day.month, day.day, h, m)


def test_accounts_buy_independently_and_limits():
    prices = {f"00000{i}": 10_000 for i in range(1, 8)}
    e = Env(prices)
    try:
        acc = e.trader.accounts
        assert acc is not None
        now = at(10, 0)
        # 같은 종목을 두 매매가 같은 분에 → 키움 모의는 하나만(이미 보유 중), 매매별 계좌는 둘 다 삼
        e.trader.on_signals(now, [sig("000001", RETEST_KIND, now, 10_000), sig("000001", BLOCK_KIND, now, 10_000)], {})
        mock_bought = [t for t in e.trader.trades if t.status in P.ACTIVE]
        assert [t.kind for t in mock_bought] == [RETEST_KIND]                      # 3️⃣ 막힌 고점 돌파는 모의 안 삼(MOCK_OFF)
        a = {t.kind: t for t in acc.trades if t.status == "open"}
        assert set(a) == {RETEST_KIND, BLOCK_KIND}, [(t.kind, t.status, t.note) for t in acc.trades]
        t = a[RETEST_KIND]
        assert t.id.startswith("A:") and t.virtual and t.overflow and t.qty == 20 and t.buy_price == 10_000   # 20만 ÷ 1만 = 20주
        assert acc.cash(RETEST_KIND) == P.ACCOUNT_START - 200_000
        # 같은 매매 계좌에 5종목 넘게 → 6번째는 '계좌 최대 5종목'
        now2 = at(10, 5)
        e.trader.on_signals(now2, [sig(f"00000{i}", RETEST_KIND, now2, 10_000) for i in range(2, 7)], {})
        opened = [t for t in acc.trades if t.kind == RETEST_KIND and t.status == "open"]
        skipped = [t for t in acc.trades if t.kind == RETEST_KIND and t.status == "skipped"]
        assert len(opened) == 5 and len(skipped) == 1 and skipped[0].note.startswith("계좌 최대 5종목"), [(x.code, x.status, x.note) for x in acc.trades]
        # 저장된 장부도 따로 (paper_trades 와 섞이지 않음)
        n_acc = e.store.conn.execute(f"SELECT count(*) FROM {P.ACCOUNT_TABLE} WHERE status = 'open'").fetchone()[0]
        n_mock = e.store.conn.execute("SELECT count(*) FROM paper_trades WHERE id LIKE 'A:%'").fetchone()[0]
        assert n_acc == 6 and n_mock == 0
    finally:
        e.close()


def test_account_cash_limit():
    prices = {f"10000{i}": 300_000 for i in range(1, 5)}      # 1주 30만 > 종목당 20만 → 1주씩, 4번째는 돈 부족 (30만 × 3 = 90만, 남은 10만)
    e = Env(prices)
    try:
        now = at(10, 0)
        e.trader.on_signals(now, [sig(f"10000{i}", RETEST_KIND, now, 300_000) for i in range(1, 5)], {})
        acc = e.trader.accounts
        st = [(t.code, t.status, t.qty, t.note[:12]) for t in acc.trades]
        assert [s[1] for s in st] == ["open", "open", "open", "skipped"], st
        assert acc.trades[-1].note.startswith("계좌 돈 부족")
    finally:
        e.close()


def test_account_sell_rules_stop_and_next_day():
    e = Env({"000001": 10_000, "000002": 10_000})
    try:
        now = at(10, 0)
        e.trader.on_signals(now, [sig("000001", RETEST_KIND, now, 10_000, stop=9_500), sig("000002", RETEST_KIND, now, 10_000, stop=9_500)], {})
        acc = e.trader.accounts
        e.market.prices["000001"] = 9_400                      # 손절선 아래 → 그날 바로 손절 ('다음날' 방식)
        acc.tick(at(10, 30))
        t1 = next(t for t in acc.trades if t.code == "000001" and t.status != "skipped")
        assert t1.status == "closed" and t1.sell_reason == "손절" and t1.sell_price == 9_400
        assert abs(P.net_pnl(t1) - ((9_400 - 10_000) * 20 - 10_000 * 20 * P.COST)) < 1e-6
        acc.tick(at(15, 25))                                   # '다음날' 은 15:19 에 안 팖
        t2 = next(t for t in acc.trades if t.code == "000002" and t.status != "skipped")
        assert t2.status == "open"
        # 다음 날 다시 켜면 장부에서 다시 읽고 09:00 에 매도
        nxt = DAY + timedelta(days=1)
        tr = e.reopen(nxt)
        e.market.prices["000002"] = 10_500
        tr.accounts.tick(at(9, 0, nxt))
        t2 = next(t for t in tr.accounts.trades if t.code == "000002")
        assert t2.status == "closed" and t2.sell_reason == "다음 날 시초 매도" and t2.sell_price == 10_500
        assert abs(tr.accounts.balance(RETEST_KIND) - (P.ACCOUNT_START + P.net_pnl(t1) + P.net_pnl(t2))) < 1e-6
        rep = P.build_account_report(e.store, nxt)
        assert rep and "매매별 가상 계좌" in rep and "2️⃣ 저항 돌파" in rep, rep
        msgs = P.build_report(e.store, nxt, final=True)
        assert any("매매별 가상 계좌" in m for m in msgs)
        assert not any("매매별 가상 계좌" in m for m in P.build_report(e.store, nxt, final=False))
    finally:
        e.close()


def test_cafe_gate_blocks_non_cafe_and_allows_inverse():
    e = Env({"000001": 10_000, "000002": 10_000, "123310": 5_000})
    try:
        u = C.Universe(DAY, "ok", codes={"000001": "종목000001"}, fetched_at="2026-11-16 07:50")
        with open(C.OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(u.to_json(), f, ensure_ascii=False)
        C._CACHE.clear()
        now = at(10, 0)
        from kiwoom_trading.strategies.inverse.live import WEAK_KIND
        e.trader.on_signals(now, [sig("000001", RETEST_KIND, now, 10_000), sig("000002", RETEST_KIND, now, 10_000)], {})
        by = {t.code: t for t in e.trader.trades}
        assert by["000001"].status == "ordered"
        assert by["000002"].status == "skipped" and by["000002"].note.startswith(C.TAG)
        acc = {t.code: t for t in e.trader.accounts.trades}
        assert acc["000001"].status == "open" and acc["000002"].status == "skipped" and acc["000002"].note.startswith(C.TAG)
        assert C.skip_reason("123310", WEAK_KIND, DAY) is None             # 인버스 ETF 는 카페 제한에서 뺌
        assert C.skip_reason("000002", RETEST_KIND, DAY + timedelta(days=1)) is None   # 다른 날 파일은 적용 안 함
    finally:
        e.close()


def test_cafe_no_cookie_means_no_limit():
    tmp = tempfile.mkdtemp(prefix="cafe_test_")
    try:
        path = os.path.join(tmp, "cafe.json")
        u = C.refresh(at(7, 50), path=path, cookie={})
        assert u.status == "no_cookie" and not u.active
        assert "쿠키 없음" in u.card_line()
        assert C.skip_reason("000002", RETEST_KIND, DAY, universe=u) is None
        # 08:40 전엔 다시 안 가져오고, 08:40 지나면 한 번 더
        assert C.maybe_refresh(at(8, 0), path=path) is None
        assert C.load(path, DAY).fetched_at == "2026-11-16 07:50"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


FAKE_BODY = """<div class="se-main-container"><p>▶ 반도체 테마</p><p>삼성전자 (005930) +3.2% · SK하이닉스 +5%</p>
<p>한미반도체/ 원익IPS, 삼성전자우 강세</p><p>에코프로비엠 은 이차전지 — 코드만 247540 도 적음</p>
<p>삼성전자가 이끔 (조사 붙은 건 안 셈)</p><img src="https://cafeptthumb-phinf.pstatic.net/a.png"></div>"""
FAKE_NAMES = {"삼성전자": "005930", "삼성전자우": "005935", "SK하이닉스": "000660", "한미반도체": "042700", "원익IPS": "240810",
              "에코프로비엠": "247540", "LG": "003550", "이수페타시스": "007660"}


def test_cafe_extract_names_codes_images():
    codes, images, n = C.extract(FAKE_BODY, FAKE_NAMES)
    assert set(codes) == {"005930", "005935", "000660", "042700", "240810", "247540"}, codes
    assert images == ["https://cafeptthumb-phinf.pstatic.net/a.png"] and n > 20


def test_cafe_refresh_with_fake_api():
    tmp = tempfile.mkdtemp(prefix="cafe_test_")
    try:
        path = os.path.join(tmp, "cafe.json")
        arts = [{"id": 3, "subject": "11월 13일 특징테마", "writer": "", "ts": ""}, {"id": 2, "subject": "11월 13일 일자별 테마주 정리", "writer": "", "ts": ""},
                {"id": 1, "subject": "11월 13일 오전장 특징테마", "writer": "", "ts": ""}]
        bodies = {3: FAKE_BODY, 2: '<p><img src="https://x/b.jpg"></p>'}
        u = C.refresh(at(7, 50), path=path, names=FAKE_NAMES, cookie={"NID_AUT": "a", "NID_SES": "b"},
                      fetch_list_fn=lambda: arts, fetch_body_fn=lambda aid, ck: bodies[aid])
        assert u.active and len(u.codes) == 6 and [a["id"] for a in u.articles] == [3, 2]
        assert "6개 안에서만 매수" in u.card_line()
        # 08:40 다시 가져오다 실패해도 아침 결과 유지
        def boom():
            raise RuntimeError("네트워크 오류")
        u2 = C.refresh(at(8, 40), path=path, names=FAKE_NAMES, cookie={"NID_AUT": "a", "NID_SES": "b"}, fetch_list_fn=boom)
        assert u2.active and len(u2.codes) == 6 and "앞 결과 유지" in u2.reason
        # pick_articles: 오전장 특징테마가 맨 위여도 마감 '특징테마' + '테마주 정리'
        order = [arts[2], arts[0], arts[1]]
        assert [a["id"] for a in C.pick_articles(order)] == [3, 2]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_performance_page_account_rows():
    from kiwoom_trading.execution.performance_page import _account_rows
    acct = [(RETEST_KIND, 20, 10_000, 10_500, 0, None, "closed"), (RETEST_KIND, 20, 10_000, 9_500, 0, None, "closed"),
            (BLOCK_KIND, 10, 20_000, None, 0, None, "open")]
    rows = _account_rows(acct, lambda k: k)
    by = {r[0]: r for r in rows}
    assert by[RETEST_KIND][1] == 2 and by[RETEST_KIND][7] == 0
    assert by[RETEST_KIND][6] == f"{1_000_000 + (10_000 - 10_000 * 40 * 0.0025 - 10_000):,.0f}원"
    assert by[BLOCK_KIND][7] == 1 and by[BLOCK_KIND][1] == 0


def test_full_report_fill_and_seed():
    from kiwoom_trading.execution import full_report as F
    mon, fri = date(2026, 11, 16), date(2026, 11, 20)
    none = SimpleNamespace(d=SimpleNamespace(fill_cols=[], fill_rows=[]))
    assert "기록 없음" in F.Report.fill_html(none, mon, fri)
    cols = ["signal_price", "fill_price", "ask1", "bid1", "sell_signal_price"]
    rows = [(date(2026, 11, 17), "삼성전자", RETEST_KIND, 10_100, 10_400, 10_000, 10_100, 10_050, 10_000, 10_450)]
    out = F.Report.fill_html(SimpleNamespace(d=SimpleNamespace(fill_cols=cols, fill_rows=rows)), mon, fri)
    assert "+1.00%" in out and "2️⃣ 저항 돌파" in out, out
    # 시드 증액: 4주 연속 PF ≥ 1.2 · 30건 ↑
    def tr(kind, d, pnl):
        return F.Trade("account", "매매별 가상 계좌", kind, "000001", "x", 1, datetime.combine(d, datetime.min.time()), 1.0,
                       datetime.combine(d, datetime.min.time()), 1.0, pnl, "", "closed", d)
    good = [tr("A매매", fri - timedelta(days=7 * w), p) for w in range(4) for p in (300, 300, -200, 100, 100, 100, 100, 100)]
    bad = [tr("B매매", fri - timedelta(days=7 * w), p) for w in range(3) for p in (300,) * 12]
    rep = SimpleNamespace(today=fri)
    rows = F.Report.seed_rows(rep, good + bad)
    got = {k: (n, ok) for k, _, n, ok in rows}
    assert got["A매매"] == (32, True) and got["B매매"] == (36, False)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("통과", name)
