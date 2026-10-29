"""중심선 후보 + '09:10 강한 하락장(D) 판정이면 아직 안 채워진 주문 취소' (2026-10-30 사용자 '해봐').

매수 날 1분봉(정규장)에서 저가가 중심선(1분봉 가격 기준 = 일봉 중심선 × factor)에 처음 닿은 시각 = 체결 시각.
D 날: 체결 시각 < 09:10 이면 이미 산 것(그대로), 09:10 이후면 취소(안 삼).
1분봉이 없는 매매는 '체결 시각 모름'으로 따로 센다.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.centerline.cancel_d → data/centerline/cancel_d.txt
"""
import os
import sys
from collections import Counter, defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.regime import cls
from kiwoom_trading.strategies.centerline.backtest import OUT
from kiwoom_trading.strategies.centerline.check import KC, trades


def fill_time(t):
    d, c = t["date"], t["code"]
    b = E.regular(E.bars(c, d)); f = E.factor(c, d)
    if len(b) < 30 or not f: return None
    C = t["C"] * f
    x = next((y for y in b if y[3] <= C), None)
    return x[0] if x else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    fo = open(os.path.join(OUT, "cancel_d.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); fo.write(s + "\n"); fo.flush()

    T = [t for t in trades() if E.P0 <= t["date"] <= E.P1]
    for t in T:
        r = E.daily_day(t["base_d"])[t["code"]]; t["C"] = (r[0] + r[3]) / 2
        t["ft"] = fill_time(t); t["cls"] = cls(t["date"])
    say(f"중심선 후보 1년 {len(T)}건 — 1분봉으로 체결 시각 찾음 {sum(t['ft'] is not None for t in T)}건, 모름 {sum(t['ft'] is None for t in T)}건")
    hist = Counter()
    for t in T:
        k = "모름" if t["ft"] is None else "09:00~09:09" if t["ft"] < time(9, 10) else "09:10~09:59" if t["ft"] < time(10) else "10:00~11:59" if t["ft"] < time(12) else "12:00 뒤"
        hist[k] += 1
    say("  체결 시각 분포: " + " · ".join(f"{k} {hist[k]}" for k in ("09:00~09:09", "09:10~09:59", "10:00~11:59", "12:00 뒤", "모름")))
    D = [t for t in T if t["cls"] == "D"]
    say(f"\n강한 하락장(D) 날 {len(D)}건 건당 {np.mean([t['ret'] for t in D]):+.2%}")
    g = defaultdict(list)
    for t in D:
        g["09:10 전 체결(못 피함)" if t["ft"] and t["ft"] < time(9, 10) else "09:10 뒤 체결 → 취소" if t["ft"] else "시각 모름"].append(t["ret"])
    for k, v in g.items():
        say(f"  {k:20s} {len(v):3d}건 건당 {np.mean(v):+.2%} 합계 {sum(v) * 100:+.0f}만")

    def keep(t, unknown_cancel):
        if t["cls"] != "D": return True
        if t["ft"] is None: return not unknown_cancel
        return t["ft"] < time(9, 10)

    say("\n100만/건 합계:")
    for lab, f in (("취소 없음", lambda t: True), ("D 취소 (시각 모름은 그대로 삼)", lambda t: keep(t, False)),
                   ("D 취소 (시각 모름도 취소로 봄)", lambda t: keep(t, True))):
        v = [t["ret"] for t in T if f(t)]
        say(f"  {lab:28s} {len(v):3d}건 건당 {np.mean(v):+.2%} 합계 {sum(v) * 100:+.0f}만")

    from kiwoom_trading.research.account_alloc import sim as S
    S.KINDS.append(KC); S.FULLNAME[KC] = "📍 중심선"
    base = set(S.KINDS) - {KC}
    say("\n계좌 전체 1년 (시드 1천만):")
    for lab, kinds in (("지금 배분", base), ("B6 (🔁·3️⃣ 뺌)", base - {"🔁", "3️⃣"})):
        r0 = S.run({"kinds": kinds})
        say(f"  {lab} 중심선 없음 {r0['final'] / 1e4:,.0f}만 낙폭 {r0['mdd']:.1%}")
        for tl, f in (("취소 없음", lambda t: True), ("D 취소", lambda t: keep(t, False))):
            add = [dict(date=t["date"], t=time(9, 0), kind=KC, code=t["code"], px=float("nan"), ret=t["ret"], sell_d=t["sell_d"], rk=0) for t in T if f(t)]
            for pool, amt in ((0.20, 0.05), (0.30, 0.05), (0.20, 0.10), (0.30, 0.10)):
                r = S.run({"kinds": kinds | {KC}, "cpool": pool, "c_amt": amt}, trades=S.T_ALL + add)
                say(f"    {tl:8s} 몫 {pool:.0%}·종목당 {amt:.0%}: {r['final'] / 1e4:9,.0f}만 ({r['final'] / r0['final'] - 1:+.0%}) 낙폭 {r['mdd']:.1%} "
                    f"앞 {r['front']:+.0%} 뒤 {r['back']:+.0%} {'★' if r['star'] else ' '} | 📍 {r['n_k'].get(KC, 0)}건 {r['pnl_k'].get(KC, 0) / 1e4:+,.0f}만")


if __name__ == "__main__":
    main()
