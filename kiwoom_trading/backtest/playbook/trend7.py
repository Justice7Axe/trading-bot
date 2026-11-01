"""⑦ 주도주 추세 보유 — 일봉 (원래 d9b9b62e/swing.py 앞부분 + swing3.py).

신호 = 그날 종가가 52주 신고가 & 그날 대금 순위 (f7: 5위 안 & 외인·기관 둘 다 순매수) → 다음 날 시가 매수,
매도 = 종가 20일선 아래 → 다음 날 시가. 금액 100만 원(1주 > 100만이면 1주), 비용 0.25%. 일봉 수정주가.
"""
from collections import defaultdict
from datetime import date

import duckdb
import numpy as np
import pandas as pd

import os

from kiwoom_trading.backtest.playbook.paths import DAILY_DB

START = os.environ.get("TREND7_START", "2024-06-01")     # 4년: TREND7_START=2022-01-01 (2026-11-01)

COST = 0.0025
BUDGET = 1_000_000

_dd = duckdb.connect(DAILY_DB, read_only=True)
df = _dd.execute("""select d.code, d.date, d.open, d.high, d.low, d.close, d.value from daily_ohlcv d join stocks s using(code)
                    where d.date >= ? order by d.code, d.date""", [START]).df()
df["date"] = pd.to_datetime(df["date"]).dt.date
G = {c: g.reset_index(drop=True) for c, g in df.groupby("code")}


def ind(g):
    c, h, l = g.close, g.high, g.low
    out = {"c": c.values, "o": g.open.values, "h": h.values, "l": l.values}
    for n in (5, 10, 20, 30, 60):
        out[f"ma{n}"] = c.rolling(n).mean().values
    for n in (5, 10, 20, 55):
        out[f"hh{n}"] = h.rolling(n).max().shift(1).values
        out[f"ll{n}"] = l.rolling(n).min().shift(1).values
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    out["atr"] = tr.rolling(14).mean().values
    return out


shares = dict(_dd.execute("select code, listed_shares from stocks").fetchall())
sector = dict(_dd.execute("select code, sector from stocks").fetchall())
_inv = _dd.execute("select code, date, foreign_, institution from investor_daily where date >= ?", [START]).df()
_inv["date"] = pd.to_datetime(_inv["date"]).dt.date
INV = {(c, d): (f, i) for c, d, f, i in zip(_inv.code, _inv.date, _inv.foreign_, _inv.institution)}
df["vr"] = df.groupby("date").value.rank(ascending=False, method="first")
VR = {(c, d): r for c, d, r in zip(df.code, df.date, df.vr)}
alld = sorted(set(df.date))

feat = {}
NH = defaultdict(list)
for c, g in G.items():
    if len(g) < 300: continue
    x = ind(g); ds = list(g.date)
    h250 = g.high.rolling(250, min_periods=200).max().shift(1).values
    h60 = g.high.rolling(60).max().shift(1).values
    v20 = g.value.rolling(20).mean().shift(1).values
    c60 = g.close.pct_change(60).values
    ma60 = g.close.rolling(60).mean().values; ma120 = g.close.rolling(120).mean().values
    for i in range(260, len(ds)):
        if h250[i] == h250[i] and x["c"][i] >= h250[i]:
            NH[ds[i]].append(c)
        feat[(c, ds[i])] = dict(i=i, nh=h250[i] == h250[i] and x["c"][i] >= h250[i], nh60=h60[i] == h60[i] and x["c"][i] >= h60[i],
                                near=x["c"][i] / h250[i] if h250[i] == h250[i] else np.nan, vratio=g.value.values[i] / v20[i] if v20[i] else np.nan,
                                r60=c60[i], up60=x["c"][i] > ma60[i] > ma120[i] if ma120[i] == ma120[i] else False,
                                mcap=x["c"][i] * (shares.get(c) or 0), chg=x["c"][i] / x["c"][i - 1] - 1)
X = {c: ind(g) for c, g in G.items() if len(g) >= 300}
DS = {c: list(g.date) for c, g in G.items() if len(g) >= 300}


def trades(sel):
    out = []
    for c, ds in DS.items():
        x = X[c]; i = 260
        while i < len(ds) - 1:
            d = ds[i]; f = feat.get((c, d))
            if f and sel(c, d, f):
                e = i + 1; px = x["o"][e]; qty = max(1, int(BUDGET // px)); j = e; out_i = None
                while j < len(ds) - 1:
                    if x["ma20"][j] == x["ma20"][j] and x["c"][j] < x["ma20"][j]:
                        out_i = j + 1; break
                    j += 1
                sell = x["o"][out_i] if out_i else x["c"][-1]; out_i = out_i or len(ds) - 1
                out.append(dict(code=c, sig=d, buy_d=ds[e], buy=px, qty=qty, sell_d=ds[out_i], sell=sell, open=out_i == len(ds) - 1 and j >= len(ds) - 2,
                                r=sell / px * (1 - COST) - 1, won=qty * (sell - px) - qty * px * COST, days=out_i - e))
                i = out_i
            else:
                i += 1
    return out


def f7(c, d, f):
    """⑦ 매매표 조건: 52주 신고가 & 대금 5위 & 그날 외인·기관 둘 다 순매수."""
    return (f["nh"] and VR.get((c, d), 999) <= 5 and (INV.get((c, d), (0, 0))[0] or 0) > 0
            and (INV.get((c, d), (0, 0))[1] or 0) > 0)
