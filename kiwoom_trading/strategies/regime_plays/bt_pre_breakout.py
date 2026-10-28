"""장 초 급등 고점 R '돌파 직전 선매수' 1년 시험 (2026-10-28 사용자: "돌파 직전에 미리 사는 조건 시험해줘").

직전 시험 bt_open_high_rebreak.py 의 자료·유니버스·R 정의를 그대로 쓰고, 그 기준(확인 후 매수) 결과를 먼저 재현한다.
공통 전제 (봉 k 끝에 아는 값만): R = R10(09:00~09:10 최고가) ≥ 시가 × (1+a), R 확정 뒤 T분 지남 + 직전 T봉 R 위 마감 없음,
  k 종가 ≤ R, 09:40~14:30, 그 봉 끝 누적 대금 순위 ≤ N (1분봉 있는 종목 안에서), 종목당 하루 1번. → k+1 봉 시가 매수.
  매수가가 전날 종가 +29% 이상이면 못 삼.
선매수 조건:
  E1 근접+거래량: 종가가 R −x 안 (x 1.5%/1%) + 최근 5봉 거래량 합 ≥ 그 앞 30봉의 5봉 평균 × kv (1.5/2)
  E2 저점 상승 수렴: 최근 3개 W분(15/10) 구간 저점이 계속 높아짐 + 그 45(30)분 고가 < R + 종가 R −2% 안
  E3 이평 수렴 정배열: 5>20>60분선 + |5분선−20분선| ≤ 종가 0.3% + 종가 R −2% 안
  E4 E1+E2 / E1+E3 동시
  E5 첫 터치 실패 뒤 재접근: R 확정 뒤 고가가 R −1% 안에 닿음 → (다음 봉부터) 저가 R −1.5% 이하로 밀림 → 종가 R −1% 안 재접근
손절: S1 = 직전 15봉 최저 × 0.997 아래 마감 (매수 때 고정) / S2 = 20분선 아래 마감 → 다음 봉 시가. 둘 다 −3% 터치 안전장치.
매도: (a) +2% 터치 절반 → 나머지 5분선 아래 마감(다음 봉 시가) / 15:19 종가
      (b) 5분선 아래 마감 전부
      (c) (a) + R 돌파 실패 정리: 매수 뒤 30분 안에, 아직 R 위 마감이 없고 종가 < 매수가면 다음 봉 시가 정리
      (d) 손절만, 아니면 다음 날 09:00 시가
      15:19 당일 정리는 단타 성격상 허용(명시). 같은 봉 손절·익절이면 손절 먼저. 비용 0.25%.
'R 돌파' = 매수 뒤 15:19 까지 종가가 R 위로 마감한 적 있음 (매도 여부와 무관).
한계: minute_history 는 전날 대금 상위 500 위주 + 그날 대금 200 안 종목 → 범위 밖 종목이 빠지고, 순위는 그 안에서만 매김.
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.strategies.regime_plays.bt_pre_breakout → data/backtest/pre_breakout.txt
"""
import os, sys, pickle
from collections import defaultdict
from datetime import date, time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load
from kiwoom_trading.strategies.regime_plays import bt_open_high_rebreak as OH
from kiwoom_trading.strategies.regime_plays.bt_open_high_rebreak import Day, UNTIL, T0, T1, tmin

OUT = os.path.join(E.DATA, "backtest"); os.makedirs(OUT, exist_ok=True)
F = None


def say(s=""):
    print(s, flush=True)
    if F: F.write(s + "\n"); F.flush()


def roll(x, n, fn):
    """x[k-n+1..k] 에 fn (모자라면 nan)."""
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        w = np.lib.stride_tricks.sliding_window_view(x, n)
        out[n - 1:] = fn(w, axis=1)
    return out


def masks(D, R, ci):
    """조건별 봉 마스크 (봉 k 끝에 아는 값만)."""
    n = len(D.c); c, h, l, v = D.c, D.h, D.l, D.v
    M = {}
    M["le"] = c <= R
    for x in (0.01, 0.015, 0.02):
        M[f"near{x}"] = M["le"] & (c >= R * (1 - x))
    s5 = roll(v, 5, np.sum); s35 = roll(v, 35, np.sum)
    pr = (s35 - s5) / 6
    with np.errstate(invalid="ignore", divide="ignore"):
        vr = np.where(pr > 0, s5 / pr, np.nan)
    M["vr"] = vr
    for W in (15, 10):
        L1 = roll(l, W, np.min)
        L2 = np.r_[np.full(W, np.nan), L1[:-W]] if n > W else np.full(n, np.nan)
        L3 = np.r_[np.full(2 * W, np.nan), L1[:-2 * W]] if n > 2 * W else np.full(n, np.nan)
        H = roll(h, 3 * W, np.max)
        with np.errstate(invalid="ignore"):
            M[f"E2_{W}"] = (L3 < L2) & (L2 < L1) & (H < R) & M["near0.02"]
    with np.errstate(invalid="ignore"):
        M["E3"] = (D.m5 > D.m20) & (D.m20 > D.m60) & (np.abs(D.m5 - D.m20) <= c * 0.003) & M["near0.02"]
    e5 = np.zeros(n, bool); st = 0
    for i in range(ci + 1, n):
        if st == 2 and M["near0.01"][i]: e5[i] = True
        if st == 0 and h[i] >= R * 0.99: st = 1
        elif st == 1 and l[i] <= R * 0.985: st = 2
    M["E5"] = e5
    # 전제: T 봉 R 위 마감 없음 (k 포함)
    above = np.r_[0, np.cumsum(c > R)]
    for T in (30, 60):
        ok = np.zeros(n, bool)
        for k in range(n):
            if k - ci >= T and k >= T: ok[k] = above[k + 1] - above[k + 1 - T] == 0
        M[f"T{T}"] = ok
    tt = np.array([T0 <= t <= T1 for t in D.t]); nx = np.array([i + 1 < n and D.t[i + 1] <= UNTIL for i in range(n)])
    M["time"] = tt & nx & (np.arange(n) >= 34)
    return M


def cond(M, P):
    e = P["E"]
    def e1(x, kv):
        with np.errstate(invalid="ignore"):
            return M[f"near{x}"] & (M["vr"] >= kv)
    if e == "E1": return e1(P["x"], P["kv"])
    if e == "E2": return M[f"E2_{P['W']}"]
    if e == "E3": return M["E3"]
    if e == "E1E2": return e1(P["x"], P["kv"]) & M["E2_15"]
    if e == "E1E3": return e1(P["x"], P["kv"]) & M["E3"]
    if e == "E5": return M["E5"]
    raise ValueError(e)


def run_pre(D, k, R, stop, how, nx_px):
    """D.b[k+1] 시가 매수 → (수익률, 보유분|None, R%, 매수가, 이유, 매도시각, 돌파여부)."""
    j = k + 1; buy = D.o[j]; safety = buy * 0.97
    slo = D.l[max(0, k - 14):k + 1].min() * 0.997
    lvl0 = slo if stop == "S1" else D.m20[k]
    rpct = min(max(1 - lvl0 / buy, 0.003), 0.03)
    i19 = max(i for i, t in enumerate(D.t) if t <= UNTIL)
    broke = bool((D.c[j:i19 + 1] > R).any())
    pos, got, half, pend, brk = 1.0, 0.0, False, None, False
    held = lambda t: tmin(t) - tmin(D.t[j])
    for i in range(j, len(D.b)):
        t = D.t[i]
        if t > UNTIL: break
        o, h, l, c = D.o[i], D.h[i], D.l[i], D.c[i]
        if pend:
            return got + pos * (o / buy - 1) - E.COST, held(t), rpct, buy, pend, t, broke
        if l <= safety:
            return got + pos * (min(o, safety) / buy - 1) - E.COST, held(t), rpct, buy, "−3%", t, broke
        lvl = slo if stop == "S1" else D.m20[i]
        if c < lvl:
            pend = "손절"; continue
        if c > R: brk = True
        if how in ("a", "c"):
            if not half and h >= buy * 1.02:
                got += 0.5 * (max(o, buy * 1.02) / buy - 1); pos = 0.5; half = True
            if half and c < D.m5[i]:
                pend = "5분선"; continue
            if how == "c" and not half and not brk and i - j < 30 and c < buy:
                pend = "R 실패"; continue
        elif how == "b":
            if c < D.m5[i]:
                pend = "5분선"; continue
    if pend:
        nxt = next((i for i in range(j, len(D.b)) if D.t[i] > UNTIL), None)
        if nxt is not None:
            return got + pos * (D.o[nxt] / buy - 1) - E.COST, held(D.t[nxt]), rpct, buy, pend, D.t[nxt], broke
    if how == "d":
        return got + pos * (nx_px / buy - 1) - E.COST, None, rpct, buy, "다음 날", None, broke
    return got + pos * (D.c[i19] / buy - 1) - E.COST, held(UNTIL), rpct, buy, "15:19", UNTIL, broke


BASE = dict(E="E1", x=0.015, kv=1.5, W=15, a=0.03, T=30, N=100, st="S1", ex="a")
COMBOS = [(nm, {**BASE, **ch}) for nm, ch in [
    ("E1 기본 −1.5% ×1.5 a3 T30 S1 (a) 100", {}),
    ("E1 −1% ×1.5", dict(x=0.01)), ("E1 −1.5% ×2", dict(kv=2)), ("E1 −1% ×2", dict(x=0.01, kv=2)),
    ("E1 a5", dict(a=0.05)), ("E1 T60", dict(T=60)), ("E1 a5 T60", dict(a=0.05, T=60)),
    ("E1 손절 S2(20분선)", dict(st="S2")), ("E1 매도 (b)", dict(ex="b")), ("E1 매도 (c)", dict(ex="c")),
    ("E1 매도 (d)", dict(ex="d")), ("E1 상위40", dict(N=40)), ("E1 S2 (d)", dict(st="S2", ex="d")),
    ("E2 15분", dict(E="E2")), ("E2 10분", dict(E="E2", W=10)), ("E2 (c)", dict(E="E2", ex="c")),
    ("E2 (d)", dict(E="E2", ex="d")), ("E2 상위40", dict(E="E2", N=40)), ("E2 10분 a5", dict(E="E2", W=10, a=0.05)),
    ("E3 정배열 수렴", dict(E="E3")), ("E3 (c)", dict(E="E3", ex="c")), ("E3 (d)", dict(E="E3", ex="d")),
    ("E4 E1+E2", dict(E="E1E2")), ("E4 E1+E3", dict(E="E1E3")), ("E4 E1+E2 (d)", dict(E="E1E2", ex="d")),
    ("E5 재접근", dict(E="E5")), ("E5 (c)", dict(E="E5", ex="c")), ("E5 (d)", dict(E="E5", ex="d")),
    ("E5 a5", dict(E="E5", a=0.05)), ("E5 상위40", dict(E="E5", N=40)), ("E5 S2", dict(E="E5", st="S2")),
]]
OHB = OH.COMBOS[0]   # 기준: 확인 후 매수 (R10 a3 T30 ×2 정배열 S1 (a) 상위100)


def first_k(M, P, rkb, ci):
    m = M["time"] & M[f"T{P['T']}"] & (rkb <= P["N"]) & cond(M, P)
    ix = np.flatnonzero(m)
    return int(ix[0]) if len(ix) else None


def stats2(tr):
    s = OH.stats(tr)
    if not s: return None
    v = np.array([x["ret"] for x in tr]); w, lo = v[v > 0], v[v <= 0]
    s["pf"] = (w.mean() / -lo.mean()) if len(w) and len(lo) and lo.mean() < 0 else float("nan")
    s["brk"] = np.mean([x["broke"] for x in tr])
    b1 = [x["ret"] for x in tr if x["broke"]]; b0 = [x["ret"] for x in tr if not x["broke"]]
    s["b1"] = np.mean(b1) if b1 else float("nan"); s["b0"] = np.mean(b0) if b0 else float("nan")
    s["vsR"] = np.mean([x["buy"] / x["R"] - 1 for x in tr])
    return s


def line(name, s):
    if s is None:
        say(f"   {name:30s} 적음"); return
    hold = f"{s['hold']:4.0f}분" if s["hold"] is not None else "다음날"
    say(f" {s['star']} {name:30s} {s['n']:4d} {s['days']:3d}일 {s['mean']:+6.2%} {s['a']:+6.2%} {s['b']:+6.2%} {s['tot']:+6.0f}만 {s['ex5']:+6.0f}만 "
        f"{s['mdd']:4.0f}만 {s['win']:4.0%} {hold} {s['Rm']:+5.2f}R {s['pf']:4.2f} | {s['vsR']:+6.2%} {s['brk']:4.0%} {s['b1']:+6.2%} {s['b0']:+6.2%}")


def build():
    feat = _load("regime_feat.pkl")
    days = [d for d in E.days() if E.next_day(d) and d in feat]
    res = defaultdict(list); base = []; inv = []
    for di, d in enumerate(days):
        p = E.prev_day(d); dd, dp = E.daily_day(d), E.daily_day(p)
        codes = [c for c in E._min_codes(d) if E.is_common(c) and c in dd and c in dp and "스팩" not in (E.NAME.get(c) or "")]
        B = {c: E.regular(b) for c, b in E.load_day(codes, d).items()}
        B = {c: Day(b) for c, b in B.items() if len(b) >= 120 and b[0][0] <= time(9, 1)}
        if not B: continue
        U = cls_of(feat[d]) == "U"
        grid = [time(9 + (m // 60), m % 60) for m in range(0, 391)]
        gi = {t: i for i, t in enumerate(grid)}
        cl = list(B); Mx = np.zeros((len(cl), len(grid)))
        for r, c in enumerate(cl):
            D = B[c]; last = 0.0; pos = 0
            for i, t in enumerate(grid):
                while pos < len(D.t) and D.t[pos] <= t:
                    last = D.cumv[pos]; pos += 1
                Mx[r, i] = last
        RK = (-Mx).argsort(0).argsort(0) + 1
        rk = {c: RK[r] for r, c in enumerate(cl)}
        for c, D in B.items():
            o9 = dd[c][0]; pcl = dp[c][3]
            if not (o9 and pcl): continue
            pc0 = D.o[0] / (o9 / pcl)
            rkb = np.array([rk[c][gi[t]] for t in D.t])
            # 기준 재현 (확인 후 매수)
            nmB, PB = OHB
            fb = OH.signal(D, PB["R"], PB["a"], PB["T"], PB["kv"], PB["al"], lambda k: rk[c][gi[D.t[k]]] <= PB["N"])
            bbuy = None
            if fb and D.o[fb[0] + 1] / pc0 - 1 < 0.29:
                k, R = fb
                ret, hold, rp, buy, why, te = OH.run_exit(D, k, R, PB["st"], PB["ex"], None)
                base.append(dict(d=d, U=U, c=c, ret=ret, hold=hold, rpct=rp, buy=buy, R=R, t=D.t[k]))
                bbuy = (buy, D.t[k + 1])
            r = D.R("R10")
            if not r: continue
            R, ci = r
            if R < D.o[0] * 1.03: continue
            M = masks(D, R, ci)
            nxe = None
            fired = {}
            for nm, P in COMBOS:
                if R < D.o[0] * (1 + P["a"]): continue
                k = first_k(M, P, rkb, ci)
                if k is None: continue
                if D.o[k + 1] / pc0 - 1 >= 0.29: continue
                nx_px = None
                if P["ex"] == "d":
                    if nxe is None:
                        ex = E.next_day_exits(c, d, D.c[-1]).get("09:00 시가")
                        nxe = (ex + E.COST + 1) * D.c[-1] if ex is not None else False
                    if nxe is False: continue
                    nx_px = nxe
                ret, hold, rp, buy, why, te, broke = run_pre(D, k, R, P["st"], P["ex"], nx_px)
                i19 = max(i for i, t in enumerate(D.t) if t <= UNTIL)
                res[nm].append(dict(d=d, U=U, c=c, ret=ret, hold=hold, rpct=rp, buy=buy, R=R, t=D.t[k], why=why, broke=broke,
                                    raw=D.c[i19] / buy - 1, bbuy=bbuy, k=k))
                fired[nm] = k
            # 역선택: 같은 전제(R10 +3%, T30, 09:40~14:30, 상위100, 종가 ≤ R) 처음 충족 봉 k0 기준 그날 결과
            pm = M["time"] & M["T30"] & (rkb <= 100) & M["le"]
            ix = np.flatnonzero(pm)
            if len(ix):
                k0 = int(ix[0]); i19 = max(i for i, t in enumerate(D.t) if t <= UNTIL)
                inv.append(dict(d=d, U=U, c=c, ret=D.c[i19] / D.o[k0 + 1] - 1, mx=D.h[k0 + 1:i19 + 1].max() / D.o[k0 + 1] - 1,
                                above=bool((D.c[k0 + 1:i19 + 1] > R).any()), fired=set(fired)))
        if di % 20 == 0:
            print(f"  {d} {len(B)}종목 기준 {len(base)}건 E1 {len(res[COMBOS[0][0]])}건", file=sys.stderr, flush=True)
    return res, base, inv, days, feat


HDR = (f"   {'조합':30s} {'건수':>4s} {'날':>4s} {'건당':>6s} {'앞':>6s} {'뒤':>6s} {'1천만/일':>7s} {'최고5일빼':>7s} {'낙폭':>5s} {'승률':>4s} "
       f"{'보유':>5s} {'R배':>6s} {'손익비':>4s} | {'R대비매수':>6s} {'돌파율':>4s} {'돌파시':>6s} {'실패시':>6s}")


def main():
    global F
    sys.stdout.reconfigure(encoding="utf-8")
    F = open(os.path.join(OUT, "pre_breakout.txt"), "w", encoding="utf-8")
    res, base, inv, days, feat = build()
    nU = sum(cls_of(feat[d]) == "U" for d in days)
    say(f"R10 급등 고점 돌파 직전 선매수 — {days[0]}~{days[-1]} {len(days)}일 (강한 상승장 U {nU}일), 1분봉 minute_history(+kang_minute) 원가격")
    say(f"시험한 조합 {len(COMBOS)}개 × 날 3가지 × (상위 40/100 일부). 같은 자료에서 고른 것이라 ★ 하나쯤은 우연으로도 나올 수 있음.")
    say("1천만/일 = 그날 산 종목 수로 나눔. R배 = 수익률÷(매수가→첫 손절선 거리, 0.3~3%). 손익비 = 평균 이익÷평균 손실.")
    say("R대비매수 = 매수가÷R−1 (음수 = R 아래에서 삼). 돌파율 = 매수 뒤 15:19 까지 R 위 마감한 비율, 돌파시/실패시 = 각각의 건당 결과.")
    for title, flt in (("모든 날", lambda x: True), ("강한 상승장(U) 날", lambda x: x["U"]), ("강한 상승장 아닌 날", lambda x: not x["U"])):
        say("\n" + "=" * 150); say(f"[{title}]"); say(HDR)
        sb = OH.stats([x for x in base if flt(x)])
        if sb:
            vsR = np.mean([x["buy"] / x["R"] - 1 for x in base if flt(x)])
            say(f"   기준 확인 후 매수 (직전 시험 기본)    {sb['n']:4d} {sb['days']:3d}일 {sb['mean']:+6.2%} {sb['a']:+6.2%} {sb['b']:+6.2%} "
                f"{sb['tot']:+6.0f}만 {sb['ex5']:+6.0f}만 {sb['mdd']:4.0f}만 {sb['win']:4.0%} {sb['hold']:4.0f}분 {sb['Rm']:+5.2f}R      | {vsR:+6.2%}")
        for nm, P in COMBOS:
            line(nm, stats2([x for x in res[nm] if flt(x)]))
    # 기준 대비 진입가
    say("\n" + "=" * 150)
    say("같은 종목·같은 날 기준(확인 후 매수)도 신호가 났을 때: 선매수 매수가가 기준 매수가보다 몇 % 싼지, 몇 분 빠른지")
    for nm, P in COMBOS:
        z = [x for x in res[nm] if x["bbuy"]]
        if len(z) < 5: continue
        dp = np.mean([x["buy"] / x["bbuy"][0] - 1 for x in z]); dt = np.median([tmin(x["bbuy"][1]) - tmin(x["t"]) - 1 for x in z])
        early = np.mean([tmin(x["t"]) + 1 < tmin(x["bbuy"][1]) for x in z])
        say(f"   {nm:30s} 겹침 {len(z):4d}건 ({len(z) / max(len(res[nm]), 1):3.0%}) · 매수가 {dp:+.2%} · 기준보다 먼저 산 비율 {early:.0%} · 시간차 중앙 {dt:+.0f}분")
    nm0 = COMBOS[0][0]
    for nm in (nm0, "E2 15분", "E3 정배열 수렴", "E5 재접근"):
        say(f"   {nm} 매도 이유: " + ", ".join(f"{k} {v}" for k, v in sorted(
            {w: sum(1 for x in res[nm] if x["why"] == w) for w in {x["why"] for x in res[nm]}}.items(), key=lambda q: -q[1])))
    # 역선택
    say("\n" + "=" * 150)
    say("역선택 점검 — 같은 전제(R10 +3%↑, T30 동안 R 위 마감 없음, 09:40~14:30, 상위100, 종가 ≤ R) 처음 충족 봉 다음 시가 → 15:19 종가 (비용 전)")
    for title, flt in (("모든 날", lambda x: True), ("U 날", lambda x: x["U"]), ("U 아닌 날", lambda x: not x["U"])):
        g = [x for x in inv if flt(x)]
        f = lambda z, k: np.mean([q[k] for q in z]) if z else float("nan")
        say(f"  [{title}] 전제 충족 {len(g)}종목·날")
        for nm in (nm0, "E1 −1% ×2", "E2 15분", "E3 정배열 수렴", "E4 E1+E2", "E5 재접근"):
            y = [x for x in g if nm in x["fired"]]; n = [x for x in g if nm not in x["fired"]]
            tr = [x for x in res[nm] if flt(x)]
            say(f"     {nm:30s} 신호 난 {len(y):4d}: 그날 {f(y, 'ret'):+.2%} 최고 {f(y, 'mx'):+.2%} R 돌파 {f(y, 'above'):.0%} | "
                f"안 난 {len(n):5d}: 그날 {f(n, 'ret'):+.2%} 최고 {f(n, 'mx'):+.2%} R 돌파 {f(n, 'above'):.0%} | 신호 매수→15:19 {np.mean([x['raw'] for x in tr]) if tr else float('nan'):+.2%}")
    pickle.dump(dict(res=res, base=base, inv=inv), open(os.path.join(os.environ.get("TEMP", "."), "pre_breakout.pkl"), "wb"))


def today_examples():
    say("\n" + "=" * 150)
    say("오늘(2026-10-28) 예시 — KRX 1분봉 data/leader_capture/bars_krx.pkl (그 안 종목끼리 누적 대금 순위). 다음 날 없음 → (d) 는 15:30 종가로 표시")
    B = pickle.load(open(os.path.join(E.DATA, "leader_capture", "bars_krx.pkl"), "rb"))
    d = date(2026, 10, 28)
    allD = {}
    for (c, dd), raw in B.items():
        if dd != d: continue
        b = [(x[0].time(), *x[1:]) for x in raw if time(9, 0) <= x[0].time() <= time(15, 30)]
        if len(b) >= 60: allD[c] = Day(b)
    grid = [time(9 + (m // 60), m % 60) for m in range(0, 391)]
    cum = {}
    for c, D in allD.items():
        arr, last, pos = [], 0.0, 0
        for t in grid:
            while pos < len(D.t) and D.t[pos] <= t: last = D.cumv[pos]; pos += 1
            arr.append(last)
        cum[c] = np.array(arr)
    allc = np.array(list(cum.values()))
    for c, nm in (("356680", "엑스게이트"), ("010170", "대한광통신"), ("069540", "빛과전자")):
        D = allD.get(c)
        if not D: say(f"  {nm}({c}) 1분봉 없음"); continue
        rkb = np.array([1 + int((allc[:, grid.index(t)] > cum[c][grid.index(t)]).sum()) for t in D.t])
        r = D.R("R10"); R, ci = r
        brk = next((D.t[i].strftime('%H:%M') for i in range(ci + 30, len(D.c)) if D.c[i] > R), "없음")
        say(f"  {nm}({c}) 시가 {D.o[0]:,.0f} · R10 {R:,.0f} ({R / D.o[0] - 1:+.1%}) · 30분 뒤 첫 R 위 마감 {brk} · 15:30 종가 {D.c[-1]:,.0f}")
        fb = OH.signal(D, "R10", 0.03, 30, 2, True, lambda k: rkb[k] <= 100)
        if fb:
            ret, hold, rp, buy, why, te = OH.run_exit(D, fb[0], fb[1], "S1", "a", None)
            say(f"     {'기준 확인 후 매수':30s} {D.t[fb[0]].strftime('%H:%M')} 신호 → {D.t[fb[0] + 1].strftime('%H:%M')} 매수 {buy:,.0f} ({buy / R - 1:+.2%} vs R) → {why}"
                + (f" {te.strftime('%H:%M')}" if te else "") + f" {ret:+.2%}")
        else:
            say(f"     {'기준 확인 후 매수':30s} 신호 없음")
        M = masks(D, R, ci)
        for nm2, P in COMBOS:
            if R < D.o[0] * (1 + P["a"]): say(f"     {nm2:30s} R 급등 조건 미달"); continue
            k = first_k(M, P, rkb, ci)
            if k is None: say(f"     {nm2:30s} 신호 없음"); continue
            ret, hold, rp, buy, why, te, broke = run_pre(D, k, R, P["st"], P["ex"], D.c[-1])
            say(f"     {nm2:30s} {D.t[k].strftime('%H:%M')} 신호(순위 {rkb[k]}) → {D.t[k + 1].strftime('%H:%M')} 매수 {buy:,.0f} ({buy / R - 1:+.2%} vs R) → {why}"
                + (f" {te.strftime('%H:%M')}" if te else "") + f" {ret:+.2%} ({ret / rp:+.1f}R)" + (" · R 돌파함" if broke else " · R 돌파 못 함"))


if __name__ == "__main__":
    if "--today" in sys.argv:
        sys.stdout.reconfigure(encoding="utf-8"); today_examples()
    else:
        main(); today_examples(); F.close()
