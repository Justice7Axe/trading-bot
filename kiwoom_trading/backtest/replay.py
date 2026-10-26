"""장중 기록 재현 — 저장된 그날 매분 기록으로 가상 장부 매매법을 다시 돌려 '전과 같은 결과'를 확인한다 (docs/architecture.md 5장).

입력: screener.duckdb 의 rank_snapshots(매분 KRX 대금 상위 200)·investor_intraday·program_intraday,
      일봉 DB 의 minute_ohlcv(그날 통합 1분봉, 시세 조회 흉내) — 둘 다 임시 복사본으로 읽는다(운영 DB 를 건드리지 않음).
출력: 장부별 매매(종목·수량·매수가·매도가·손익)와 알림 첫 줄. 코드를 바꾸기 전·후 출력을 파일로 저장해 비교한다.

실행: python -m kiwoom_trading.backtest.replay 2026-10-21 2026-10-22 [--books hong,cafe,styles,jh] [--box-width 9]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.screener.market_data import Quote, RankItem

DATA = os.path.join(PROJECT_ROOT, "data")


def _copy(name: str) -> str:
    dst = os.path.join(tempfile.mkdtemp(), name)
    shutil.copy(os.path.join(DATA, name), dst)
    return dst


class Replay:
    """하루 재현 환경: 매분 대금 순위, 가짜 시세(1분봉), 수급 표를 담은 메모리 DB."""

    def __init__(self, day: date, daily, screener) -> None:
        self.day, self.d = day, daily
        self.snaps = defaultdict(list)
        for ts, code, name, rank, chg, price, tv in screener.execute(
                "SELECT ts, code, name, rank, change_rate, price, trade_value FROM rank_snapshots WHERE source='value_krx' AND date=? ORDER BY ts", [day]).fetchall():
            self.snaps[ts.replace(second=0, microsecond=0)].append(RankItem(code, name, rank, chg, price, tv))
        self.conn = duckdb.connect()
        for tb in ("investor_intraday", "program_intraday"):
            df = screener.execute(f"SELECT * FROM {tb} WHERE date = ?", [day]).fetchdf()
            self.conn.register("x", df)
            self.conn.execute(f"CREATE TABLE {tb} AS SELECT * FROM x")
            self.conn.unregister("x")
        self.next_day = daily.execute("SELECT min(date) FROM daily_ohlcv WHERE code='005930' AND date > ?", [day]).fetchone()[0]
        self.now = None
        self._bars = {}
        self._base = {}

    def bars(self, code: str):
        if code not in self._bars:
            self._bars[code] = self.d.execute("""SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code=? AND exchange='AL'
                                                  AND cast(ts AS date) BETWEEN ? AND ? ORDER BY ts""", [code, self.day, self.day + timedelta(days=5)]).fetchall()
        return self._bars[code]

    def quote(self, code: str, integrated: bool = False):
        b = [x for x in self.bars(code) if x[0] <= self.now]
        if not integrated:
            b = [x for x in b if time(9, 0) <= x[0].time() <= time(15, 30)]
        if not b:
            return None
        if code not in self._base:
            r = self.d.execute("SELECT close FROM daily_ohlcv WHERE code=? AND date<? ORDER BY date DESC LIMIT 1", [code, self.day]).fetchone()
            self._base[code] = int(r[0]) if r else 0
        return Quote(code, "", 0, 0, 0, int(b[-1][4]), self._base[code], 0)

    def minute_bars(self, client, code, day, exchange="AL"):
        return [dict(ts=x[0], open=x[1], high=x[2], low=x[3], close=x[4], volume=x[5]) for x in self.bars(code) if x[0].date() == day]

    def clock(self):
        """재현할 시각들: 장중 매분 + 애프터 5분 간격 + 다음 날 09:00."""
        mins = sorted(m for m in self.snaps if m.time() <= time(15, 30))
        mins += [datetime.combine(self.day, time(h, m)) for h in range(15, 20) for m in range(0, 60, 5) if time(15, 40) <= time(h, m) <= time(19, 58)]
        if self.next_day:
            mins.append(datetime.combine(self.next_day, time(9, 0, 30)))
        return mins


def run(days, books=("hong", "cafe", "styles", "jh"), box_width=None, out=sys.stdout):
    import kiwoom_trading.strategies.cafe_leader.live as CL
    import kiwoom_trading.strategies.hong_styles.live as HS
    from kiwoom_trading.strategies.hong_limitup.live import HongAccount, load_prev_limitups
    from kiwoom_trading.strategies.jeonhwang.live import JeonhwangAccount, load_jh_context
    daily = duckdb.connect(_copy("daily_ohlcv.duckdb"), read_only=True)
    scr = duckdb.connect(_copy("screener.duckdb"), read_only=True)
    if box_width is not None:
        CL.BOX_WIDTH = box_width
    for day in days:
        R = Replay(day, daily, scr)
        CL.fetch_minute_bars = R.minute_bars
        store, msgs = SimpleNamespace(conn=R.conn), []
        objs = []
        cafe = None
        if "cafe" in books or "styles" in books:
            cafe = CL.CafeLeaderWatcher(store, R, None, day, CL.load_cafe_context(daily, day), notify=msgs.append)
            if "cafe" in books:
                objs.append(cafe)
        if "hong" in books:
            objs.append(HongAccount(store, R, day, prev_limitups=load_prev_limitups(daily, day), notify=msgs.append))
        if "styles" in books:
            objs.append(HS.HongStylesAccount(store, R, day, HS.load_hs_context(daily, day), notify=msgs.append, leaders=cafe.leaders))
        if "jh" in books:
            objs.append(JeonhwangAccount(store, R, day, load_jh_context(daily, day), notify=msgs.append))
        for m in R.clock():
            R.now = m
            if m.date() != day:
                for o in objs:
                    o.today = m.date()
                    for l in (getattr(o, "books", {}) or {}).values():
                        l.today = m.date()
                    if getattr(o, "ledger", None) is not None:
                        o.ledger.today = m.date()
            for o in objs:
                o.tick(m + timedelta(seconds=5), R.snaps.get(m, []))
        print(f"===== {day}", file=out)
        try:
            for r in R.conn.execute("""SELECT book, code, name, strftime(buy_ts, '%H:%M'), qty, buy_price, part_qty, sell_price, reason, round(pnl)
                                       FROM ledger_trades ORDER BY buy_ts, book""").fetchall():
                print("  매매", r, file=out)
        except duckdb.CatalogException:
            pass
        for x in msgs:
            print("  알림", x.split("\n")[0], file=out)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="+")
    ap.add_argument("--books", default="hong,cafe,styles,jh")
    ap.add_argument("--box-width", type=float, default=None, help="☕ 박스 폭 조건을 풀어 매수 경로까지 시험할 때")
    a = ap.parse_args()
    run([date.fromisoformat(x) for x in a.days], tuple(a.books.split(",")), a.box_width)


if __name__ == "__main__":
    main()
