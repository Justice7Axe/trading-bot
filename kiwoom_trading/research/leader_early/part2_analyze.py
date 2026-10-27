"""PART 2·3 — features.pkl 로 (2) 특징별 구분력(AUC)·묶은 점수·정밀도@k, (3) 점수 상위 매수 결과.

묶은 점수: 그날 종목군 안 백분위 순위로 바꾼 특징들로
  · LR  = 로지스틱 회귀 (앞 절반으로 학습 → 뒤 절반 평가, 뒤 절반으로 학습 → 앞 절반 평가: 모든 날이 '처음 보는' 점수)
  · 순위평균 = 다른 절반에서 구분력 큰 5개 특징(방향 맞춤)의 백분위 평균
실행: PYTHONPATH=D:\\Ellie\\trading python kiwoom_trading/research/leader_early/part2_analyze.py
"""
import os, pickle, sys
from collections import defaultdict
from datetime import time
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import OUT, auc, Rep

D = pickle.load(open(os.path.join(OUT, "features.pkl"), "rb"))
rows, miss = D["rows"], D["miss"]
R = Rep("part2_part3.txt")
TS = [time(8, 59), time(9, 3), time(9, 5), time(9, 10)]
FEATS = ["prev_rank", "prev_val", "prev_chg", "mcap", "pre_val", "pre_ratio", "pre_burst", "pre_gap", "pre_hi",
         "flow_fi", "flow_f", "flow_i", "chg_T", "from_open", "open_gap", "cum_val", "cum_ratio", "cum_rank",
         "burst", "reg_burst", "nhigh", "hi52"]
KOR = dict(prev_rank="전날 대금 순위", prev_val="전날 대금", prev_chg="전날 등락", mcap="시총", pre_val="프리장 대금",
           pre_ratio="프리장 대금÷전날 대금", pre_burst="프리장 최대 1분 대금÷전날 분당", pre_gap="프리장 마지막 갭",
           pre_hi="프리장 고가 갭", flow_fi="전날 외인+기관÷대금", flow_f="전날 외인÷대금", flow_i="전날 기관÷대금",
           chg_T="T 전일 대비", from_open="T 시가 대비", open_gap="09:00 시가 갭", cum_val="09:00~T 누적 대금",
           cum_ratio="누적 대금÷전날 대금", cum_rank="누적 대금 순위(종목군 안)", burst="최대 1분 대금(햄버거)÷전날 분당",
           reg_burst="정규장 최대 1분 대금÷전날 분당", nhigh="09:00~T 신고가 횟수", hi52="T 가격÷52주 고가")

days = sorted({r["d"] for r in rows}); H = days[len(days) // 2]
for r in rows: r["half"] = 0 if r["d"] < H else 1

# 그날·T 안 누적 대금 순위 (08:59 는 프리장 대금 순위)
by = defaultdict(list)
for r in rows: by[(r["d"], r["T"])].append(r)
for k, g in by.items():
    key = "pre_val" if k[1] < time(9, 0) else "cum_val"
    for i, r in enumerate(sorted(g, key=lambda r: -(r[key] or 0))): r["cum_rank"] = i + 1


def pct_rank(g, f):
    v = np.array([g_.get(f) if g_.get(f) is not None else np.nan for g_ in g], float)
    out = np.full(len(v), 0.5); m = ~np.isnan(v)
    if m.sum() > 1:
        o = v[m].argsort().argsort(); out[m] = o / (m.sum() - 1)
    return out


for g in by.values():
    for f in FEATS:
        p = pct_rank(g, f)
        for r, x in zip(g, p): r["p_" + f] = x

R("=" * 110)
R(f"PART 2 — 1년 {days[0]} ~ {days[-1]} ({len(days)}일, 앞/뒤 나눔 {H}), 종목군 = 전날 대금 상위 200 (주식·우선주 제외)")
R("=" * 110)
nl1 = sum(m[1] for m in miss); nout = sum(m[2] for m in miss)
R(f" L1 주도주 {nl1}건 (하루 {nl1 / len(miss):.1f}) 중 전날 상위 200 밖 {nout}건 = {nout / nl1:.0%} → 이 연구로는 원래 못 잡는 몫")
ex = [n for m in miss for n in m[3]][:15]
R(f"  (예: {', '.join(ex)} …)")
for T in TS:
    g = [r for r in rows if r["T"] == T]
    R(f" T={T.strftime('%H:%M')}: 종목·일 {len(g)}건, L1 {sum(r['L1'] for r in g)} ({np.mean([r['L1'] for r in g]):.1%}), L2 {sum(r['L2'] for r in g)}")


# ---------------------------------------------------------------- AUC
R("\n[1] 특징 하나씩 구분력 (AUC, 모든 날 묶음 / 0.5=무작위, 0.5 아래는 '낮을수록 주도주') — L1 전체·앞·뒤 / L2 전체")
best = {}
for T in TS:
    g = [r for r in rows if r["T"] == T]
    R(f"\n T={T.strftime('%H:%M')}   {'특징':34s} {'L1':>6s} {'앞':>6s} {'뒤':>6s} {'L2':>6s} | 그날 안 순위 L1")
    res = []
    for f in FEATS:
        x = np.array([r.get(f) if r.get(f) is not None else np.nan for r in g], float)
        if np.all(np.isnan(x)) or np.nanstd(x) == 0: continue
        y1 = np.array([r["L1"] for r in g]); y2 = np.array([r["L2"] for r in g]); hf = np.array([r["half"] for r in g])
        a = auc(x, y1); a0 = auc(x[hf == 0], y1[hf == 0]); a1 = auc(x[hf == 1], y1[hf == 1]); a2 = auc(x, y2)
        ap = auc(np.array([r["p_" + f] for r in g]), y1)
        res.append((abs(ap - 0.5), f, a, a0, a1, a2, ap))
    for _, f, a, a0, a1, a2, ap in sorted(res, reverse=True):
        R(f"            {KOR[f]:34s} {a:6.3f} {a0:6.3f} {a1:6.3f} {a2:6.3f} | {ap:6.3f}")
    best[T] = sorted(res, reverse=True)


# ---------------------------------------------------------------- 묶은 점수
def logit_fit(X, y, lam=1.0, it=30):
    X1 = np.c_[np.ones(len(X)), X]; w = np.zeros(X1.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X1 @ w)); W = p * (1 - p)
        Hm = X1.T @ (X1 * W[:, None]) + lam * np.eye(len(w)); Hm[0, 0] -= lam
        gr = X1.T @ (p - y) + lam * np.r_[0, w[1:]]
        w -= np.linalg.solve(Hm, gr)
    return w


def feats_for(T):
    fs = [f for f in FEATS if not (T < time(9, 0) and f in ("from_open", "open_gap", "cum_val", "cum_ratio", "reg_burst", "nhigh"))]
    return [f for f in fs if f not in ("flow_fi", "flow_f", "flow_i")]   # 수급은 10-13 까지만 → 묶음에선 뺌 (따로 표시)


def score_rows(T, which="L1"):
    g = [r for r in rows if r["T"] == T]; fs = feats_for(T)
    X = np.array([[r["p_" + f] for f in fs] for r in g]) - 0.5
    y = np.array([r[which] for r in g], float); hf = np.array([r["half"] for r in g])
    lr = np.zeros(len(g)); ra = np.zeros(len(g)); coefs = {}
    for h in (0, 1):
        tr, te = hf != h, hf == h
        w = logit_fit(X[tr], y[tr]); lr[te] = np.c_[np.ones(te.sum()), X[te]] @ w; coefs[h] = w
        aucs = sorted(((abs(auc(X[tr, i], y[tr]) - 0.5), i, auc(X[tr, i], y[tr])) for i in range(len(fs))), reverse=True)[:5]
        ra[te] = np.mean([X[te, i] * (1 if a > 0.5 else -1) for _, i, a in aucs], axis=0)
        coefs[f"ra{h}"] = [(fs[i], round(a, 3)) for _, i, a in aucs]
    for r, a, b in zip(g, lr, ra): r["s_lr"] = a; r["s_ra"] = b
    return g, fs, coefs


def prec_at(g, key, which, ks=(1, 3, 5, 10)):
    byd = defaultdict(list)
    for r in g: byd[r["d"]].append(r)
    out = {k: [] for k in ks}; rec10 = [0, 0]; hit3 = []
    for d, lst in byd.items():
        lst = sorted(lst, key=lambda r: -r[key])
        for k in ks: out[k].append(np.mean([r[which] for r in lst[:k]]))
        tot = sum(r[which] for r in lst); rec10[0] += sum(r[which] for r in lst[:10]); rec10[1] += tot
        if tot: hit3.append(any(r[which] for r in lst[:3]))
    return {k: np.mean(v) for k, v in out.items()}, rec10[0] / max(rec10[1], 1), np.mean(hit3)


R("\n[2] 묶은 점수 — 처음 보는 절반으로 평가 (교차 적합). 정밀도@k = 그날 점수 상위 k 중 주도주 비율 (하루 평균)")
R(f" {'T':5s} {'점수':22s} {'라벨':4s} {'AUC':>6s} {'앞':>6s} {'뒤':>6s} | {'P@1':>5s} {'P@3':>5s} {'P@5':>5s} {'P@10':>5s} | 10위 안 재현 | 상위3에 1개↑(주도주 있는 날)")
SC = {}
for T in TS:
    for which in ("L1", "L2"):
        g, fs, coefs = score_rows(T, which)
        for key, nm in (("s_lr", "LR(로지스틱)"), ("s_ra", "순위평균 5개"), ("p_chg_T", "T 전일 대비만"), ("p_cum_val" if T >= time(9, 0) else "p_pre_val", "누적 대금만")):
            s = np.array([r[key] for r in g]); y = np.array([r[which] for r in g]); hf = np.array([r["half"] for r in g])
            p, rc, h3 = prec_at(g, key, which)
            R(f" {T.strftime('%H:%M'):5s} {nm:22s} {which:4s} {auc(s, y):6.3f} {auc(s[hf == 0], y[hf == 0]):6.3f} {auc(s[hf == 1], y[hf == 1]):6.3f} | "
              f"{p[1]:5.0%} {p[3]:5.0%} {p[5]:5.0%} {p[10]:5.0%} | {rc:6.0%}      | {h3:5.0%}")
        if which == "L1":
            SC[T] = {(r["d"], r["c"]): (r["s_lr"], r["s_ra"]) for r in g}
            R(f"        순위평균 고른 특징 (앞으로 학습): {coefs['ra0']}")
            R(f"        LR 계수(뒤 절반 평가용, 앞 절반 학습): " + ", ".join(f"{f}{w:+.1f}" for f, w in sorted(zip(fs, coefs[0][1:]), key=lambda x: -abs(x[1]))[:8]))
    R("")
base = np.mean([r["L1"] for r in rows if r["T"] == TS[-1]])
R(f" (무작위로 고르면 정밀도 ≈ {base:.1%})")

# ---------------------------------------------------------------- PART 3 매매
for r in rows:
    s = SC.get(r["T"], {}).get((r["d"], r["c"]))
    r["s_lr"], r["s_ra"] = s if s else (np.nan, np.nan)
# 장 초 분위기: 그 시각 종목군 전일 대비 중앙
med = {}
for k, g in by.items(): med[k] = np.nanmedian([r["chg_T"] for r in g])


def stats(tr, title):
    """tr = [(date, ret)] (ret 는 비용 뺀 비율). 합계는 건당 100만 원 기준 만 원."""
    tr = [(d, x) for d, x in tr if x is not None and not np.isnan(x)]
    if len(tr) < 15:
        R(f"  {title:58s} {len(tr)}건 (적음)"); return
    ds = sorted({d for d, _ in tr}); h = H
    v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < h]; b = [x for d, x in tr if d >= h]
    bd = defaultdict(float)
    for d, x in tr: bd[d] += x
    s = sorted(bd.values(), reverse=True)
    eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
    ma = np.mean(a) if a else np.nan; mb = np.mean(b) if b else np.nan
    ok = "★" if (ma > 0 and mb > 0 and sum(s[5:]) > 0) else " "
    R(f" {ok}{title:58s} {len(v):5d}건 {len(bd):3d}일 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+6.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+6.0f}만 "
      f"| 앞 {ma:+.2%} 뒤 {mb:+.2%} | 승률 {np.mean(v > 0):.0%} 낙폭 {mdd * 100:.0f}만")


R("\n" + "=" * 110)
R("PART 3 — 점수 상위 매수 (T 다음 봉 시가, 상한가 근처 +29%↑ 제외), 건당 100만 원, 비용 0.25% 포함")
R(" 매도 a = 손절 −3% 아니면 다음 날 09:00 시가 / c = 손절 09:00~T 저가, +2R 절반·나머지 고가 −3% 추적, 아니면 다음 날 09:00")
R(" ★ = 앞·뒤 반 모두 + & 가장 좋은 5일 빼도 +")
R("=" * 110)
for T in TS:
    g = [r for r in rows if r["T"] == T and r["chg_T"] == r["chg_T"] and r["chg_T"] < 0.29]
    byd = defaultdict(list)
    for r in g: byd[r["d"]].append(r)
    rp = np.nanmedian([r["r_pct"] for r in g if r["L1"]])
    R(f"\n── T={T.strftime('%H:%M')}  (종목·일 {len(g)}, 주도주의 c 손절폭 R 중앙 {rp:.1%})")
    for ex in ("ret_a", "ret_c"):
        R(f" [매도 {ex[-1]}]")
        stats([(r["d"], r[ex]) for r in g], "종목군 전체 (아무거나)")
        for key, nm in (("s_lr", "LR"), ("s_ra", "순위평균")):
            for k in (3, 5):
                sel = [r for d, lst in byd.items() for r in sorted(lst, key=lambda r: -(r[key] if r[key] == r[key] else -9))[:k]]
                stats([(r["d"], r[ex]) for r in sel], f"{nm} 점수 상위 {k}")
                if key == "s_lr" and k == 3:
                    strong = [r for r in sel if med[(r["d"], T)] >= 0.015]; weak = [r for r in sel if med[(r["d"], T)] < 0.015]
                    stats([(r["d"], r[ex]) for r in strong], "  └ 그 시각 종목군 중앙 +1.5%↑ 날만")
                    stats([(r["d"], r[ex]) for r in weak], "  └ 그 밖의 날")
                    stats([(r["d"], r[ex]) for r in sel if r["L1"]], "  └ (사후) 고른 것 중 실제 주도주만")
                    stats([(r["d"], r[ex]) for r in sel if not r["L1"]], "  └ (사후) 고른 것 중 주도주 아닌 것")
        if T >= time(9, 0):
            rule = [r for r in g if r["cum_rank"] <= 20 and r["chg_T"] >= 0.03]
            stats([(r["d"], r[ex]) for r in rule], "규칙: 누적 대금 20위 & +3%↑ (PART1 규칙)")
            rule = [r for r in g if r["cum_rank"] <= 10 and r["chg_T"] >= 0.03]
            stats([(r["d"], r[ex]) for r in rule], "규칙: 누적 대금 10위 & +3%↑")
        stats([(r["d"], r[ex]) for r in g if r["L1"]], "⚠미래 정보: 그날 L1 주도주 전부 (상한)")
        stats([(r["d"], r[ex]) for r in g if r["L2"]], "⚠미래 정보: 그날 L2 주도주 전부 (상한)")
R("\n(참고) 수급 특징(전날 외인·기관)은 2026-10-13 까지만 있어 묶은 점수에서 뺐다. 단독 AUC 는 [1] 표 참고.")
