"""보조 검증: 일봉만으로 4년(2022-06~2026-10) — B 종가 확인 → 다음 날 시가 매수, 영상식 보유(종가 < VWMA100 → 다음 날 시가, 최대 20일).
일봉 수정주가끼리만 계산 (2026-09-14 뒤 시가 = 통합 일봉 시가라 근사). 대상: 전날 대금 상위 100, 우선주 제외, 상장 120일↑."""
import sys
import numpy as np
import pandas as pd
import duckdb

d = duckdb.connect(r"D:\Ellie\trading\data\daily_ohlcv.duckdb", read_only=True)
df = d.execute("SELECT d.code, d.date, d.open, d.high, d.low, d.close, d.volume, d.value FROM daily_ohlcv d JOIN stocks s USING(code) WHERE d.close > 0").df()
df["date"] = pd.to_datetime(df["date"]).dt.date
df = df[df.code.str[-1].apply(lambda x: x not in "579K")]
P = {k: df.pivot(index="date", columns="code", values=k).sort_index() for k in ("open", "high", "close", "volume", "value")}
C, O, H, V = P["close"], P["open"], P["high"], P["volume"].fillna(0)
VW = (C * V).rolling(100, min_periods=100).sum() / V.rolling(100, min_periods=100).sum()
B = (C < VW)
RUN = B.astype(int).groupby((~B).cumsum()).cumsum() if False else None
SL = VW / VW.shift(20) - 1
GAP = C / VW - 1
RK = P["value"].rank(axis=1, ascending=False)
idx = list(C.index)
COST = 0.0025
rows = []
for i in range(120, len(idx) - 2):
    prev, day = idx[i - 1], idx[i]
    cand = RK.loc[prev][RK.loc[prev] <= 100].index
    for c in cand:
        if np.isnan(VW.at[prev, c]) or not (C.at[prev, c] < VW.at[prev, c]) or not (C.at[day, c] > VW.at[day, c]):
            continue
        col = B[c].values
        run = 0
        while run < 120 and i - 1 - run >= 0 and col[i - 1 - run]:
            run += 1
        o = O[c].iloc[i + 1]
        if np.isnan(o) or o <= 0:
            continue
        res = {}
        for tp in (None, 0.10):
            ret = None; ex = False
            for k in range(i + 1, min(i + 23, len(idx))):
                ok, hk, ck = O[c].iloc[k], H[c].iloc[k], C[c].iloc[k]
                if np.isnan(ck):
                    continue
                if ex:
                    ret = ok / o - 1 - COST; break
                if tp and hk >= o * (1 + tp) and k > i + 1:
                    ret = max(ok, o * (1 + tp)) / o - 1 - COST; break
                if ck < VW[c].iloc[k] or k - (i + 1) >= 20:
                    ex = True
            res[tp] = ret
        n1 = O[c].iloc[i + 2]
        rows.append(dict(date=idx[i + 1], code=c, run=run, slope=SL.at[prev, c], gap=GAP.at[prev, c],
                         sw0=res[None], sw10=res[0.10], nextopen=(n1 / o - 1 - COST) if n1 == n1 else None))
T = pd.DataFrame(rows).dropna(subset=["sw0"])
T["y"] = pd.to_datetime(T.date).dt.year
base = T[(T.run >= 20) & (T.slope < 0) & (T.gap >= -0.05)]
out = open(r"D:\Ellie\trading\data\lectures\yt\msQZetf7_UI\bt_daily4y.txt", "w", encoding="utf-8")


def say(s):
    print(s); out.write(s + "\n")


for nm, S in (("조건 없음", T), ("기본(20일↑ 아래·선 내려옴·−5% 안)", base)):
    say(f"[{nm}]")
    for col, t in (("nextopen", "다음 날 시가 매도"), ("sw0", "보유: 종가<VWMA→다음날 시가"), ("sw10", "보유 + 10% 익절")):
        v = S[col].dropna()
        top = v.sort_values(ascending=False)
        say(f"  {t:28s} {len(v):5d}건 건당 {v.mean():+.2%} 승률 {np.mean(v > 0):.0%} 최고10건 빼면 {top.iloc[10:].mean():+.2%} | 해마다 " +
            " ".join(f"{y}:{S[S.y == y][col].mean():+.2%}({(S.y == y).sum()})" for y in sorted(S.y.unique())))
out.close()
