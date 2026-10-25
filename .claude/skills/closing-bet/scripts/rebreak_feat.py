"""🌙 종가 재돌파 보완 탐색 — 어떤 특징이 다음 날 결과를 가르는가 (dans_bars.pkl).

대상: 대금 10위 · 상승 마감 · 17:00~19:45 첫 1분봉 종가 > 정규장 종가에서 매수 → 다음 날 09:00 시가, 비용 0.25%.
특징을 다섯 구간(같은 건수)으로 나눠 건당·앞/뒤를 본다. 한쪽으로 고르게 기울어야 쓸 만하다.
진입 시점 변형: 늦게(18·19시) 확인, 두 번 확인(18시·19:40 모두 종가 위) 등.
"""
import os, pickle, sys
from collections import defaultdict
from datetime import time
import numpy as np

S = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")), "data", "closing_bet")
D = pickle.load(open(os.path.join(S, "dans_bars.pkl"), "rb"))
R = [r for r in D["rows"] if r["rk"] <= 10 and r["chg"] < 0.295]
DAYS = sorted({r["date"] for r in D["rows"]}); HALF = DAYS[len(DAYS) // 2]
COST = 0.0025


def o9(r):
    reg = [b for b in r["n_bars"] if b[0] >= time(9, 0)]
    return reg[0][1] if reg and reg[0][0] <= time(9, 5) else None


def px_at(bars, t):
    b = [x for x in bars if x[0] <= t]
    return b[-1][4] if b else None


def stats(tr, title):
    if len(tr) < 20:
        print(f"  {title:46s} {len(tr)}건 (적음)"); return
    v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < HALF]; b = [x for d, x in tr if d >= HALF]
    bd = defaultdict(float)
    for d, x in tr: bd[d] += x
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(eq) - eq).max()
    s = sorted(bd.values(), reverse=True)
    print(f"  {title:46s} {len(v):4d}건 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+5.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+5.0f}만 "
          f"| 앞 {np.mean(a) if a else 0:+.2%} 뒤 {np.mean(b) if b else 0:+.2%} | 플러스 {np.mean(v > 0):.0%} | 낙폭 {mdd * 100:.0f}만")


# ---- 진입 + 특징
T = []
for r in R:
    o = o9(r)
    if not o:
        continue
    c = r["close"]; bars = r["d_bars"]
    reg = [b for b in bars if b[0] <= time(15, 30)]
    am = [b for b in bars if b[0] >= time(15, 40)]
    e = next((b for b in am if time(17, 0) <= b[0] < time(19, 45) and b[4] > c), None)
    if not e:
        continue
    upto = [b for b in am if b[0] <= e[0]]
    reg_v = sum(b[5] for b in reg) or 1
    c1500 = next((b[4] for b in reg if b[0] >= time(15, 0)), c)
    f = dict(
        chg=r["chg"], rk=r["rk"], near_high=c / r["high"], late=c / c1500 - 1,
        entry_prem=e[4] / c - 1,                                   # 진입가가 종가보다 얼마나 위
        entry_hour=e[0].hour + e[0].minute / 60,
        am_vol=sum(b[5] for b in upto) / reg_v,                    # 진입까지 애프터 거래량 / 정규장 거래량
        am_low=min(b[3] for b in upto) / c - 1,                    # 진입 전 애프터 저가 (종가 대비)
        am_high=max(b[2] for b in upto) / c - 1,
        pre17=(px_at(am, time(16, 59)) or c) / c - 1,              # 17시 직전 애프터 가격
        kchg=r["kchg"] if r["kchg"] is not None else 0,
        pchg=r["pchg"] if r["pchg"] is not None else 0,
    )
    T.append(dict(date=r["date"], ret=o / e[4] - 1 - COST, f=f, r=r, e=e))

print(f"=== 기준: 재돌파 매수 {len(T)}건")
stats([(t["date"], t["ret"]) for t in T], "전체")

NAMES = {"chg": "그날 등락률", "rk": "대금 순위", "near_high": "종가/고가", "late": "막판 30분 흐름", "entry_prem": "진입가 종가 대비",
         "entry_hour": "진입 시각", "am_vol": "애프터 거래량/정규장", "am_low": "진입 전 애프터 저가", "am_high": "진입 전 애프터 고가",
         "pre17": "17시 직전 애프터 가격", "kchg": "코스피 등락", "pchg": "전날 등락률"}
for k, nm in NAMES.items():
    xs = sorted(T, key=lambda t: t["f"][k])
    q = np.array_split(np.arange(len(xs)), 5)
    print(f"\n-- {nm} ({k}) 다섯 구간")
    for idx in q:
        part = [xs[i] for i in idx]
        lo, hi = part[0]["f"][k], part[-1]["f"][k]
        stats([(t["date"], t["ret"]) for t in part], f"{lo:+.4f} ~ {hi:+.4f}")

# ---- 진입 시점 변형 (같은 대상)
print("\n=== 진입 시점 변형 (대금 10위 · 상승)")
VAR = {
    "17시 이후 처음 종가 위 (지금)": lambda am, c: next((b[4] for b in am if time(17, 0) <= b[0] < time(19, 45) and b[4] > c), None),
    "18시 이후 처음 종가 위": lambda am, c: next((b[4] for b in am if time(18, 0) <= b[0] < time(19, 45) and b[4] > c), None),
    "19시 이후 처음 종가 위": lambda am, c: next((b[4] for b in am if time(19, 0) <= b[0] < time(19, 45) and b[4] > c), None),
    "19:40 가격이 종가 위면 19:40 매수": lambda am, c: (lambda p: p if p and p > c else None)(px_at(am, time(19, 40))),
    "18:00·19:40 둘 다 종가 위 → 19:40": lambda am, c: (lambda p1, p2: p2 if p1 and p2 and p1 > c and p2 > c else None)(px_at(am, time(18, 0)), px_at(am, time(19, 40))),
    "17시 이후 종가 +0.5% 위 처음": lambda am, c: next((b[4] for b in am if time(17, 0) <= b[0] < time(19, 45) and b[4] > c * 1.005), None),
    "17시 이후 종가 +1% 위 처음": lambda am, c: next((b[4] for b in am if time(17, 0) <= b[0] < time(19, 45) and b[4] > c * 1.01), None),
}
for nm, fn in VAR.items():
    tr = []
    for r in R:
        o = o9(r); am = [b for b in r["d_bars"] if b[0] >= time(15, 40)]
        p = fn(am, r["close"]) if am else None
        if o and p:
            tr.append((r["date"], o / p - 1 - COST))
    stats(tr, nm)
pickle.dump(T, open(os.path.join(S, "rebreak_feat.pkl"), "wb"))
