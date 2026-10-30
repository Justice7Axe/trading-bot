"""중심선 돌파 매수 (2026-10-30 사용자: '중심선을 돌파할 때 사고 2~3% 상승 시 익절, 중심선을 깨면 손절.
대상은 잡주가 아니라 거래대금이 일정 수준 이상이면서 순위 가속도가 된 종목').

기준봉 (일봉, 매수 전날까지 앎): 양봉 +10%↑·거래량 20일 평균 3배·대금 100억↑ + 대상 거르기 U
  U0 거르기 없음 · U1 대금 20위 안 & 평소 대금 10배 · U2 대금 300억↑ & 30위 안 & 전날 순위 100위 밖(순위 급등)
  U3 대금 100억↑ & 50위 안 & 전날 순위 200위 밖 · U4 대금 300억↑ & 평소 대금 5배
중심선 C = 기준봉 정규장 (시가+종가)/2 → 1분봉 가격으로 factor 맞춤.
매수 (기준봉 뒤 1~W일, 정규장 1분봉): 1분봉 종가가 C 아래였던 뒤 C 위로 마감(돌파) → 다음 봉 시가 매수, 09:00~15:00.
  시가부터 C 위면 먼저 C 아래로 내려와야 함. 기준봉 하나에 한 번(첫 돌파)만.
매도: 익절 +2/+3% 닿으면 그 가격 · 손절 S0 1분봉 종가 C 아래 → 다음 봉 시가 / S1 C−0.5% 닿으면 / S2 C−1% 닿으면 (같은 봉이면 손절 먼저)
  · 둘 다 아니면 다음 날 09:00 시가. 비용 0.25%.
⚠️ 1분봉은 날짜별 대금 상위 500 이라 매수 날 대금이 작은 종목은 빠질 수 있음 → 매수 시점 누적 대금 ≥ 30억만 셈(빠지는 종목 영향 줄임).
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.centerline.backtest_cross → data/centerline/cross.txt
"""
import os
import sys
from collections import defaultdict
from datetime import date, time
from itertools import product

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.regime import cls
import kiwoom_trading.strategies.centerline.backtest as B
from kiwoom_trading.strategies.centerline.backtest_filters import accel

OUT = B.OUT
B.DAYS = [d for d in E.CAL if E.CAL[E.CIDX[E.P0] - 10] <= d <= E.P1]
MIN_CUM = 3e9


def universe(b):
    d, c = b[0], b[1]
    v = E.daily_day(d)[c][5] or 0; rk = E.value_rank(d).get(c, 9999); prk = E.value_rank(E.prev_day(d)).get(c, 9999); ac = accel(c, d)
    return {"U0": True, "U1": rk <= 20 and ac >= 10, "U2": v >= 3e10 and rk <= 30 and prk > 100,
            "U3": v >= 1e10 and rk <= 50 and prk > 200, "U4": v >= 3e10 and ac >= 5}


def entry(b, wait):
    """→ (매수 날, 봉 목록, 매수 봉 index, 1분봉 기준 C) 또는 None."""
    d0, c, o, h, l, cl = b
    i0 = E.CIDX[d0]
    for k in range(1, wait + 1):
        if i0 + k >= len(E.CAL) or E.CAL[i0 + k] > E.P1: return None
        d = E.CAL[i0 + k]
        dd = E.daily_day(d).get(c)
        if not dd: return None
        f = E.factor(c, d)
        if f is None:
            if dd[2] <= (o + cl) / 2 * 1.02: return None   # 1분봉이 없는데 중심선 근처까지 온 날 → 그 뒤는 모름, 끝
            continue
        C = (o + cl) / 2 * f
        bars = E.regular(E.bars(c, d))
        below = False; cum = 0.0
        for j, x in enumerate(bars[:-1]):
            cum += x[4] * x[5]
            if x[0] > time(15, 0): break
            if x[4] < C: below = True
            elif below and x[4] >= C and cum >= MIN_CUM:
                return d, bars, j + 1, C
        if dd[3] < (o + cl) / 2 * 0.9: return None          # 중심선보다 한참 밑으로 무너짐 → 기준봉 끝
    return None


def exit_(c, d, bars, j, C, tp, stop):
    buy = bars[j][1]; tpp = buy * (1 + tp)
    sp = C * (1 - {"S1": 0.005, "S2": 0.01}.get(stop, 0))
    for k in range(j, len(bars)):
        x = bars[k]
        if x[0] > time(15, 19): break
        if stop == "S0":
            if k > j and bars[k - 1][4] < C: return x[1] / buy - 1 - E.COST, "손절"
        elif x[3] <= sp:
            return min(x[1], sp) / buy - 1 - E.COST, "손절"
        if k > j and x[2] >= tpp: return max(x[1], tpp) / buy - 1 - E.COST, "익절"
        if k == j and x[4] >= tpp: return tpp / buy - 1 - E.COST, "익절"   # 매수 봉: 시가에 사고 그 봉 종가가 익절가 위면 익절 (봉 안 순서 모름 → 보수적으로 종가 확인)
    ex = E.next_day_exits(c, d, buy).get("09:00 시가")
    return (ex, "다음 날") if ex is not None else (None, None)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fo = open(os.path.join(OUT, "cross.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); fo.write(s + "\n"); fo.flush()

    rep = E.Report.__new__(E.Report); rep.f = fo
    BS = [b for b in B.bases(0.10)]
    U = {(b[0], b[1]): universe(b) for b in BS}
    say(f"중심선 돌파 매수, 1분봉 {E.P0}~{E.P1}, 기준봉 {len(BS)}개 (+10%·거래량 3배·대금 100억), 매수 시점 누적 대금 {MIN_CUM / 1e8:.0f}억↑")
    say("U0 없음 · U1 20위&평소 10배 · U2 300억&30위&전날 100위 밖 · U3 100억&50위&전날 200위 밖 · U4 300억&평소 5배")
    say("S0 1분봉 종가 중심선 아래 → 다음 봉 · S1 중심선 −0.5% · S2 −1% / 못 닿으면 다음 날 09:00")
    for wait in (5, 10):
        E_ = {}
        for b in BS:
            e = entry(b, wait)
            if e: E_[(b[0], b[1])] = e
        say(f"\n===== 기준봉 뒤 {wait}일 안 첫 돌파: 매수 {len(E_)}건 =====")
        for u in ("U0", "U1", "U2", "U3", "U4"):
            keys = [k for k in E_ if U[k][u]]
            say(f"\n[{u}] {len(keys)}건")
            for tp, st in product((0.02, 0.03), ("S0", "S1", "S2")):
                tr, why = [], defaultdict(int)
                for k in keys:
                    d, bars, j, C = E_[k]
                    r, w = exit_(k[1], d, bars, j, C, tp, st)
                    if r is None or abs(r) > 0.35: continue
                    tr.append((d, r)); why[w] += 1
                rep.stats(tr, f"  익절 +{tp:.0%} 손절 {st}  {dict(why)}", 52)
    # 고른 조합 시장 상황별
    say("\n[참고] 10일 · 익절 +3% · S1 — 시장 상황별 (매수 날, 09:10 판정)")
    for u in ("U0", "U1", "U2", "U4"):
        g = defaultdict(list)
        for b in BS:
            if not U[(b[0], b[1])][u]: continue
            e = entry(b, 10)
            if not e: continue
            r, _ = exit_(b[1], e[0], e[1], e[2], e[3], 0.03, "S1")
            if r is not None and abs(r) < 0.35: g[cls(e[0]) or "?"].append(r)
        say(f"  {u}: " + " · ".join(f"{k} {len(v)}건 {np.mean(v):+.2%}" for k, v in sorted(g.items())))


if __name__ == "__main__":
    main()
