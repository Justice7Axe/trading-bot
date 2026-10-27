"""PART 2 (자료 만들기) — 1년 (2025-10-16 ~ 2026-10-22), 종목군 = 전날 대금 상위 200 (주식·우선주 제외, 장 전에 아는 목록).

각 날·종목·시각 T ∈ {08:59, 09:03, 09:05, 09:10} 의 특징 + 그 시각 다음 봉 시가에 샀을 때의 매도 결과를 계산해
data/leader_early/features.pkl 로 저장한다. (분석·매매 집계는 part2_analyze.py)

1분봉 봉 시각 = 그 분의 시작 (09:05 봉 = 09:05:00~59) → T 시각 판단은 T 봉까지, 매수는 그다음 봉 시가.
가격 기준: 전일 종가(일봉 수정주가) × f(그날 1분봉/일봉 비율) — engine 규칙.
매도 (a) 손절 −3% (장중 닿으면 즉시), 아니면 다음 날 09:00 시가.
     (c) 손절 = 09:00~T 저가, R = 매수가 − 손절. +2R 닿으면 절반 매도, 나머지는 고가 대비 −3% 추적(본전 아래로는 안 내림),
         장 끝까지 안 걸리면 다음 날 09:00 시가. 같은 봉에서 손절·익절 둘 다면 손절 먼저. 비용 0.25%.
"""
import os, pickle, sys, time as tm
from datetime import time
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import E, labels, common_rank, OUT

TS = [time(8, 59), time(9, 3), time(9, 5), time(9, 10)]
T_END = time(15, 30)
FLOW_LAST = E.date(2026, 10, 13)


def next_open(c, d, buy):
    """다음 날 09:00 시가 수익률 (비용 포함). 1분봉 우선, 없으면 일봉 시가 × f(d) (9-14 이후 바로잡지 못한 일봉은 제외)."""
    ex = E.next_day_exits(c, d, buy)
    if "09:00 시가" in ex: return ex["09:00 시가"]
    n = E.next_day(d)
    if not n: return None
    dn = E.daily_day(n).get(c); f = E.factor(c, d)
    if not dn or not f or (n >= E.NXT_SWITCH and (c, n) in E.UNSURE): return None
    r = dn[0] * f / buy - 1 - E.COST
    return r if abs(r) < 0.35 else None


def exits(reg, j, low_T, c, d):
    """reg = 정규장 봉 배열 (t,o,h,l,c,v) numpy object 대신 열별 배열 dict. j = 매수 봉 index."""
    o, h, l = reg["o"], reg["h"], reg["l"]
    buy = o[j]
    if not buy or buy <= 0: return None
    nx = None
    # (a) −3%
    sp = buy * 0.97
    hit = np.nonzero(l[j:] <= sp)[0]
    if len(hit):
        k = j + hit[0]; ra = min(o[k], sp) / buy - 1 - E.COST
    else:
        nx = next_open(c, d, buy); ra = nx
    # (c) 09:00~T 저가 손절, +2R 절반, 나머지 3% 추적
    stop = min(low_T, buy * 0.995); R = buy - stop; tgt = buy + 2 * R
    rc = None; half = None
    for k in range(j, len(o)):
        if half is None:
            if l[k] <= stop: rc = min(o[k], stop) / buy - 1 - E.COST; break
            if h[k] >= tgt:
                half = max(o[k], tgt) / buy - 1; run = h[k]; continue
        else:
            trail = max(buy, run * 0.97)
            if l[k] <= trail:
                rc = 0.5 * half + 0.5 * (min(o[k], trail) / buy - 1) - E.COST; break
            run = max(run, h[k])
    if rc is None:
        if nx is None: nx = next_open(c, d, buy)
        if nx is not None:
            rc = nx if half is None else 0.5 * half + 0.5 * (nx + E.COST) - E.COST
    return buy, ra, rc, R / buy


def main():
    rows = []; miss = []
    t0 = tm.time()
    for di, d in enumerate(E.days()):
        p = E.prev_day(d); pp = E.prev_day(p)
        cr = common_rank(p)
        univ = [c for c, r in cr.items() if r <= 200]
        lb = labels(d)
        l1 = {c for c, v in lb.items() if v[0]}
        miss.append((d, len(l1), len(l1 - set(univ)), [E.NAME[c] for c in l1 - set(univ)]))
        dp, dpp = E.daily_day(p), E.daily_day(pp)
        B = E.load_day(univ, d)
        n = E.next_day(d)
        if n: E.load_day(univ, n)
        for c in univ:
            b = B[c]; f = E.factor(c, d)
            if not f or c not in dp: continue
            pv = dp[c][5] or 0
            if pv <= 0: continue
            pc = dp[c][3] * f
            prev_chg = dp[c][3] / dpp[c][3] - 1 if c in dpp and dpp[c][3] else np.nan
            hi = E.hi_n(c, d, 250)
            hi = hi * f if hi else None
            fl = E.inv(c, p) if p <= FLOW_LAST else None
            pre = [x for x in b if x[0] < time(9, 0)]
            reg = [x for x in b if time(9, 0) <= x[0] <= T_END]
            if len(reg) < 30: continue
            pre_val = sum(x[4] * x[5] for x in pre)
            permin = pv / 390
            pre_burst = max((x[4] * x[5] for x in pre), default=0) / permin
            R = {k: np.array([x[i] for x in reg], float) for i, k in enumerate("tohlcv") if k != "t"}
            R["t"] = [x[0] for x in reg]
            R["val"] = R["c"] * R["v"]
            mc = (E.SHARES.get(c) or 0) * dp[c][3]
            base = dict(d=d, c=c, prev_rank=cr[c], prev_val=pv, prev_chg=prev_chg, mcap=mc,
                        pre_val=pre_val, pre_ratio=pre_val / pv, pre_burst=pre_burst,
                        pre_gap=(pre[-1][4] / pc - 1) if pre else np.nan,
                        pre_hi=(max(x[2] for x in pre) / pc - 1) if pre else np.nan,
                        flow_fi=((fl[0] + fl[1]) / pv) if fl else np.nan,
                        flow_f=(fl[0] / pv) if fl else np.nan, flow_i=(fl[1] / pv) if fl else np.nan,
                        L1=lb.get(c, (False,))[0], L2=lb.get(c, (False, False))[1],
                        fin_chg=lb.get(c, (0, 0, np.nan))[2])
            for T in TS:
                m = sum(1 for t in R["t"] if t <= T)          # 09:00~T 봉 수
                if m >= len(R["t"]): continue
                j = m
                if T < time(9, 0):
                    px = pre[-1][4] if pre else np.nan
                    feat = dict(chg_T=px / pc - 1 if pre else np.nan, from_open=np.nan, open_gap=np.nan,
                                cum_val=0.0, cum_ratio=0.0, burst=pre_burst, low_T=np.nan)
                    low_T = R["o"][0] * 0.97   # 08:59 매수는 09:00 시가 −3% 를 (c) 손절로
                else:
                    if m == 0: continue
                    px = R["c"][m - 1]; cv = R["val"][:m].sum()
                    low_T = R["l"][:m].min()
                    feat = dict(chg_T=px / pc - 1, from_open=px / R["o"][0] - 1, open_gap=R["o"][0] / pc - 1,
                                cum_val=cv, cum_ratio=cv / pv, burst=max(pre_burst, R["val"][:m].max() / permin),
                                reg_burst=R["val"][:m].max() / permin, low_T=low_T,
                                nhigh=int(np.sum(R["h"][1:m] > np.maximum.accumulate(R["h"][:m])[:-1])) if m > 1 else 0)
                feat["hi52"] = px / hi - 1 if hi else np.nan
                ex = exits(R, j, low_T, c, d)
                if ex is None: continue
                buy, ra, rc, rpct = ex
                # 그날 남은 최대 상승 (참고)
                rows.append({**base, **feat, "T": T, "buy": buy, "ret_a": ra, "ret_c": rc, "r_pct": rpct,
                             "max_up": R["h"][j:].max() / buy - 1})
        E._bars_cache.clear()
        if di % 20 == 0:
            print(f"{d} {di + 1}/{len(E.days())} rows {len(rows)} {tm.time() - t0:.0f}s", flush=True)
    with open(os.path.join(OUT, "features.pkl"), "wb") as fh:
        pickle.dump(dict(rows=rows, miss=miss), fh)
    print("저장", len(rows), f"{tm.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
