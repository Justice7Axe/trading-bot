"""1️⃣ 상승장 장 초 — 지금(대금 40위 안 전부) vs '당일 주도주 점수' 상위 k 몰아 사기 비교 (2026-10-28).

같은 강한 상승장 날(regime_feat cls_of == 'U', 09:10 판정)만 본다.
 (0) 지금 1️⃣: bt_up_exits 와 같은 고르기 (u_cands T=09:10, 누적 대금 40위 안, 시가 위, 전날 외인·기관 둘 다 − 제외).
     09:10 봉 시가 매수(판단은 09:09 봉까지). 참고로 09:11 봉 시가 매수도 같이 본다.
 (1) (0) 의 같은 후보 안에서 점수 상위 k (3·5·10).
 (2) 전날 대금 상위 200 (주식, 우선주 제외 = leader_early features.pkl 종목군) 전체에서 점수 상위 k.
 점수 (09:10 봉까지 아는 값 = features.pkl T=09:10 → 매수는 09:11 봉 시가, 미래 정보 없음):
   RA  = 순위평균: 09:00~09:10 누적 대금, 09:10 전일 대비, 전날 대금, 프리장 고가 갭 — 고르는 집합 안 백분위 평균
   LR  = 로지스틱 (leader_early part2 와 같은 특징·백분위, L1 라벨) — 1년 앞 절반 날(모든 날)로만 학습 → 뒤 절반 U 날만 평가
 +29%↑(상한가 근처)는 못 산다고 보고 뺀다.
매도: old = −4% 손절, 아니면 다음 날 09:00 / a = −3% 손절, 아니면 다음 날 09:00 /
      B = −4% 손절, +7% 절반 익절, 남은 절반 고가 −4% 추적(본전 아래로 안 내림) / c = 09:00~매수 전 저가 손절(최소 −0.5%), +2R 절반, 남은 절반 고가 −3% 추적.
      장중은 15:19 봉까지 보고, 안 걸리면 다음 날 09:00 시가 (engine.next_day_exits). 같은 봉이면 손절 먼저. 비용 0.25%.
계좌: 날마다 1,000만 원을 그날 산 종목 수로 똑같이 나눔 (몰아 사면 한 종목 몫이 커짐) → 날 수익률 = 그날 건 평균. 합계(단리)·복리·낙폭.
실행: python -m kiwoom_trading.strategies.regime_plays.bt_up_score  → data/backtest/up_score.txt
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import time

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.backtest.playbook.build_regime import cls_of
from kiwoom_trading.strategies.regime_plays.build_up import _load

COST = E.COST
CAP = 1000          # 만 원
UNTIL = time(15, 19)
RA_F = ["cum_val", "chg_T", "prev_val", "pre_hi"]
LR_F = ["prev_rank", "prev_val", "prev_chg", "mcap", "pre_val", "pre_ratio", "pre_burst", "pre_gap", "pre_hi",
        "chg_T", "from_open", "open_gap", "cum_val", "cum_ratio", "cum_rank", "burst", "reg_burst", "nhigh", "hi52"]


# ---------------------------------------------------------------- 매도
def sim(bars, j, nx, stop, half_at=None, trail=None):
    """bars[j] 시가 매수. stop = 손절가 (절대값). half_at = 절반 익절가 (절대값, None=없음), trail = 추적 폭.
    nx = 다음 날 09:00 수익률(비용 포함) 또는 None. → 수익률 또는 None."""
    e = bars[j][1]
    hi = e
    half, got = False, 0.0
    for x in bars[j:]:
        if x[0] > UNTIL:
            break
        o, h, l = x[1], x[2], x[3]
        if l <= stop:
            px = min(o, stop)
            return got + (0.5 if half else 1.0) * (px / e - 1) - COST
        if half_at is not None and not half and h >= half_at:
            got += 0.5 * (max(o, half_at) / e - 1)
            half = True
            hi = h
            stop = max(stop, e, hi * (1 - trail)) if trail else max(stop, e)
            continue
        hi = max(hi, h)
        if half and trail:
            stop = max(stop, hi * (1 - trail), e)
    if nx is None:
        return None
    return got + (0.5 if half else 1.0) * (nx + COST) - COST


def all_exits(c, d, t_buy):
    """t_buy 봉 시가 매수 → {old, a, B, c} 수익률 (못 구하면 None)."""
    b = [x for x in E.bars(c, d) if time(9, 0) <= x[0] <= time(15, 30)]
    j = next((i for i, x in enumerate(b) if x[0] >= t_buy), None)
    if j is None or j == 0 or b[j][0] > time(9, 13):
        return None
    e = b[j][1]
    if not e or e <= 0:
        return None
    ex = E.next_day_exits(c, d, e)
    nx = ex.get("09:00 시가")
    lowT = min(x[3] for x in b[:j])
    cs = min(lowT, e * 0.995)
    out = dict(old=sim(b, j, nx, e * 0.96), a=sim(b, j, nx, e * 0.97),
               B=sim(b, j, nx, e * 0.96, e * 1.07, 0.04), c=sim(b, j, nx, cs, e + 2 * (e - cs), 0.03))
    if any(v is None or abs(v) > 0.4 for v in out.values()):
        return None
    out["R"] = (e - cs) / e
    return out


# ---------------------------------------------------------------- 점수
def pct(vals):
    v = np.array([np.nan if x is None else x for x in vals], float)
    out = np.full(len(v), 0.5)
    m = ~np.isnan(v)
    if m.sum() > 1:
        out[m] = v[m].argsort().argsort() / (m.sum() - 1)
    return out


def logit_fit(X, y, lam=1.0, it=30):
    X1 = np.c_[np.ones(len(X)), X]
    w = np.zeros(X1.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X1 @ w))
        W = p * (1 - p)
        Hm = X1.T @ (X1 * W[:, None]) + lam * np.eye(len(w)); Hm[0, 0] -= lam
        gr = X1.T @ (p - y) + lam * np.r_[0, w[1:]]
        w -= np.linalg.solve(Hm, gr)
    return w


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    R_ = open(os.path.join(E.DATA, "backtest", "up_score.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s, flush=True); R_.write(s + "\n"); R_.flush()

    feat = _load("regime_feat.pkl")
    U = {d for d, x in feat.items() if cls_of(x) == "U"}

    # (0) 후보
    rows, _ = _load("u_cands.pkl")
    sel0 = [r for r in rows if r["T"] == time(9, 10) and r["date"] in U
            and r["vrank"] <= 40 and r["from_open"] > 0 and r["fr"] is not None
            and not ((r["fr"] or 0) < 0 and (r["ins"] or 0) < 0) and all(abs(v) < 0.4 for v in r["ex"].values())]
    one = defaultdict(set)
    for r in sel0:
        one[r["date"]].add(r["code"])

    # 점수 자료 (features.pkl T=09:10, 종목군 = 전날 대금 상위 200)
    F = pickle.load(open(os.path.join(E.DATA, "leader_early", "features.pkl"), "rb"))["rows"]
    F = [r for r in F if r["T"] == time(9, 10)]
    alld = sorted({r["d"] for r in F}); HALL = alld[len(alld) // 2]
    byd = defaultdict(list)
    for r in F:
        byd[r["d"]].append(r)
    # 그날 종목군 안 누적 대금 순위 + 백분위 (LR 학습용, part2 와 같게)
    for d, g in byd.items():
        for i, r in enumerate(sorted(g, key=lambda r: -(r["cum_val"] or 0))):
            r["cum_rank"] = i + 1
        for f in LR_F:
            for r, p in zip(g, pct([r.get(f) for r in g])):
                r["p_" + f] = p
    tr = [r for r in F if r["d"] < HALL]
    w = logit_fit(np.array([[r["p_" + f] for f in LR_F] for r in tr]) - 0.5, np.array([r["L1"] for r in tr], float))
    for r in F:
        r["s_lr"] = float(np.r_[1, np.array([r["p_" + f] for f in LR_F]) - 0.5] @ w)
    say(f"LR 학습: {alld[0]} ~ {HALL} 앞 절반 {len(tr):,}건 (모든 날, L1 {sum(r['L1'] for r in tr)}) → 뒤 절반 U 날만 평가")
    say("  LR 계수 큰 것: " + ", ".join(f"{f}{x:+.2f}" for f, x in sorted(zip(LR_F, w[1:]), key=lambda t: -abs(t[1]))[:8]))

    Udays = sorted(d for d in U if d in byd or d in one)
    fdays = sorted(d for d in U if d in byd)
    say(f"U 날: 1️⃣ 후보 있는 날 {len(one)}일 ({min(one)} ~ {max(one)}), 점수 자료 있는 U 날 {len(fdays)}일 ({fdays[0]} ~ {fdays[-1]})")
    nomatch = sum(1 for d in one for c in one[d] if d in byd and c not in {r['c'] for r in byd[d]})
    say(f"1️⃣ 후보 중 점수 자료(전날 200 보통주)에 없는 것 {nomatch}건 → (1) 에선 점수 맨 뒤")

    # 매매 결과 계산 (캐시)
    cache = {}

    def ex(c, d, t):
        k = (c, d, t)
        if k not in cache:
            cache[k] = all_exits(c, d, t)
        return cache[k]

    def picks(d, pool, key, k):
        """pool = features 행 리스트. key = 'ra'|'lr'. 상위 k 행."""
        pool = [r for r in pool if r["chg_T"] == r["chg_T"] and r["chg_T"] < 0.29]
        if not pool:
            return []
        if key == "ra":
            P = np.mean([pct([r[f] for r in pool]) for f in RA_F], axis=0)
        else:
            P = np.array([r["s_lr"] for r in pool])
        order = np.argsort(-P, kind="mergesort")
        return [pool[i]["c"] for i in order[:k]]

    strategies = {}   # 이름 → [(d, code, t_buy)]
    for d in sorted(one):
        for c in one[d]:
            strategies.setdefault("(0) 1️⃣ 40위 안 전부 · 09:10 매수", []).append((d, c, time(9, 10)))
            strategies.setdefault("(0') 1️⃣ 40위 안 전부 · 09:11 매수", []).append((d, c, time(9, 11)))
    for key, kn in (("ra", "순위평균"), ("lr", "LR")):
        for k in (3, 5, 10):
            for d in fdays:
                if key == "lr" and d < HALL:
                    continue
                g = byd[d]
                if d in one:
                    pool1 = [r for r in g if r["c"] in one[d]]
                    for c in picks(d, pool1, key, k):
                        strategies.setdefault(f"(1) 1️⃣ 후보 안 {kn} 상위 {k}", []).append((d, c, time(9, 11)))
                for c in picks(d, g, key, k):
                    strategies.setdefault(f"(2) 전날 200 전체 {kn} 상위 {k}", []).append((d, c, time(9, 11)))
    # LR 비교용: 같은 뒤 절반 날의 (0)·순위평균
    for nm in list(strategies):
        if nm.startswith("(0)") or "순위평균" in nm:
            strategies["[뒤 절반] " + nm] = [x for x in strategies[nm] if x[0] >= HALL]

    say(f"\n매수 결과 계산 중 … ({sum(len(v) for v in strategies.values())} 건)")
    for nm, lst in strategies.items():
        for d, c, t in lst:
            ex(c, d, t)

    # ---------------------------------------------------------------- 집계
    def report(nm, lst, exn):
        tr = [(d, ex(c, d, t)[exn]) for d, c, t in lst if ex(c, d, t)]
        if len(tr) < 10:
            say(f"   {nm:34s} {exn:3s} {len(tr)}건 (적음)"); return None
        ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
        v = np.array([x for _, x in tr])
        a = np.mean([x for d, x in tr if d < h]); b = np.mean([x for d, x in tr if d >= h])
        bd = defaultdict(list)
        for d, x in tr:
            bd[d].append(x)
        dr = {d: np.mean(x) for d, x in bd.items()}           # 날 수익률 (1,000만 균등 분배)
        s = sorted(dr.values(), reverse=True)
        star = "★" if a > 0 and b > 0 and sum(s[5:]) > 0 else " "
        seq = [dr[d] for d in sorted(dr)]
        eq = np.cumsum(seq) * CAP; mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
        comp = np.prod([1 + x for x in seq]) - 1
        say(f" {star} {nm:34s} {exn:3s} {len(v):4d}건 {len(dr):2d}일 건당 {v.mean():+.2%} | 앞 {a:+.2%} 뒤 {b:+.2%} | "
            f"날 평균 {np.mean(seq):+.2%} 1천만/일 합계 {sum(seq) * CAP:+5.0f}만 최고5일 빼면 {sum(s[5:]) * CAP:+5.0f}만 "
            f"복리 {comp:+.0%} 낙폭 {mdd:.0f}만 | 승률 {np.mean(v > 0):.0%}")
        return dict(nm=nm, ex=exn, n=len(v), mean=v.mean(), tot=sum(seq) * CAP, x5=sum(s[5:]) * CAP, mdd=mdd, star=star)

    say("\n" + "=" * 120)
    say("결과 — 건당 = 비용 뺀 평균 / 1천만/일 = 날마다 1,000만 원을 산 종목 수로 똑같이 나눈 날 수익의 합 (단리) / ★ = 앞·뒤 + & 최고 5일 빼도 +")
    say("매도 old=−4%·다음 날 09:00 / a=−3%·다음 날 09:00 / B=−4%·+7% 절반·고가 −4% 추적 / c=09:00~ 저가 손절·+2R 절반·고가 −3% 추적")
    say("=" * 120)
    res = []
    for nm, lst in strategies.items():
        if nm.startswith("[뒤 절반]") or "LR" in nm:
            continue
        say(f"\n{nm}")
        for exn in ("old", "a", "B", "c"):
            r = report(nm, lst, exn)
            if r: res.append(r)
        if nm.startswith("(0)"):
            n25 = [ex(c, d, t)["old"] for d, c, t in lst if ex(c, d, t)]
            nB = [ex(c, d, t)["B"] for d, c, t in lst if ex(c, d, t)]
            say(f"     (참고: 지금처럼 건당 25만 원이면 old 합계 {sum(n25) * 25:+.0f}만, B {sum(nB) * 25:+.0f}만 / 하루 평균 {len(n25) / len(one):.1f}종목)")
    say("\n" + "-" * 120)
    say(f"LR 점수는 뒤 절반 ({HALL} 이후) U 날만 — 같은 날의 (0)·순위평균과 나란히")
    for nm, lst in strategies.items():
        if not (nm.startswith("[뒤 절반]") or "LR" in nm):
            continue
        say(f"\n{nm}")
        for exn in ("old", "a", "B", "c"):
            report(nm, lst, exn)

    # c 손절 폭 참고
    rs = [ex(c, d, t)["R"] for nm, lst in strategies.items() if nm.startswith("(2) 전날 200 전체 순위평균 상위 3") for d, c, t in lst if ex(c, d, t)]
    if rs:
        say(f"\n(참고) (2) 순위평균 상위 3 의 c 손절 폭 R 중앙 {np.median(rs):.1%}, 90% {np.percentile(rs, 90):.1%}")
    say(f"매수 결과 못 구해 뺀 것: {sum(1 for v in cache.values() if v is None)} / {len(cache)}")
    say("\n가장 좋은 것 (1천만/일 합계, ★만):")
    for r in sorted([r for r in res if r["star"] == "★"], key=lambda r: -r["tot"])[:10]:
        say(f"  {r['nm']:34s} {r['ex']:3s} 건당 {r['mean']:+.2%} 합계 {r['tot']:+.0f}만 최고5일 빼면 {r['x5']:+.0f}만 낙폭 {r['mdd']:.0f}만")
    R_.close()


if __name__ == "__main__":
    main()
