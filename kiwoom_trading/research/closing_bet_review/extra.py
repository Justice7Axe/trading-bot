"""추가 점검 — (1) 10만 계좌로 살 수 있는 가격대(1주 ≤ 10만)만의 성적, (2) 처음 보는 기간(일봉)에서 시총·가격 효과,
(3) 시드 크기별 실전 규칙 계좌, (4) 실전 계좌에서 실제 체결된 🌙 건당.
출력: data/closing_bet_review/extra.txt
"""
import os
import pickle
from datetime import date

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.research.closing_bet_review import sim_real as SR

OUT = os.path.join(E.DATA, "closing_bet_review")
P = pickle.load(open(os.path.join(OUT, "plays.pkl"), "rb"))
L = pickle.load(open(os.path.join(OUT, "long_daily.pkl"), "rb"))
rep = open(os.path.join(OUT, "extra.txt"), "w", encoding="utf-8")
B0 = date(2026, 7, 1)


def say(s=""):
    print(s); rep.write(str(s) + "\n"); rep.flush()


def m(v):
    return f"{len(v):4d}건 건당 {np.mean(v):+.2%}" if v else "   0건"


say("## 1. 가격대별 (1분봉 1년 / 7월부터) — 10만 계좌는 1주 ≤ 약 10만 원만 살 수 있다")
for nm, key, px in (("🌙", "r_moon", "moon_px"), ("4️⃣", "r19", "p1519"), ("🧭", "r_1431", "b1431"), ("기본", "r_close", "close")):
    rows = P["moon" if nm == "🌙" else "contra" if nm == "4️⃣" else "compass" if nm == "🧭" else "basic"]
    for lo, hi in ((0, 30_000), (30_000, 100_000), (100_000, 300_000), (300_000, 1e9)):
        sub = [r for r in rows if r.get(key) is not None and lo <= r[px] < hi]
        say(f"  {nm} {lo / 1e4:>4.0f}~{hi / 1e4 if hi < 1e9 else 999:>4.0f}만 원: 1년 {m([r[key] for r in sub])} | 7월부터 {m([r[key] for r in sub if r['date'] >= B0])}")

say("\n## 2. 처음 보는 기간 2024-10~2025-10 (일봉) · 대금 10위 · 상승 — 시총·가격 (시총 = 지금 상장주식수 × 그날 수정 종가, 근사)")
for r in L:
    r["mc"] = (E.SHARES.get(r["code"]) or 0) * E.daily_day(r["date"])[r["code"]][3]
base = [r for r in L if r["rk"] <= 10 and 0 < r["chg"] < E.LIMIT]
for pn, pf in (("A 처음 보는 기간", lambda d: d < E.P0), ("B 본 기간", lambda d: d >= E.P0)):
    for lo, hi, nm in ((0, 3e12, "시총 3조 미만"), (3e12, 2e13, "3조~20조"), (2e13, 1e20, "20조↑")):
        say(f"  {pn} {nm:10s} {m([r['ret'] for r in base if pf(r['date']) and lo <= r['mc'] < hi])}")

say("\n## 3. 시드 크기별 (실전 규칙: 종목당 3만, 1주 > 3만 이면 1주) — 종가 계열만 / 실전 전체")
for seed in (100_000, 300_000, 1_000_000):
    for lab, T in (("🌙 + 4️⃣ (지금)", SR.MOON() + SR.CONTRA), ("🌙 시총 20조↑ + 4️⃣", SR.MOON(SR.BIG) + SR.CONTRA),
                   ("4️⃣ 만", SR.CONTRA), ("🌙 + 4️⃣ + 🧭", SR.MOON() + SR.CONTRA + SR.COMPASS)):
        a = SR.C.real_sim(T, seed=seed, kinds=SR.KINDS); b = SR.C.real_sim(SR.OTHER + T, seed=seed, kinds=SR.KINDS)
        say(f"  시드 {seed / 1e4:>4.0f}만 {lab:22s} 종가만 {a['final'] / seed - 1:+6.1%} (낙폭 {a['mdd']:.0%}, 🌙 {a['n'].get('🌙', 0)}건 {a['pnl'].get('🌙', 0):+,.0f}원, 4️⃣ {a['pnl'].get('4️⃣', 0):+,.0f}원)"
            f" | 실전 전체 {b['final'] / seed - 1:+7.1%} (낙폭 {b['mdd']:.0%})")
    o = SR.C.real_sim(SR.OTHER, seed=seed, kinds=SR.KINDS)
    say(f"  시드 {seed / 1e4:>4.0f}만 {'종가 계열 없음':22s} 실전 전체 {o['final'] / seed - 1:+7.1%} (낙폭 {o['mdd']:.0%})")
