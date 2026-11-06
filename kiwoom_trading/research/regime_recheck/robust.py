"""장중 재판정 → 4️⃣ — 계좌 시뮬 흔들림 점검 (2026-11-06).

10만 실전 계좌는 몇 건만 바뀌어도 나중에 1주 값이 큰 종목(1주 > 3만 → 1주)을 살 수 있느냐가 달라져 최종 자산이 크게 출렁인다
(09:20 판정 4일만 더해도 312만 → 209만). 그래서
  ① 시드 7만·10만·15만·20만·30만 으로 같은 비교를 되풀이 (기준 = 운영과 같은 09:10·09:20 날, 비교 = 그 + 재판정 새 날)
  ② 새 날 4️⃣ 만 따로 실전 수량 규칙(지정가 = +1% 호가 올림, 3만 원 안 최대·넘으면 1주)으로 샀을 때의 손익 합 (현금 제약 없음)
출력: data/regime_recheck/robust.txt
"""
import os
import pickle
import sys
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest.playbook.regime import cls
from kiwoom_trading.research.account_alloc import sim as S
from kiwoom_trading.research.strict_select import choose as C

OUT = os.path.join(S.DATA, "regime_recheck")
REAL = {"6️⃣", "2️⃣", "5️⃣", "📕", "1️⃣", "🌙", "4️⃣"}
RECHECK = [time(14, 0), time(14, 30), time(15, 0), time(15, 15)]
rep = open(os.path.join(OUT, "robust.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(str(s) + "\n"); rep.flush()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    D = pickle.load(open(os.path.join(OUT, "days.pkl"), "rb")); by = {x["date"]: x for x in D}; days = sorted(by)
    base = {d for d in days if by[d]["reg"][time(9, 10)]["down"] or by[d]["reg"][time(9, 20)]["down"]}
    feat_d = {d for d in days if cls(d) == "D"}; on = base | feat_d
    newd = {t: sorted({d for d in days if by[d]["reg"][t]["down"]} - on) for t in RECHECK}
    T0 = pickle.load(open(os.path.join(S.DATA, "strict_select", "trades_feat.pkl"), "rb"))
    BASE_T = [t for t in C.apply(T0, C.ALT) if t["kind"] != "7️⃣"]
    DAYS1 = list(S.DAYS); SPLIT0 = S.SPLIT; last = DAYS1[-1]; d3 = DAYS1[-63]

    def add(ds):
        return [dict(date=d, t=time(15, 20), kind="4️⃣", code=p["code"], px=p["px"], ret=p["ret"], rk=p["rk"], xt=None)
                for d in ds if d <= last for p in by[d]["picks"] if p["ret"] is not None]

    def acct(T, seed, d_from=None):
        if d_from:
            dd = [d for d in DAYS1 if d >= d_from]; S.DAYS = dd; S.SPLIT = dd[len(dd) // 2]
            T = [t for t in T if t["date"] >= d_from]
        r = C.real_sim(T, kinds=REAL, seed=seed)
        S.DAYS = DAYS1; S.SPLIT = SPLIT0
        return r["final"]

    only920 = sorted(base - feat_d)
    say("## ① 시드별 10만 실전 계좌 (1년 / 최근 63거래일) — 기준 A = 계좌 시뮬 입력 그대로(09:10 D), 기준 B = A + 09:20 판정 날(운영과 같게)")
    say("   시드     | 기준 A      기준 B      | B+14:00     B+14:30     B+15:00     B+15:15")
    for seed in (70_000, 100_000, 150_000, 200_000, 300_000):
        for lab, dfrom in (("1년", None), ("3달", d3)):
            a = acct(BASE_T, seed, dfrom); b = acct(BASE_T + add(only920), seed, dfrom)
            xs = [acct(BASE_T + add(only920) + add(newd[t]), seed, dfrom) for t in RECHECK]
            say(f"   {seed // 10000:2d}만 {lab} | {a:>10,.0f} {b:>10,.0f} | " + " ".join(f"{x:>10,.0f}" for x in xs)
                + f" | B 대비 {' '.join(f'{x / b - 1:+.0%}' for x in xs)}")

    say("\n## ② 새 날 4️⃣ 만 실전 수량 규칙으로 (3만 원 안 최대·넘으면 1주, 현금 제약 없음) 손익 합")
    for t in RECHECK:
        tr = add(newd[t])
        pn = []
        for x in tr:
            lim = S.tick_up(x["px"] * 1.01); q = max(1, int(30_000 // lim)); pn.append((x["date"], q * x["px"] * x["ret"], q * lim))
        cheap = [p for p, x in zip(pn, tr) if x["px"] <= 30_000]
        say(f"   {t:%H:%M} {len(tr)}건 손익 합 {sum(p[1] for p in pn):+,.0f}원 (최고 3건 빼면 {sum(sorted(p[1] for p in pn)[:-3]):+,.0f}원) "
            f"| 1주 ≤ 3만 원 종목만 {len(cheap)}건 {sum(p[1] for p in cheap):+,.0f}원 | 8월~ {sum(p[1] for p in pn if p[0] >= date(2026, 8, 1)):+,.0f}원")
    tr = [dict(px=t["px"], ret=t["ret"], date=t["date"]) for t in BASE_T if t["kind"] == "4️⃣"] + add(only920)
    pn = [(x["date"], max(1, int(30_000 // S.tick_up(x["px"] * 1.01))) * x["px"] * x["ret"]) for x in tr]
    say(f"   (비교) 기존 날 4️⃣ {len(tr)}건 손익 합 {sum(p for _, p in pn):+,.0f}원 | 8월~ {sum(p for d, p in pn if d >= date(2026, 8, 1)):+,.0f}원")


if __name__ == "__main__":
    main()
