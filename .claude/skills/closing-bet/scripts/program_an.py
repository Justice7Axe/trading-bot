"""프로그램 순매수(일별 ka90013)로 종가배팅 종목 선정 보완 — 🌙 종가 재돌파(18시 전 진입)와 정규장 종가 매수.

프로그램 비중 = 그날 프로그램 순매수 금액 / 그날 거래대금 (daily_ohlcv.value, KRX).
'원웨이 매수'(책 95쪽)는 장중 모양이라 과거 자료가 없다 → 하루 합계·며칠 연속으로 대신 본다.
"""
import os, pickle, shutil, tempfile
from collections import defaultdict
from datetime import time
import duckdb
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
S = os.path.join(ROOT, "data", "closing_bet")
P = pickle.load(open(os.path.join(S, "program_daily.pkl"), "rb"))
T = [t for t in pickle.load(open(os.path.join(S, "rebreak_feat.pkl"), "rb")) if t["f"]["entry_hour"] < 18]
D = pickle.load(open(os.path.join(S, "dans_bars.pkl"), "rb"))
DAYS = sorted({r["date"] for r in D["rows"]}); HALF = DAYS[len(DAYS) // 2]
Q = [DAYS[0], DAYS[len(DAYS) // 4], DAYS[len(DAYS) // 2], DAYS[3 * len(DAYS) // 4], DAYS[-1]]
COST = 0.0025
dst = os.path.join(tempfile.gettempdir(), "pan_daily.duckdb"); shutil.copy(os.path.join(ROOT, "data", "daily_ohlcv.duckdb"), dst)
dm = duckdb.connect(dst, read_only=True)
VAL = {(c, d): v for c, d, v in dm.execute("SELECT code, date, value FROM daily_ohlcv WHERE date >= '2025-10-01'").fetchall()}
pdays = defaultdict(list)
for (c, d) in P:
    pdays[c].append(d)
for c in pdays:
    pdays[c].sort()


def feat(code, d):
    x = P.get((code, d))
    if x is None:
        return None
    v = VAL.get((code, d)) or 0
    ds = [z for z in pdays[code] if z <= d][-3:]
    nets = [P[(code, z)][0] for z in ds]
    return dict(net=x[0], ratio=x[0] / v if v else 0, streak=sum(1 for n in nets if n > 0), prev=nets[-2] if len(nets) >= 2 else None)


def stats(tr, title):
    if len(tr) < 20:
        print(f"  {title:46s} {len(tr)}건 (적음)"); return
    v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < HALF]; b = [x for d, x in tr if d >= HALF]
    bd = defaultdict(float)
    for d, x in tr: bd[d] += x
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    s = sorted(bd.values(), reverse=True)
    qs = " ".join(f"{np.mean([x for d, x in tr if lo <= d < hi]) if any(lo <= d < hi for d, _ in tr) else 0:+.2%}" for lo, hi in zip(Q, Q[1:]))
    print(f"  {title:46s} {len(v):4d}건 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+5.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+5.0f}만 "
          f"| 앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%} | 분기 {qs} | 낙폭 {mdd * 100:.0f}만")


def run(items, label):
    """items: [(date, ret, code)]"""
    rows = [(d, r, feat(c, d)) for d, r, c in items]
    ok = [(d, r, f) for d, r, f in rows if f]
    print(f"\n=== {label}: {len(items)}건 중 프로그램 자료 {len(ok)}건")
    stats([(d, r) for d, r, _ in ok], "전체 (자료 있는 것)")
    stats([(d, r) for d, r, f in ok if f["net"] > 0], "그날 프로그램 순매수 +")
    stats([(d, r) for d, r, f in ok if f["net"] <= 0], "그날 프로그램 순매수 − (순매도)")
    stats([(d, r) for d, r, f in ok if f["ratio"] >= 0.02], "프로그램 순매수 ≥ 거래대금 2%")
    stats([(d, r) for d, r, f in ok if f["ratio"] <= -0.02], "프로그램 순매도 ≥ 거래대금 2%")
    stats([(d, r) for d, r, f in ok if f["streak"] >= 2], "최근 3일 중 2일↑ 순매수")
    stats([(d, r) for d, r, f in ok if f["streak"] == 3], "3일 연속 순매수")
    stats([(d, r) for d, r, f in ok if f["prev"] is not None and f["prev"] > 0 and f["net"] > 0], "전날·오늘 연속 순매수")
    xs = sorted(ok, key=lambda z: z[2]["ratio"])
    print("  -- 프로그램 순매수/거래대금 다섯 구간")
    for idx in np.array_split(np.arange(len(xs)), 5):
        part = [xs[i] for i in idx]
        stats([(d, r) for d, r, _ in part], f"{part[0][2]['ratio']:+.3f} ~ {part[-1][2]['ratio']:+.3f}")


def o9(r):
    reg = [b for b in r["n_bars"] if b[0] >= time(9, 0)]
    return reg[0][1] if reg and reg[0][0] <= time(9, 5) else None


if __name__ == "__main__":
    run([(t["date"], t["ret"], t["r"]["code"]) for t in T], "🌙 종가 재돌파 (대금 10위·상승, 18시 전 진입)")
    base = [r for r in D["rows"] if r["rk"] <= 10 and r["chg"] < 0.295]
    run([(r["date"], o9(r) / r["close"] - 1 - COST, r["code"]) for r in base if o9(r)], "정규장 종가 매수 (대금 10위·상승)")
