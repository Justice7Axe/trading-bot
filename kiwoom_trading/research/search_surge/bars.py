"""2단계: 사건 종목의 그날·다음 날 KRX 1분봉을 키움에서 받아 data/search_surge/bars.duckdb 에 모은다 (선택 편향 없음).

minute_history 는 그날 대금 상위 500 위주라 조회만 뜬 작은 종목이 빠질 수 있어 직접 받는다.
같은 날 모두 지금 기준 수정주가로 받으므로 그날·다음 날 가격 기준이 같다.
"""
import os, sys, time as _t
from datetime import date
import duckdb
import pandas as pd

ROOT = r"D:\Ellie\trading"
sys.path.insert(0, ROOT)
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client

OUT = os.path.join(ROOT, "data", "search_surge")
DB = duckdb.connect(os.path.join(OUT, "bars.duckdb"))
DB.execute("""CREATE TABLE IF NOT EXISTS bars(code VARCHAR, d DATE, ts TIMESTAMP, open BIGINT, high BIGINT, low BIGINT, close BIGINT, volume BIGINT)""")
DB.execute("CREATE TABLE IF NOT EXISTS done(code VARCHAR, d DATE, n INT)")

CAL = sorted(pd.read_parquet(os.path.join(OUT, "events.parquet")).date.unique())
TRADING = [date(2026, 10, x) for x in (13, 14, 15, 16, 19, 20, 21, 22, 23, 26, 27, 28, 29, 30)]


def nxt(d):
    later = [x for x in TRADING if x > d]
    return later[0] if later else None


if __name__ == "__main__":
    ev = pd.read_parquet(os.path.join(OUT, "events.parquet"))
    ev = ev[ev.date < date(2026, 10, 30)]
    need = set()
    for c, d in zip(ev.code, ev.date):
        need.add((c, d)); n = nxt(d)
        if n: need.add((c, n))
    done = {(c, d) for c, d in DB.execute("SELECT code, d FROM done").fetchall()}
    todo = sorted(need - done, key=lambda x: (x[1], x[0]))
    print("받을 것", len(todo), "이미", len(need & done), flush=True)
    cl = build_client()
    for i, (c, d) in enumerate(todo):
        try:
            b = fetch_minute_bars(cl, c, d, "KRX")
        except Exception as e:
            print("실패", c, d, e, flush=True); continue
        if b:
            df = pd.DataFrame(b)[["code", "ts", "open", "high", "low", "close", "volume"]]
            df.insert(1, "d", d)
            DB.execute("INSERT INTO bars SELECT * FROM df")
        DB.execute("INSERT INTO done VALUES (?, ?, ?)", [c, d, len(b)])
        if i % 50 == 0: print(i, c, d, len(b), flush=True)
    print("끝", flush=True)
