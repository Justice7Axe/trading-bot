"""중심선 강한 돌파 매수 (2026-10-30 사용자 '그냥 중심선을 강하게 돌파할 때 매수').

기준봉·대상 U·중심선은 backtest_cross.py 와 같음 (U0 없음 · U1 20위&평소 10배 · U2 300억&30위&전날 100위 밖 · U3 100억&50위&전날 200위 밖 · U4 300억&평소 5배).
강한 돌파 봉 (기준봉 뒤 1~10일, 정규장 1분봉 09:00~15:00): 직전 봉 종가 < C ≤ 이번 봉 종가,
  봉 대금 ≥ 10억 & ≥ 직전 20봉 평균 × M (M = 3·5·10), 선택: 봉 상승 ≥ +1% (B1)
  → 다음 봉 시가 매수. 기준봉 하나에 첫 강한 돌파 한 번.
매도: 익절 +2/+3/+5% · 손절 S0 1분봉 종가 C 아래 → 다음 봉 시가 / S1 C−0.5% / S2 C−1% (같은 봉 손절 먼저) · 못 닿으면 다음 날 09:00.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.centerline.backtest_strong → data/centerline/strong.txt
"""
import os
import sys
from collections import defaultdict
from datetime import time
from itertools import product

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.regime import cls
from kiwoom_trading.strategies.centerline import backtest_cross as X

WAIT = 10


def strong_entry(b, mult, body):
    d0, c, o, h, l, cl = b
    i0 = E.CIDX[d0]
    for k in range(1, WAIT + 1):
        if i0 + k >= len(E.CAL) or E.CAL[i0 + k] > E.P1: return None
        d = E.CAL[i0 + k]
        f = E.factor(c, d)
        if f is None: continue
        C = (o + cl) / 2 * f
        bars = E.regular(E.bars(c, d))
        for j in range(1, len(bars) - 1):
            x, p = bars[j], bars[j - 1]
            if x[0] > time(15, 0): break
            if not (p[4] < C <= x[4]): continue
            val = x[4] * x[5]; prev = [y[4] * y[5] for y in bars[max(0, j - 20):j]]
            if val < 1e9 or not prev or val < np.mean(prev) * mult: continue
            if body and x[4] / x[1] - 1 < 0.01: continue
            return d, bars, j + 1, C
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fo = open(os.path.join(X.OUT, "strong.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); fo.write(s + "\n"); fo.flush()

    rep = E.Report.__new__(E.Report); rep.f = fo
    BS = X.B.bases(0.10)
    U = {(b[0], b[1]): X.universe(b) for b in BS}
    say(f"중심선 강한 돌파, 1분봉 {E.P0}~{E.P1}, 기준봉 {len(BS)}개, 대기 {WAIT}일, 다음 봉 시가 매수, 비용 0.25%")
    best = []
    for mult, body in product((3, 5, 10), (False, True)):
        EN = {k: e for b in BS if (e := strong_entry(b, mult, body)) for k in [(b[0], b[1])]}
        say(f"\n===== 돌파 봉 대금 10억↑ & 평균 {mult}배{' & 봉 +1%↑' if body else ''}: {len(EN)}건 =====")
        for u in ("U0", "U1", "U2", "U3", "U4"):
            keys = [k for k in EN if U[k][u]]
            if len(keys) < 15:
                say(f"  [{u}] {len(keys)}건 (적음)"); continue
            for tp, st in product((0.02, 0.03, 0.05), ("S0", "S1", "S2")):
                tr = []
                for k in keys:
                    d, bars, j, C = EN[k]
                    r, w = X.exit_(k[1], d, bars, j, C, tp, st)
                    if r is not None and abs(r) < 0.35: tr.append((d, r))
                res = rep.stats(tr, f"  [{u}] 익절 +{tp:.0%} {st}", 22)
                if res: best.append((res["mean"], res["star"], mult, body, u, tp, st, len(tr)))
    best.sort(key=lambda x: -x[0])
    say("\n건당 상위 10 (조합이 많아 우연 가능):")
    for m, star, mult, body, u, tp, st, n in best[:10]:
        say(f"  {'★' if star else ' '} {u} 평균 {mult}배{' +1%봉' if body else ''} 익절 +{tp:.0%} {st}: {n}건 {m:+.2%}")
    say(f"★ 조합 {sum(1 for x in best if x[1])}/{len(best)}, 플러스 {sum(1 for x in best if x[0] > 0)}/{len(best)}")
    say("\n시장 상황별 (U0·평균 5배·익절 +3%·S1):")
    EN = {k: e for b in BS if (e := strong_entry(b, 5, False)) for k in [(b[0], b[1])]}
    g = defaultdict(list)
    for k, (d, bars, j, C) in EN.items():
        r, _ = X.exit_(k[1], d, bars, j, C, 0.03, "S1")
        if r is not None and abs(r) < 0.35: g[cls(d) or "?"].append(r)
    say("  " + " · ".join(f"{k} {len(v)}건 {np.mean(v):+.2%}" for k, v in sorted(g.items())))


if __name__ == "__main__":
    main()
