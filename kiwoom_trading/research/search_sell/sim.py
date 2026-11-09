"""2단계: 사건 다음 1분봉 시가에 50%/100% 팔았다면 수익률 (비용 같은 몫 적용).

매도 가격 (사건 분 m = 조회 스냅샷 분)
  09:00 ≤ m < 15:19 → KRX 1분봉 m+1 분 이후 첫 봉 시가 (5분 안에 봉 없으면 뺌)
  15:19 ≤ m < 20:00, 08:00 ≤ m < 08:50 → NXT(NX) 1분봉 m+1 분 이후 첫 봉 시가 (10분 안)
  08:50 ≤ m < 09:00 → KRX 09:00 시가
  매도 봉 시각이 실제 매도 시각 이후면 규칙이 바꾸는 것 없음(영향 없음).
1분봉: data/search_surge/bars.duckdb(KRX) 먼저, 없으면 키움에서 받아 data/search_sell/bars.duckdb 에 모음.
가격 기준 점검: 사건 분 1분봉 종가 vs 스냅샷 가격 차이 > 2% 면 표시(px_flag).
출력: data/search_sell/sim.parquet
"""
import os
from datetime import datetime, time, timedelta

import duckdb
import pandas as pd

ROOT = r"D:\Ellie\trading"
OUT = os.path.join(ROOT, "data", "search_sell")
OLD = duckdb.connect(os.path.join(ROOT, "data", "search_surge", "bars.duckdb"), read_only=True)
DB = duckdb.connect(os.path.join(OUT, "bars.duckdb"))
DB.execute("CREATE TABLE IF NOT EXISTS bars(code VARCHAR, d DATE, ex VARCHAR, ts TIMESTAMP, open BIGINT, high BIGINT, low BIGINT, close BIGINT, volume BIGINT)")
DB.execute("CREATE TABLE IF NOT EXISTS done(code VARCHAR, d DATE, ex VARCHAR, n INT)")
_cl = None


def client():
    global _cl
    if _cl is None:
        from kiwoom_trading.ingestion.collectors.daily_backfill import build_client
        _cl = build_client()
    return _cl


def bars(code, d, ex):
    if ex == "KRX":
        b = OLD.execute("SELECT ts, open, high, low, close FROM bars WHERE code=? AND d=? AND CAST(ts AS TIME) BETWEEN '09:00' AND '15:30' ORDER BY ts", [code, d]).df()
        if len(b): return b
    if not DB.execute("SELECT 1 FROM done WHERE code=? AND d=? AND ex=?", [code, d, ex]).fetchall():
        from kiwoom_trading.ingestion.collectors.minute_collector import fetch_minute_bars
        try:
            x = fetch_minute_bars(client(), code, d, ex)
        except Exception as e:
            print("실패", code, d, ex, e, flush=True); x = []
        if x:
            df = pd.DataFrame(x)[["ts", "open", "high", "low", "close", "volume"]]
            df.insert(0, "ex", ex); df.insert(0, "d", d); df.insert(0, "code", code)
            DB.execute("INSERT INTO bars SELECT * FROM df")
        DB.execute("INSERT INTO done VALUES (?,?,?,?)", [code, d, ex, len(x)])
    b = DB.execute("SELECT ts, open, high, low, close FROM bars WHERE code=? AND d=? AND ex=? ORDER BY ts", [code, d, ex]).df()
    if ex == "KRX": b = b[(b.ts.dt.time >= time(9, 0)) & (b.ts.dt.time <= time(15, 30))]
    return b


def sell_price(code, hm):
    d, t = hm.date(), hm.time()
    if time(9, 0) <= t < time(15, 19):
        ex, lim = "KRX", 5
    elif time(8, 50) <= t < time(9, 0):
        ex, lim, hm = "KRX", 5, pd.Timestamp(datetime.combine(d, time(8, 59)))
    else:
        ex, lim = "NX", 10
    b = bars(code, d, ex)
    if not len(b): return None, None, ex, None
    j = b[b.ts >= hm + timedelta(minutes=1)]
    if not len(j) or j.ts.iat[0] > hm + timedelta(minutes=lim): return None, None, ex, None
    cur = b[b.ts <= hm]
    ref = float(cur.close.iat[-1]) if len(cur) else None
    return float(j.open.iat[0]), j.ts.iat[0], ex, ref


if __name__ == "__main__":
    P = pd.read_parquet(os.path.join(OUT, "positions.parquet")).set_index("id")
    E = pd.read_parquet(os.path.join(OUT, "events.parquet"))
    rows = []
    for k, e in enumerate(E.itertuples()):
        p = P.loc[e.id]
        px, sts, ex, ref = sell_price(p.code, pd.Timestamp(e.ev_hm))
        r = dict(e._asdict()); r.pop("Index")
        r.update(code=p.code, name=p["name"], kind=p.kind, date=p.date, buy_ts=p.buy_ts, buy=p.buy, exit_ts=p.exit_ts, act=p.act,
                 cost=p.cost, virtual=p.virtual, overflow=p.overflow, reason=p.reason, part=p.part, sell_ex=ex, sell_ts=sts, sell_px=px,
                 px_flag=(ref is not None and abs(ref / e.ev_price - 1) > 0.02))
        if px is None:
            r["status"] = "봉 없음"
        elif sts >= p.exit_ts:
            r["status"] = "실제 매도가 먼저"
        else:
            r["status"] = "적용"
            r["full"] = px / p.buy - 1 - p.cost
            r["half"] = 0.5 * r["full"] + 0.5 * p.act
        rows.append(r)
        if k % 50 == 0: print(k, len(E), flush=True)
    R = pd.DataFrame(rows)
    R.to_parquet(os.path.join(OUT, "sim.parquet"))
    print(R.groupby(["src", "N", "var", "status"]).size())
    print("가격 기준 차이 >2%:", int(R.px_flag.sum()))
