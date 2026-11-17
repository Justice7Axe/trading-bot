"""장중 기록 재현 — 저장된 그날 매분 기록으로 가상 장부 매매법을 다시 돌려 '전과 같은 결과'를 확인한다 (docs/architecture.md 5장).

입력: screener.duckdb 의 rank_snapshots(매분 KRX 대금 상위 200)·investor_intraday·program_intraday,
      일봉 DB 의 minute_ohlcv(그날 통합 1분봉, 시세 조회 흉내) — 둘 다 임시 복사본으로 읽는다(운영 DB 를 건드리지 않음).
출력: 장부별 매매(종목·수량·매수가·매도가·손익)와 알림 첫 줄. 코드를 바꾸기 전·후 출력을 파일로 저장해 비교한다.

실행: python -m kiwoom_trading.backtest.replay 2026-10-21 2026-10-22 [--books hong,cafe,styles,jh,qulla] [--box-width 9]
      장중·최근 날: --screener screener_snapshot.duckdb --minute-db minute_history.duckdb (등락률 상위 ka10027 은 1분봉으로 흉내)
  (qulla = 🏄 쿨라매기 돌파, 기본 목록에는 없음 — 넣으면 정규장 시세에 오늘 시가·고가·저가를 채움)
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

    def __init__(self, day: date, daily, screener, minute=None, regular=None) -> None:
        self.day, self.d = day, daily
        self.m = minute or daily      # 1분봉 자료 (기본 일봉 DB 의 minute_ohlcv, --minute-db 면 minute_history — 그날 대금 상위 500)
        self.reg = regular            # daily_regular (전날 정규장 종가 — 등락률 상위 흉내용, 없으면 일봉 종가)
        self._riser_day = None
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
        self.full_quote = False       # True 면 정규장 시세에 오늘 시가·고가·저가도 채움 (🏄 쿨라매기 — 다른 장부 재현 결과는 그대로 두려고 따로)

    def bars(self, code: str):
        if code not in self._bars:
            self._bars[code] = self.m.execute("""SELECT ts, open, high, low, close, volume FROM minute_ohlcv WHERE code=? AND exchange='AL'
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
        if self.full_quote and not integrated:
            today = [x for x in b if x[0].date() == self.now.date()]
            if not today:
                return None
            return Quote(code, "", int(today[0][1]), int(max(x[2] for x in today)), int(min(x[3] for x in today)), int(today[-1][4]),
                         self._base[code], int(sum(x[5] or 0 for x in today)))
        return Quote(code, "", 0, 0, 0, int(b[-1][4]), self._base[code], 0)

    def _prev_close(self) -> dict:
        p = self.d.execute("SELECT max(date) FROM daily_ohlcv WHERE code='005930' AND date < ?", [self.day]).fetchone()[0]
        out = dict(self.d.execute("SELECT code, close FROM daily_ohlcv WHERE date = ?", [p]).fetchall())
        if self.reg is not None:
            out.update(self.reg.execute("SELECT code, close FROM daily_regular WHERE date = ?", [p]).fetchall())
        return out

    def risers(self, min_value_cond: str = "300", stex_tp: str = "3", pages: int = 1):
        """ka10027 등락률 상위 흉내: 그 분 직전까지 통합 1분봉 → 등락률·누적 대금(거래량×종가), 대금 조건(키움 코드 × 1천만 원) 넘는 것 200개."""
        if self._riser_day is None:
            pc = self._prev_close()
            rows = self.m.execute("""SELECT code, ts, close, volume FROM minute_ohlcv WHERE exchange='AL' AND cast(ts AS date) = ?
                                     ORDER BY code, ts""", [self.day]).fetchall()
            by = defaultdict(list)
            for c, ts, cl, v in rows:
                if pc.get(c):
                    by[c].append((ts, cl, (cl or 0) * (v or 0)))
            self._riser_day = (by, pc)
        by, pc = self._riser_day
        need = int(min_value_cond) * 1e7
        cut = self.now.replace(second=0, microsecond=0)
        out = []
        for c, bs in by.items():
            cv, last = 0.0, None
            for ts, cl, v in bs:
                if ts >= cut:
                    break
                cv += v
                last = cl
            if last and cv >= need:
                out.append(RankItem(c, "", 0, last / pc[c] - 1, int(last), cv))
        out.sort(key=lambda r: -r.change_rate)
        return out[:200 * pages]

    def minute_bars(self, client, code, day, exchange="AL"):
        return [dict(ts=x[0], open=x[1], high=x[2], low=x[3], close=x[4], volume=x[5]) for x in self.bars(code) if x[0].date() == day]

    def clock(self):
        """재현할 시각들: 장중 매분 + 애프터 5분 간격 + 다음 날 09:00."""
        mins = sorted(m for m in self.snaps if m.time() <= time(15, 30))
        mins += [datetime.combine(self.day, time(h, m)) for h in range(15, 20) for m in range(0, 60, 5) if time(15, 40) <= time(h, m) <= time(19, 58)]
        if self.next_day:
            mins.append(datetime.combine(self.next_day, time(9, 0, 30)))
        return mins


def run(days, books=("hong", "cafe", "styles", "jh"), box_width=None, out=sys.stdout, screener_name="screener.duckdb", minute_db=None):
    import kiwoom_trading.strategies.cafe_leader.live as CL
    import kiwoom_trading.strategies.hong_styles.live as HS
    from kiwoom_trading.strategies.hong_limitup.live import HongAccount, load_prev_limitups
    from kiwoom_trading.strategies.jeonhwang.live import JeonhwangAccount, load_jh_context
    daily_path = _copy("daily_ohlcv.duckdb")
    daily = duckdb.connect(daily_path, read_only=True)
    scr = duckdb.connect(_copy(screener_name), read_only=True)
    mdb = duckdb.connect(_copy(minute_db), read_only=True) if minute_db else None
    try:
        rdb = duckdb.connect(_copy("daily_regular.duckdb"), read_only=True)
    except Exception:
        rdb = None
    if box_width is not None:
        CL.BOX_WIDTH = box_width
    for day in days:
        R = Replay(day, daily, scr, mdb, rdb)
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
        if "qulla" in books:    # 🏄 쿨라매기 돌파 — 정규장 빈 날은 지역 자료·파일 캐시로만 채움 (키움 조회 없음)
            import kiwoom_trading.strategies.qullamaggie.live as QL
            QL.fetch_minute_bars = R.minute_bars
            R.full_quote = True
            qranks, qn, _ = QL.rank_universe(day, daily_path)
            objs.append(QL.QullaBook(store, R, day, QL.QullaContext(day, db_path=daily_path), qranks, qn, notify=msgs.append, db_path=daily_path))
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
        for tb in ("cafe_checks", "cafe_leader_hits"):
            try:
                for r in R.conn.execute(f"SELECT * EXCLUDE (date) FROM {tb} ORDER BY ts").fetchall():
                    print(f"  {tb}", r, file=out)
            except duckdb.CatalogException:
                pass


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="+")
    ap.add_argument("--books", default="hong,cafe,styles,jh")
    ap.add_argument("--box-width", type=float, default=None, help="☕ 박스 폭 조건을 풀어 매수 경로까지 시험할 때")
    ap.add_argument("--screener", default="screener.duckdb", help="장중엔 본 DB 가 잠김 → screener_snapshot.duckdb")
    ap.add_argument("--minute-db", default=None, help="1분봉을 이 DB 에서 (예: minute_history.duckdb — 일봉 DB 엔 그날 몇 종목뿐일 때)")
    a = ap.parse_args()
    run([date.fromisoformat(x) for x in a.days], tuple(a.books.split(",")), a.box_width,
        screener_name=a.screener, minute_db=a.minute_db)


if __name__ == "__main__":
    main()
