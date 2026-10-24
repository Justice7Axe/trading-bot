import os, pickle
from collections import defaultdict
import numpy as np

S = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")), "data", "closing_bet")
T = pickle.load(open(os.path.join(S, "closebet.pkl"), "rb"))
DAYS = sorted({r["date"] for r in T}); HALF = DAYS[len(DAYS) // 2]
EX = ["open", "0930", "1000", "close", (0.02, 0.03), (0.03, 0.03), (0.05, 0.03), (0.03, 0.05), (0.05, 0.05)]
NM = {"open": "다음 날 시가", "0930": "09:30", "1000": "10:00", "close": "15:19"}
nm = lambda k: NM.get(k) or f"+{k[0]:.0%}/-{k[1]:.0%}"

SETS = [
    ("대금 상위 200 전체 (기준선)", lambda r: True),
    ("오늘 주도주: +7%↑ · 종가 ≥ 고가 95% · 대금 30위 안", lambda r: r["chg"] >= 0.07 and r["near_high"] >= 0.95 and r["rk"] <= 30),
    ("강한 마감: +10~29% · 종가 ≥ 고가 97% · 대금 50위 안", lambda r: 0.10 <= r["chg"] and r["near_high"] >= 0.97 and r["rk"] <= 50),
    ("+5~10% · 종가 ≥ 고가 97%", lambda r: 0.05 <= r["chg"] < 0.10 and r["near_high"] >= 0.97),
    ("+3~7% · 종가 ≥ 고가 98% · 막판 30분 상승", lambda r: 0.03 <= r["chg"] < 0.07 and r["near_high"] >= 0.98 and r["late"] > 0),
    ("52주 신고가 마감 · +3%↑", lambda r: r["hi52"] is not None and r["hi52"] >= 0 and r["chg"] >= 0.03),
    ("대금 10위 안 · 상승 마감", lambda r: r["rk"] <= 10 and r["chg"] > 0),
]


def show(rows, title):
    if len(rows) < 30:
        print(f"\n== {title}: {len(rows)}건 (적음)"); return
    print(f"\n== {title}: {len(rows)}건 {len({r['date'] for r in rows})}일 (하루 {len(rows) / len({r['date'] for r in rows}):.1f}), 다음 날 시가 갭 중앙 {np.median([r['gap'] for r in rows]):+.2%}")
    for k in EX:
        v = np.array([r["ex"][k] for r in rows])
        a = [r["ex"][k] for r in rows if r["date"] < HALF]; b = [r["ex"][k] for r in rows if r["date"] >= HALF]
        w, l = v[v > 0], v[v <= 0]
        bm = defaultdict(float)
        for r in rows: bm[r["date"].strftime("%y-%m")] += r["ex"][k]
        bd = defaultdict(float)
        for r in rows: bd[r["date"]] += r["ex"][k]
        best = max(bd.values())
        ok = "★" if np.mean(a) > 0 and np.mean(b) > 0 and v.sum() - best > 0 else " "
        print(f"  {ok} {nm(k):12s} 합계 {v.sum() * 1e6:+12,.0f}원 건당 {v.mean():+.2%} 손익비 {(w.mean() / -l.mean()) if len(w) and len(l) else 0:.2f} "
              f"| 앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%} | 플러스 달 {sum(1 for x in bm.values() if x > 0)}/{len(bm)}")


for title, f in SETS:
    rs = [r for r in T if f(r)]
    show(rs, title)
    if title.startswith("대금 상위 200"):
        continue
    for lab, g in (("시장 강함(그날 중앙 ≥ +1%)", lambda r: r["mkt"] >= 0.01), ("시장 보통", lambda r: -0.01 < r["mkt"] < 0.01), ("시장 약함(≤ −1%)", lambda r: r["mkt"] <= -0.01)):
        show([r for r in rs if g(r)], f"  └ {lab}")
