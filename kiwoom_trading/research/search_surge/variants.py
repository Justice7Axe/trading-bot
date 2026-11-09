"""5단계: 조회 급증을 '바로 사는 신호'가 아닌 '알림 뒤 다른 타점'으로 쓰면 나은가.

같은 사건(S=조회 첫 등장, 비교 V30_ns = 조회 없이 대금 가속 30억)에 대해 진입만 바꾼다. 매도 동일(손절 −3%·익절 +5%·아니면 다음 날 09:00, 비용 0.25%).
  A 돌파 확인: 사건 뒤 60분 안에 사건 분까지의 그날 고점을 넘는 첫 봉 → 고점 가격(시가가 이미 넘었으면 시가)
  B VWAP 눌림: 사건 뒤 90분 안에 저가가 VWAP 이하로 닿고 종가가 VWAP 위로 끝난 첫 봉 → 다음 봉 시가
  C 30분 뒤 유지: 사건 30분 뒤 종가가 사건 진입가 이상이면 그다음 봉 시가
  D 종가 보유: 15:19 종가가 그날 시가 대비 +5%↑ & 고점 −3% 안 → 15:19 종가 매수, 다음 날 09:00 시가 매도 (손절 없음)
"""
import os
from datetime import date, time, timedelta
import duckdb
import numpy as np
import pandas as pd

OUT = r"D:\Ellie\trading\data\search_surge"
COST = 0.0025
B = duckdb.connect(os.path.join(OUT, "bars.duckdb"), read_only=True)
TRADING = [date(2026, 10, x) for x in (13, 14, 15, 16, 19, 20, 21, 22, 23, 26, 27, 28, 29, 30)]
nxt = lambda d: next((x for x in TRADING if x > d), None)
_c = {}


def bars(c, d):
    if (c, d) not in _c:
        _c[(c, d)] = B.execute("SELECT ts, open, high, low, close, volume FROM bars WHERE code=? AND d=? AND CAST(ts AS TIME) BETWEEN '09:00' AND '15:30' ORDER BY ts", [c, d]).df().drop_duplicates("ts").reset_index(drop=True)
    return _c[(c, d)]


def sim(b, j, buy, nb, stop=0.03, tp=0.05, intrabar_tp=True):
    sp, tpp = buy * (1 - stop), buy * (1 + tp)
    for k in range(j, len(b)):
        o, h, l = b.open.iat[k], b.high.iat[k], b.low.iat[k]
        if l <= sp: return min(o, sp) / buy - 1 - COST
        if (k > j or intrabar_tp) and h >= tpp: return max(o, tpp) / buy - 1 - COST
    return nb.open.iat[0] / buy - 1 - COST if nb is not None and len(nb) else np.nan


def stats(name, rows):
    d = pd.DataFrame(rows, columns=["date", "r"]).dropna()
    if d.empty: return f"  {name:28s} 0건"
    ds = sorted(d.date.unique()); h = ds[len(ds) // 2]
    a, b = d[d.date < h].r.mean(), d[d.date >= h].r.mean()
    bd = d.groupby("date").r.sum().sort_values(ascending=False)
    star = len(d) >= 15 and a > 0 and b > 0 and bd.iloc[5:].sum() > 0
    return (f" {'★' if star else ' '}{name:28s} {len(d):4d}건 {d.date.nunique():2d}일 건당 {d.r.mean():+.2%} 중앙 {d.r.median():+.2%} 승률 {(d.r > 0).mean():.0%} "
            f"앞 {a:+.2%} 뒤 {b:+.2%} 최고5일빼면 {bd.iloc[5:].sum()*100:+.0f}%")


def main():
    t = pd.read_parquet(os.path.join(OUT, "trades_feat.parquet"))
    groups = {"S 조회 급증": t[t.kind == "S"], "V30 조회 없음(비교)": t[(t.kind == "V30") & ~t.srch10], "V30 조회 있음": t[(t.kind == "V30") & t.srch10]}
    lines = []
    for gname, g in groups.items():
        res = {k: [] for k in "0ABCD"}
        for e in g.itertuples():
            b = bars(e.code, e.date); nb = bars(e.code, nxt(e.date)) if nxt(e.date) else None
            if len(b) < 30: continue
            hm = pd.Timestamp(e.hm)
            j0 = int(np.searchsorted(b.ts.values, np.datetime64(hm + timedelta(minutes=1))))
            if j0 >= len(b): continue
            res["0"].append((e.date, e.x_s3_t5))
            past = b.iloc[:j0]; past = past[past.ts < hm]
            hi = past.high.max() if len(past) else b.high.iat[0]
            # A 돌파 확인
            for k in range(j0, min(j0 + 60, len(b))):
                if b.high.iat[k] > hi:
                    buy = max(b.open.iat[k], hi * 1.001)
                    res["A"].append((e.date, sim(b, k, buy, nb, intrabar_tp=False))); break
            # B VWAP 눌림
            pv = (b.close * b.volume).cumsum(); vv = b.volume.cumsum().replace(0, np.nan); vwap = pv / vv
            for k in range(j0, min(j0 + 90, len(b) - 1)):
                if b.low.iat[k] <= vwap.iat[k - 1] and b.close.iat[k] > vwap.iat[k]:
                    res["B"].append((e.date, sim(b, k + 1, b.open.iat[k + 1], nb))); break
            # C 30분 뒤 유지
            k = j0 + 30
            if k + 1 < len(b) and b.close.iat[k] >= e.buy:
                res["C"].append((e.date, sim(b, k + 1, b.open.iat[k + 1], nb)))
            # D 종가 보유
            bb = b[b.ts.dt.time <= time(15, 19)]
            if len(bb) and nb is not None and len(nb):
                c = bb.close.iat[-1]
                if c / b.open.iat[0] - 1 >= 0.05 and c >= bb.high.max() * 0.97:
                    res["D"].append((e.date, nb.open.iat[0] / c - 1 - COST))
        lines.append(f"## {gname}")
        for k, nm in zip("0ABCD", ["0 바로 매수(기본)", "A 돌파 확인", "B VWAP 눌림", "C 30분 뒤 유지", "D 종가 보유→다음날 09:00"]):
            lines.append(stats(nm, res[k]))
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(OUT, "variants.txt"), "w", encoding="utf-8").write(txt + "\n")


if __name__ == "__main__":
    main()
