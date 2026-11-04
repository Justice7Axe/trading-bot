"""오늘(11-04) 대금 상위 100 주식의 통합(AL) 1분봉 11-03·11-04 받기 → data/ma120_cross/min_1104.duckdb"""
import os, sys, time, duckdb
from datetime import date
from dotenv import load_dotenv
load_dotenv('.env.local')
from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
os.makedirs('data/ma120_cross', exist_ok=True)
s = duckdb.connect('data/screener.duckdb', read_only=True)
rows = s.execute("""select code, any_value(name), max(trade_value) v from rank_snapshots
                    where date='2026-11-04' and source='value_krx' and ts::time <= '15:31' group by code order by v desc""").fetchall()
s.close()
skip = ('KODEX', 'TIGER', 'ACE', 'RISE', 'SOL', 'KoAct', 'PLUS', 'HANARO', 'KIWOOM', 'ETN', 'TIME', '1Q', 'WON', '스팩')
codes = [(c, n) for c, n, v in rows if not any(k in (n or '') for k in skip)][:100]
cl = build_client()
out = duckdb.connect('data/ma120_cross/min_1104.duckdb')
out.execute("create table if not exists bars(code varchar, ts timestamp, open bigint, high bigint, low bigint, close bigint, volume bigint, primary key(code, ts))")
done = {c for (c,) in out.execute("select distinct code from bars where ts >= '2026-11-04'").fetchall()}
for i, (c, n) in enumerate(codes):
    if c in done: continue
    for d in (date(2026, 11, 3), date(2026, 11, 4)):
        for _ in range(3):
            try:
                bars = fetch_minute_bars(cl, c, d, "AL"); break
            except Exception as e:
                print("오류", c, d, e, flush=True)
                time.sleep(2); bars = []
        if bars: out.executemany("insert or ignore into bars values (?,?,?,?,?,?,?)",
                        [(b['code'], b['ts'], b['open'], b['high'], b['low'], b['close'], b['volume']) for b in bars])
        time.sleep(0.25)
    print(i, c, n, flush=True)
out.close()
