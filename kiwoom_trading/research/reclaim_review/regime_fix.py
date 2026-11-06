"""2026-09-14 뒤 시장 분위기 M0 바로잡기 → trades.pkl 의 reg 덮어씀 (옛 값은 reg_old).

build_regime 의 M0 는 전일 종가를 일봉 종가로 쓰는데, 9-14 부터 일봉 종가 = 20:00 애프터 종가라 실제 장중 판정(정규장 종가 기준)과 어긋남
(예: 11-04 실제 판정 중앙 +2.9% 강한 상승장 ↔ 재계산 +1.0% 보통). 그래서 9-14 뒤는 전일 정규장 마지막 1분봉 종가로 다시 계산함.
실행: PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m kiwoom_trading.research.reclaim_review.regime_fix
"""
import os
import pickle
import sys
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of

OUT = os.path.join(E.DATA, "reclaim_review")
SW = date(2026, 9, 14)


def m0(d):
    p = E.prev_day(d)
    U = [c for c, r in E.value_rank(p).items() if r <= 200]
    B, P = E.load_day(U, d), E.load_day(U, p)
    ch = []
    for c in U:
        b = [x for x in B.get(c) or [] if time(9, 0) <= x[0] <= time(15, 20)]
        pr = E.regular(P.get(c) or [])
        if len(b) < 60 or b[0][0] > time(9, 1) or not pr:
            continue
        x = [y for y in b if y[0] < time(9, 10)]
        if x:
            ch.append(x[-1][4] / pr[-1][4] - 1)
    return float(np.median(ch)) if len(ch) >= 100 else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    T = pickle.load(open(os.path.join(OUT, "trades.pkl"), "rb"))
    days = sorted({t["date"] for t in T if t["date"] >= SW})
    new = {}
    for d in days:
        t0 = next(t for t in T if t["date"] == d)
        v = m0(d)
        if v is None:
            continue
        x = dict(M0=v, K1z=t0["K1z"], dd52=t0["dd52"])
        new[d] = (v, cls_of(x))
        print(f"{d} M0 {t0['M0']:+.4f} → {v:+.4f}  {t0['reg']} → {new[d][1]}")
    for t in T:
        t.setdefault("reg_old", t["reg"])
        if t["date"] in new:
            t["M0"], t["reg"] = new[t["date"]]
    pickle.dump(T, open(os.path.join(OUT, "trades.pkl"), "wb"))


if __name__ == "__main__":
    main()
