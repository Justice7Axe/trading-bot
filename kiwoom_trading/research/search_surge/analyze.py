"""3단계: 사건마다 매수(사건 분 다음 1분봉 시가) → 결과, 그 분까지 아는 1분봉·수급 특징 붙이기 → 조합 비교.

매도 (backtest-rules): 손절가 닿으면 즉시(같은 봉이면 손절 먼저), 익절가 닿으면 그 값, 둘 다 아니면 다음 날 09:00 시가. 비용 0.25%.
참고용으로 15:19 종가 청산도 같이 적는다 (실제 규칙은 다음 날 09:00).
출력: data/search_surge/trades.parquet, data/search_surge/report.txt
"""
import os
from datetime import date, datetime, time, timedelta
import duckdb
import numpy as np
import pandas as pd

ROOT = r"D:\Ellie\trading"
OUT = os.path.join(ROOT, "data", "search_surge")
COST = 0.0025
B = duckdb.connect(os.path.join(OUT, "bars.duckdb"), read_only=True)
S = duckdb.connect(os.path.join(ROOT, "data", "screener_snapshot.duckdb"), read_only=True)
TRADING = [date(2026, 10, x) for x in (13, 14, 15, 16, 19, 20, 21, 22, 23, 26, 27, 28, 29, 30)]


def nxt(d):
    later = [x for x in TRADING if x > d]
    return later[0] if later else None


_bars = {}


def bars(c, d):
    k = (c, d)
    if k not in _bars:
        df = B.execute("SELECT ts, open, high, low, close, volume FROM bars WHERE code=? AND d=? AND CAST(ts AS TIME) BETWEEN '09:00' AND '15:30' ORDER BY ts", [c, d]).df()
        _bars[k] = df.drop_duplicates("ts")
    return _bars[k]


PROG = S.execute("SELECT ts, date, code, net_amount FROM program_intraday").df()
INV = S.execute("SELECT ts, date, investor, code, net_amount FROM investor_intraday").df()
BUYSIG = S.execute("SELECT date, code, min(ts) ts, string_agg(DISTINCT source, ',') src FROM buy_signals GROUP BY 1, 2").df()
for _x in (PROG, INV, BUYSIG):
    _x["date"] = pd.to_datetime(_x["date"]).dt.date


def flow_at(c, d, hm):
    out = {}
    p = PROG[(PROG.code == c) & (PROG.date == d) & (PROG.ts <= hm)]
    if len(p):
        p = p.sort_values("ts"); out["prog"] = p.net_amount.iloc[-1]
        q = p[p.ts <= hm - timedelta(minutes=20)]
        out["prog_d20"] = p.net_amount.iloc[-1] - (q.net_amount.iloc[-1] if len(q) else 0)
    for inv in ("foreign", "institution"):
        x = INV[(INV.code == c) & (INV.date == d) & (INV.investor == inv) & (INV.ts <= hm)]
        if len(x): out[inv[:4]] = x.sort_values("ts").net_amount.iloc[-1]
    return out


def simulate(b, j, buy, stop, tp, nb):
    sp = buy * (1 - stop) if stop else None
    tpp = buy * (1 + tp) if tp else None
    for k in range(j, len(b)):
        o, h, l = b.open.iat[k], b.high.iat[k], b.low.iat[k]
        if sp and l <= sp: return min(o, sp) / buy - 1 - COST
        if tpp and h >= tpp: return max(o, tpp) / buy - 1 - COST
    if nb is None or nb.empty: return np.nan
    return nb.open.iat[0] / buy - 1 - COST


def main():
    ev = pd.read_parquet(os.path.join(OUT, "events.parquet"))
    ev = ev[ev.date < date(2026, 10, 30)].copy()
    rows = []
    for e in ev.itertuples():
        b = bars(e.code, e.date)
        if len(b) < 30: continue
        hm = pd.Timestamp(e.hm)
        j = b.index[b.ts >= hm + timedelta(minutes=1)]
        if not len(j): continue
        j = b.index.get_loc(j[0])
        if b.ts.iat[j] > hm + timedelta(minutes=5): continue        # 거래 정지·빈 봉 → 뺌
        past = b.iloc[:j]                                             # 사건 분 직전까지 끝난 봉 (hm 봉은 진행 중이라 j-1 까지 = hm 봉 포함? → hm 봉 빼기)
        past = past[past.ts < hm]
        if len(past) < 3: continue
        buy = b.open.iat[j]
        o9 = b.open.iat[0]
        val = past.close * past.volume
        vwap = val.sum() / max(past.volume.sum(), 1)
        v5 = val.iloc[-5:].sum(); navg = max(len(past) // 5, 1)
        v5_ratio = v5 / (val.sum() / navg) if val.sum() > 0 else np.nan
        hi = past.high.max()
        up = b.high.iloc[:j].max()
        # 상한가 근접 (+29%↑ from prev close?) 전날 종가 모름 → 그날 등락 cr 로
        nb = bars(e.code, nxt(e.date)) if nxt(e.date) else None
        f30 = b.iloc[j:j + 30]
        r = dict(e._asdict())
        r.update(buy=buy, ret_open=buy / o9 - 1, vs_vwap=buy / vwap - 1, vs_high=buy / hi - 1,
                 v5_val=v5, v5_ratio=v5_ratio, mfe30=f30.high.max() / buy - 1, mae30=f30.low.min() / buy - 1,
                 r1519=(b[b.ts.dt.time <= time(15, 19)].close.iat[-1] / buy - 1 - COST),
                 nd_open=(nb.open.iat[0] / buy - 1 - COST) if nb is not None and len(nb) else np.nan,
                 entry_t=b.ts.iat[j])
        for stop in (0.02, 0.03):
            for tp in (0.03, 0.05, None):
                r[f"x_s{int(stop*100)}_t{int(tp*100) if tp else 0}"] = simulate(b, j, buy, stop, tp, nb)
        r.update(flow_at(e.code, e.date, hm))
        sg = BUYSIG[(BUYSIG.code == e.code) & (BUYSIG.date == e.date)]
        if len(sg):
            r["sig_ts"] = sg.ts.iat[0]; r["sig_src"] = sg.src.iat[0]
        rows.append(r)
    tr = pd.DataFrame(rows)
    tr.to_parquet(os.path.join(OUT, "trades.parquet"))
    print(len(tr), tr.groupby("kind").size().to_dict())


if __name__ == "__main__":
    main()
