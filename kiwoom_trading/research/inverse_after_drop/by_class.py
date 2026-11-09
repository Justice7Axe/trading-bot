"""전날 급락 날을 오늘 09:10 시장 상황(U/N+/N-/D)으로 나눠 인버스 09:11 규칙 결과 — 5️⃣ 의 날 거르기가 이미 반등 날을 빼는지.

실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.inverse_after_drop.by_class → data/inverse_after_drop/by_class.txt
"""
import os
import sys
from datetime import time

import numpy as np

from kiwoom_trading.backtest.playbook.regime import cls, feat
from kiwoom_trading.research.inverse_after_drop import common as C

rep = open(os.path.join(C.OUT, "by_class.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(s + "\n"); rep.flush()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    KD = {r["date"]: r for r in C.idx_daily("001")}; kd = sorted(KD)
    KM = C.idx_min("001")
    NAME = {"U": "강한 상승장", "N+": "상승 흐름 보통 날", "N-": "하락 흐름 보통 날(5️⃣ 사는 날)", "D": "강한 하락장"}
    rows = []
    for d in sorted(feat):
        c = cls(d)
        if not c or d not in KD:
            continue
        i = kd.index(d)
        prev = KD[kd[i - 1]]["close"] / KD[kd[i - 2]]["close"] - 1
        x, _, _ = C.trade(d)
        bs = KM.get(d, [])
        b11 = next((b for b in bs if b["ts"].time() >= time(9, 11)), None)
        rest = KD[d]["close"] / b11["open"] - 1 if b11 else None
        rows.append(dict(date=d, c=c, prev=prev, ret=x, rest=rest, gap=KD[d]["open"] / KD[kd[i - 1]]["close"] - 1))
    for th in (-0.02, -0.03):
        say(f"\n## 전날 코스피 ≤ {th:+.0%} 다음 날 — 오늘 09:10 시장 상황별 (2025-10-15 ~ 2026-10-23)")
        for c in ("U", "N+", "N-", "D"):
            g = [r for r in rows if r["prev"] <= th and r["c"] == c]
            if not g:
                say(f"  {NAME[c]:22s} 0일"); continue
            say(f"  {NAME[c]:22s} {len(g):2d}일 | 오늘 갭 {np.mean([r['gap'] for r in g]):+.2%} | 09:11→종가 코스피 {np.mean([r['rest'] for r in g if r['rest'] is not None]):+.2%} "
                f"| 인버스 09:11 +5/−3: {C.fmt(C.summ([(r['date'], r['ret']) for r in g if r['ret'] is not None]))}")
    say("\n## (참고) 전날 구간 상관없이 시장 상황별 인버스 09:11 +5/−3")
    for c in ("U", "N+", "N-", "D"):
        g = [r for r in rows if r["c"] == c and r["ret"] is not None]
        say(f"  {NAME[c]:22s} {C.fmt(C.summ([(r['date'], r['ret']) for r in g]))}")


if __name__ == "__main__":
    main()
