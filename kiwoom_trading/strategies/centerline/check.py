"""중심선 후보 (A 기준봉 대금 20위 안 × B 대금 가속 10배↑, 몸통 중심선·대기 10일·−3% 손절·익절 없음·보유 5일) 점검 3가지
(2026-10-30 사용자 '그 순서대로'):
  1. 6️⃣ 주도주 신고가·7️⃣ 주도주 추세와 겹침 (같은 종목을 중심선 보유 기간에 산 적 있나)
  2. 시장 상황별 — 매수 날 U/N+/N-/D (그날 09:10 판정, 설명용) · 매수 전날 코스피·코스닥 20일선 (매수 전에 앎)
  3. 계좌 전체 1년 시험 — research/account_alloc/sim 에 '📍 중심선' 을 7️⃣ 처럼 팔 때까지 돈이 묶이는 매매로 넣음
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.centerline.check → data/centerline/check.txt
"""
import os
import sys
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.regime import cls, feat
from kiwoom_trading.common.market import ma20_tag
from kiwoom_trading.strategies.centerline.backtest import OUT, bases, simulate
from kiwoom_trading.strategies.centerline.backtest_filters import accel

EX = ("몸통", 10, 0.03, None, 5)
KC = "📍"


def trades(rank=20, acc=10):
    out = []
    for b in bases(0.10):
        d0, c = b[0], b[1]
        if E.value_rank(d0).get(c, 9999) > rank or accel(c, d0) < acc: continue
        x = simulate(b, *EX)
        if not x: continue
        buy_d, ret, why = x
        sell_d = exit_day(b, buy_d)
        out.append(dict(date=buy_d, base_d=d0, code=c, ret=float(ret), why=why, sell_d=sell_d))
    return out


def exit_day(b, buy_d):
    """simulate 와 같은 규칙으로 '돈이 돌아오는 날'(마지막 매도 다음 거래일 또는 다음 날 09:00 매도 날)."""
    d0, c, o, h, l, cl = b
    mk, wait, stop, tp, hold = EX
    C = (o + cl) / 2
    sp = C * (1 - stop)
    j = bi = E.CIDX[buy_d]
    while j < len(E.CAL):
        r = E.daily_day(E.CAL[j]).get(c)
        ro, rh, rl, rc = r[:4]
        if (j > bi and ro <= sp) or rl <= sp or rc < C or j - bi + 1 >= hold:
            return E.CAL[j + 1] if j + 1 < len(E.CAL) else E.CAL[j]
        j += 1
    return E.CAL[-1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    f = open(os.path.join(OUT, "check.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); f.write(s + "\n"); f.flush()

    T2 = trades()
    T = [t for t in T2 if E.P0 <= t["date"] <= E.P1]
    v = np.array([t["ret"] for t in T2])
    say(f"후보: 기준봉 대금 20위 안 × 대금 가속 10배↑, 몸통 중심선·대기 10일·−3%·익절 없음·보유 5일")
    say(f"  2년 {len(T2)}건 건당 {v.mean():+.2%} / 매매표 1년 기간({E.P0}~{E.P1}) {len(T)}건 건당 {np.mean([t['ret'] for t in T]):+.2%}")

    # ---------------------------------------------------------------- 1. 겹침
    import pickle
    from kiwoom_trading.research.account_alloc import sim as S
    A = S.T_ALL
    say("\n[1] 6️⃣·7️⃣ 와 겹침 (1년 기간, 중심선 매수 날 ~ 매도 날 사이에 같은 종목을 그 매매가 산 적)")
    for k in ("6️⃣", "7️⃣", "📕", "🌙", "1️⃣", "3️⃣"):
        idx = defaultdict(list)
        for t in A:
            if t["kind"] == k: idx[t["code"]].append(t)
        hit, same = [], 0
        for t in T:
            o = [x for x in idx[t["code"]] if t["base_d"] <= x["date"] < t["sell_d"] or
                 (k == "7️⃣" and x["date"] <= t["date"] < x["sell_d"])]
            if o: hit.append(t)
            if any(x["date"] == t["date"] for x in o): same += 1
        hv = [t["ret"] for t in hit]; nv = [t["ret"] for t in T if t not in hit]
        say(f"  {k}: 겹침 {len(hit)}/{len(T)}건 ({len(hit) / len(T):.0%}, 같은 날 {same}) — 겹친 것 건당 {np.mean(hv) if hv else 0:+.2%}, 안 겹친 것 {np.mean(nv) if nv else 0:+.2%}")
    # 기준봉 날 6️⃣ 신호 여부 (기준봉이 곧 6️⃣ 인 경우)
    s6 = {(t["date"], t["code"]) for t in A if t["kind"] == "6️⃣"}
    b6 = [t for t in T if (t["base_d"], t["code"]) in s6]
    say(f"  기준봉 날 6️⃣ 를 산 종목: {len(b6)}/{len(T)}건, 건당 {np.mean([t['ret'] for t in b6]) if b6 else 0:+.2%}")

    # ---------------------------------------------------------------- 2. 시장 상황
    say("\n[2] 시장 상황별")
    g = defaultdict(list)
    for t in T: g[cls(t["date"]) or "?"].append(t["ret"])
    say("  매수 날 상황 (09:10 판정이라 매수 전엔 모름 — 설명용):")
    for k in ("U", "N+", "N-", "D", "?"):
        if g[k]: say(f"    {k:3s} {len(g[k]):4d}건 건당 {np.mean(g[k]):+.2%} 합계 {sum(g[k]) * 100:+.0f}만 승률 {np.mean(np.array(g[k]) > 0):.0%}")
    ma = ma20_tag(E.IX)
    g = defaultdict(list)
    for t in T2: g[ma.get(t["date"], "?")].append((t["date"], t["ret"]))
    say("  매수 날 전날 마감 기준 코스피·코스닥 20일선 (2년, 매수 전에 앎):")
    for k, tr in g.items():
        x = np.array([r for _, r in tr]); ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
        say(f"    {k:14s} {len(x):4d}건 건당 {x.mean():+.2%} 합계 {x.sum() * 100:+.0f}만 | 앞 {np.mean([r for d, r in tr if d < h]):+.2%} 뒤 {np.mean([r for d, r in tr if d >= h]):+.2%}")
    g = defaultdict(list)
    for t in T:
        x = feat.get(E.prev_day(t["date"])) or {}
        g["52주 고점 −10% 안" if x.get("dd52", -1) > -0.10 else "52주 고점 −10% 밖(약세장)"].append(t["ret"])
    say("  전날 코스피 52주 고점 대비 (1년):")
    for k, x in g.items():
        say(f"    {k:22s} {len(x):4d}건 건당 {np.mean(x):+.2%} 합계 {sum(x) * 100:+.0f}만")

    # ---------------------------------------------------------------- 3. 계좌
    say("\n[3] 계좌 전체 1년 (sim 지금 배분 + 고른 배분 B6 = 🔁·3️⃣ 뺀 것, 시드 1천만)")
    add = [dict(date=t["date"], t=time(9, 0), kind=KC, code=t["code"], px=float("nan"), ret=t["ret"], sell_d=t["sell_d"], rk=0) for t in T]
    S.KINDS.append(KC); S.FULLNAME[KC] = "📍 중심선"
    base_kinds = set(S.KINDS) - {KC}
    cfgs = {"지금 배분": {"kinds": base_kinds}, "B6 (🔁·3️⃣ 뺌)": {"kinds": base_kinds - {"🔁", "3️⃣"}}}
    for lab, cfg in cfgs.items():
        r0 = S.run(cfg)
        say(f"  {lab:16s} 중심선 없음      최종 {r0['final'] / 1e4:9,.0f}만 낙폭 {r0['mdd']:.1%} 앞 {r0['front']:+.0%} 뒤 {r0['back']:+.0%}")
        for pool in (0.10, 0.20, 0.30):
            for amt in (0.05, 0.10):
                r = S.run({**cfg, "kinds": cfg["kinds"] | {KC}, "cpool": pool, "c_amt": amt}, trades=S.T_ALL + add)
                say(f"  {lab:16s} 📍 몫 {pool:.0%}·종목당 {amt:.0%} 최종 {r['final'] / 1e4:9,.0f}만 ({r['final'] / r0['final'] - 1:+.0%}) 낙폭 {r['mdd']:.1%} "
                    f"앞 {r['front']:+.0%} 뒤 {r['back']:+.0%} {'★' if r['star'] else ' '} | 📍 {r['n_k'].get(KC, 0)}건 {r['pnl_k'].get(KC, 0) / 1e4:+,.0f}만 · 못 삼 {r['skip'].get('📍 몫 다 씀', (0,))[0]}")


if __name__ == "__main__":
    main()
