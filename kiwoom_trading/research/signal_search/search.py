"""매수 신호 체계적 탐색 — 2단계: 워크포워드 탐색·우연 기준선 (2026-10-28).

입력: data/signal_search/dataset.parquet (build_dataset.py)
방법 (뒤 기간에서만 판단):
  분할  A = 앞 절반 날(고르기) / B = 뒤 절반 날(평가). 롤링 = 분기 4개, 앞 분기 전부로 고르고 다음 분기 평가 (Q2·Q3·Q4).
  M0 특징 하나씩: (날, 시각) 단면 순위 상관(IC) — A·B 각각 평균, B 기준 순위
  M1 규칙 탐색: 특징 분위(20·40·60·80%, A 에서 정함) ≥/≤ 조건 1개·2개 조합 → A 에서 고름(건수 ≥ 100·30일↑, A 앞·뒤 반 모두 +) → B 평가
  M2 릿지 회귀: 단면 백분위 특징 + 시장 특징 → 시각별 모델, 각 (날, 시각) 예측 상위 k 매수, 예측 > 0 일 때만도
  우연 기준선: A 라벨을 (날, 시각) 안에서 섞고 같은 탐색 반복 → 고른 규칙·모델의 B 성적 분포
라벨: L1s3 · L1s6 (15:19 까지), L2 (−6%, 다음 날 09:00), Lc (그날 종가 → 다음 날 09:00). 모두 비용 0.25% 뺀 값. lock(상한가 근처) 행 제외.
실행: PYTHONPATH=. .venv/Scripts/python.exe kiwoom_trading/research/signal_search/search.py → data/signal_search/search.txt, search_rules.parquet
"""
import os, sys, pickle, time as _clock
from collections import defaultdict

import numpy as np
import pandas as pd

DATA = os.environ.get("TRADING_DATA", r"D:\Ellie\trading\data")
OUT = os.path.join(DATA, "signal_search")
F = None
RNG = np.random.default_rng(7)

META = ["date", "T", "code", "name", "entry", "lock", "Lc", "L1s3", "L1s6", "L2", "mfe", "mae", "rclose", "in_prev200"]
MKT = ["k_ret", "k_ropen", "kdd52", "mkt_med", "mkt_med30", "mkt_br"]
LABELS = ["L1s3", "L1s6", "L2", "Lc"]
NPERM = int(os.environ.get("SS_NPERM", "30"))


def say(s=""):
    print(s, flush=True)
    if F: F.write(s + "\n"); F.flush()


def load():
    df = pd.read_parquet(os.path.join(OUT, os.environ.get("SS_IN", "dataset.parquet")))
    df = df[df["lock"] == 0].copy()
    if "close_pc" in df:   # 상한가로 마감한 종목은 종가에 못 산다 → 종가 매수 라벨(Lc) 뺌
        df.loc[df.close_pc >= 0.29, "Lc"] = np.nan
        df.loc[(df["T"] == "15:20") & (df.close_pc >= 0.29), "L2"] = np.nan
    df["date"] = pd.to_datetime(df["date"])
    feats = [c for c in df.columns if c not in META and c not in ("tmin", "close_pc")]
    df = df.replace([np.inf, -np.inf], np.nan)
    days = np.sort(df.date.unique())
    df["half"] = (df.date >= days[len(days) // 2]).astype(int)          # 0 = A, 1 = B
    q = np.array_split(days, 4)
    df["qtr"] = 0
    for k, dd in enumerate(q): df.loc[df.date.isin(dd), "qtr"] = k
    df["grp"] = df.groupby(["date", "T"]).ngroup()
    return df, feats, days


# ------------------------------------------------------------------ 평가 도우미
def acct(tr):
    """tr: DataFrame(date, ret) → 1천만/일 (그날 건수로 나눔) 합계·낙폭·★ (기간 안 앞·뒤 반 + 최고 5일 빼도 +). 단위 만원."""
    tr = tr[tr["ret"].notna()]
    if len(tr) == 0: return None
    g = tr.groupby("date")["ret"].mean() * 1000
    ds = g.index.sort_values(); h = ds[len(ds) // 2]
    eq = g.cumsum().values; mdd = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max())
    s = np.sort(g.values)[::-1]
    a, b = tr[tr.date < h].ret.mean(), tr[tr.date >= h].ret.mean()
    ok = a > 0 and b > 0 and s[5:].sum() > 0
    return dict(n=len(tr), days=len(g), mean=tr.ret.mean(), tot=g.sum(), ex5=s[5:].sum(), mdd=mdd, a=a, b=b, star=ok,
                win=(tr.ret > 0).mean())


def fmt(s):
    if s is None: return "없음"
    return (f"{'★' if s['star'] else ' '} {s['n']:5d}건 {s['days']:3d}일 건당 {s['mean']:+.2%} 합계 {s['tot']:+6.0f}만 "
            f"최고5일빼 {s['ex5']:+6.0f}만 낙폭 {s['mdd']:4.0f}만 앞 {s['a']:+.2%} 뒤 {s['b']:+.2%} 승률 {s['win']:.0%}")


# ------------------------------------------------------------------ M0 IC
def ic_table(df, feats, label):
    """(날,시각) 단면 스피어만 IC → 특징별 A·B 평균·t."""
    d = df[df[label].notna()]
    R = d.groupby("grp")[feats + [label]].rank(pct=True)
    R["grp"] = d["grp"].values; R["half"] = d["half"].values
    out = []
    for f in feats:
        x = R[[f, label, "grp", "half"]].dropna()
        x = x[x.groupby("grp")[f].transform("size") >= 20]
        xc = x[f] - x.groupby("grp")[f].transform("mean"); yc = x[label] - x.groupby("grp")[label].transform("mean")
        num = (xc * yc).groupby(x.grp).sum(); den = np.sqrt((xc ** 2).groupby(x.grp).sum() * (yc ** 2).groupby(x.grp).sum())
        ic = (num / den).replace([np.inf, -np.inf], np.nan).dropna()
        hv = x.groupby("grp").half.first().reindex(ic.index)
        r = dict(feat=f)
        for h in (0, 1):
            v = ic[hv == h]
            r[f"ic{h}"] = v.mean(); r[f"t{h}"] = v.mean() / v.std() * np.sqrt(len(v)) if len(v) > 5 else np.nan
        out.append(r)
    return pd.DataFrame(out)


# ------------------------------------------------------------------ M1 규칙 탐색
def conds_for(tr, feats):
    """A 자료 분위로 조건 목록 [(feat, op, thr)]."""
    cs = []
    for f in feats:
        v = tr[f].dropna().values
        if len(v) < 200: continue
        qs = np.unique(np.quantile(v, [0.2, 0.4, 0.6, 0.8]))
        for q in qs:
            cs.append((f, ">=", float(q))); cs.append((f, "<=", float(q)))
    return cs


def masks(d, cs):
    M = np.zeros((len(cs), len(d)), bool)
    for i, (f, op, q) in enumerate(cs):
        v = d[f].values
        with np.errstate(invalid="ignore"):
            M[i] = (v >= q) if op == ">=" else (v <= q)
    return M


def search_rules(tr, cs, y, nmin=100, dmin=30, top_single=40, keep=5):
    """A 행 tr, 조건 cs, 라벨 y(np) → 고른 규칙 [(idx tuple, A평균, n)] (A 앞·뒤 반 모두 + 인 것 중 평균 높은 순)."""
    M = masks(tr, cs).astype(np.float32)
    dates = tr.date.values; dh = np.sort(np.unique(dates)); mid = dh[len(dh) // 2]
    w1 = (dates < mid).astype(np.float32); w2 = 1 - w1
    y = y.astype(np.float32)
    # 날 수: 조건별 날 비트 (근사: 날짜 인덱스 행렬)
    di = np.searchsorted(dh, dates)
    Dm = np.zeros((len(dh), len(tr)), np.float32); Dm[di, np.arange(len(tr))] = 1
    def score(Mx):
        n = Mx @ np.ones(len(tr), np.float32); s = Mx @ y
        n1 = Mx @ w1; s1 = Mx @ (y * w1); n2 = Mx @ w2; s2 = Mx @ (y * w2)
        nd = ((Mx @ Dm.T) > 0).sum(1)
        with np.errstate(all="ignore"):
            m = s / n; ok = (n >= nmin) & (nd >= dmin) & (s1 / np.maximum(n1, 1) > 0) & (s2 / np.maximum(n2, 1) > 0) & (n1 >= 20) & (n2 >= 20)
        return np.where(ok, m, -np.inf), n
    sc1, n1_ = score(M)
    cand = [((i,), sc1[i], n1_[i]) for i in np.flatnonzero(np.isfinite(sc1))]
    order = np.argsort(-np.where(np.isfinite(sc1), sc1, -9))[:top_single]
    # 짝: 상위 단일 × 전체
    for i in order:
        if not np.isfinite(sc1[i]) and sc1[i] == -np.inf and n1_[i] < nmin: pass
        Mi = M * M[i]
        sc2, n2_ = score(Mi)
        for j in np.flatnonzero(np.isfinite(sc2)):
            if j == i or cs[j][0] == cs[i][0]: continue
            cand.append((tuple(sorted((i, j))), sc2[j], n2_[j]))
    ntried = len(cs) + len(order) * len(cs)
    seen, best = set(), []
    for c in sorted(cand, key=lambda x: -x[1]):
        if c[0] in seen: continue
        seen.add(c[0]); best.append(c)
        if len(best) >= keep: break
    return best, ntried


def apply_rule(d, cs, idx):
    m = np.ones(len(d), bool)
    for i in idx:
        f, op, q = cs[i]; v = d[f].values
        with np.errstate(invalid="ignore"):
            m &= (v >= q) if op == ">=" else (v <= q)
    return m


def rule_text(cs, idx):
    return " & ".join(f"{cs[i][0]} {cs[i][1]} {cs[i][2]:.4g}" for i in idx)


def perm_labels(d, label):
    """(날, 시각) 안에서 라벨 섞기."""
    y = d[label].values.copy(); g = d["grp"].values
    order = np.argsort(g, kind="stable"); gs = g[order]
    cuts = np.flatnonzero(np.diff(gs)) + 1
    for part in np.split(order, cuts):
        y[part] = y[RNG.permutation(part)]
    return y


# ------------------------------------------------------------------ M2 릿지
def prep_X(d, feats):
    R = d.groupby("grp")[[f for f in feats if f not in MKT]].rank(pct=True) - 0.5
    R = R.fillna(0.0)
    Mk = d[MKT].copy()
    return R, Mk


def fit_ridge(X, y, lam):
    Xa = np.c_[X, np.ones(len(X))]
    A = Xa.T @ Xa + lam * np.eye(Xa.shape[1]); A[-1, -1] -= lam
    return np.linalg.solve(A, Xa.T @ y)


def pred(X, w):
    return np.c_[X, np.ones(len(X))] @ w


def ridge_eval(df, feats, label, tr_mask, te_mask, Ts, ks=(1, 3, 5), perm=False, lam=None):
    """시각별 모델 → 평가 기간 상위 k 매수 결과 {(T,k,gate): DataFrame(date, ret)}."""
    out = {}
    R, Mk = prep_X(df, feats)
    for T in Ts:
        mt = (df["T"] == T).values & df[label].notna().values
        tr = mt & tr_mask; te = mt & te_mask
        if tr.sum() < 500 or te.sum() < 200: continue
        mu, sd = Mk[tr].mean(), Mk[tr].std().replace(0, 1)
        Xall = np.c_[R.values, ((Mk - mu) / sd).fillna(0).values]
        y = np.clip(df[label].values, -0.1, 0.1)
        ytr = perm_labels(df[tr], label).clip(-0.1, 0.1) if perm else y[tr]
        if lam is None:
            # A 안에서 마지막 1/4 날로 람다 고르기
            dtr = df.date.values[tr]; ud = np.sort(np.unique(dtr)); cut = ud[int(len(ud) * 0.75)]
            fi, va = dtr < cut, dtr >= cut
            best = None
            for L in (10.0, 100.0, 1000.0, 10000.0):
                w = fit_ridge(Xall[tr][fi], ytr[fi], L); p = pred(Xall[tr][va], w)
                g = df["grp"].values[tr][va]; yy = ytr[va]
                s = pd.DataFrame(dict(g=g, p=p, y=yy)).sort_values("p", ascending=False).groupby("g").head(3).y.mean()
                if best is None or s > best[0]: best = (s, L)
            L = best[1]
        else:
            L = lam
        w = fit_ridge(Xall[tr], ytr, L)
        p = pred(Xall[te], w)
        d = pd.DataFrame(dict(date=df.date.values[te], g=df["grp"].values[te], p=p, ret=df[label].values[te], code=df.code.values[te]))
        d = d.sort_values("p", ascending=False)
        for k in ks:
            top = d.groupby("g").head(k)
            out[(T, k, "모두")] = top
            out[(T, k, "예측>0")] = top[top.p > 0]
        out[(T, 0, "평균")] = d   # 무작위 기준 (전체 평균)
        out[(T, "w")] = (w, L)
    return out


def main():
    global F
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = _clock.time()
    F = open(os.path.join(OUT, "search.txt"), "w", encoding="utf-8")
    df, feats, days = load()
    Ts = sorted(df["T"].unique())
    A, B = (df.half == 0).values, (df.half == 1).values
    say(f"데이터셋 {len(df):,}행 (상한가 근처 제외) · {len(days)}일 {pd.Timestamp(days[0]).date()}~{pd.Timestamp(days[-1]).date()} · "
        f"시각 {len(Ts)}개 · 특징 {len(feats)}개 · A(고르기) {pd.Timestamp(days[0]).date()}~ / B(평가) {pd.Timestamp(days[len(days) // 2]).date()}~")
    say("기준: 각 (날, 시각) 상위 100 전부를 산다고 칠 때의 평균 = 무작위로 고르는 것과 같음")
    for lab in LABELS:
        g = df[df[lab].notna()]
        say(f"  {lab}: A {g[g.half == 0][lab].mean():+.2%}  B {g[g.half == 1][lab].mean():+.2%}  | 시각별 B: " +
            " ".join(f"{T} {g[(g.half == 1) & (g['T'] == T)][lab].mean():+.2%}" for T in Ts))

    # ---------------- M0
    say("\n" + "=" * 140)
    say("[M0] 특징 하나씩 — (날, 시각) 단면 순위 상관(IC) 평균. 양수 = 클수록 그날 상위 100 안에서 더 오름. B 기준 |t| 순.")
    ics = {}
    for lab in LABELS:
        t = ic_table(df, feats, lab); ics[lab] = t
        t = t.assign(same=np.sign(t.ic0) == np.sign(t.ic1)).sort_values("t1", key=lambda s: -s.abs())
        say(f"\n  라벨 {lab} (위 15개)  특징 | A IC (t) | B IC (t) | 방향 같음")
        for _, r in t.head(15).iterrows():
            say(f"    {r.feat:12s} A {r.ic0:+.3f} ({r.t0:+5.1f}) | B {r.ic1:+.3f} ({r.t1:+5.1f}) | {'같음' if r.same else '반대'}")
    pickle.dump(ics, open(os.path.join(OUT, "ic.pkl"), "wb"))

    # ---------------- M1
    say("\n" + "=" * 140)
    say("[M1] 규칙 탐색 (조건 1~2개) — A 에서 고르고 B 에서 평가. 시각·라벨마다 A 최고 5개.")
    rule_rows = []; ntried_all = 0
    best_real = {}
    for lab in LABELS:
        for T in Ts:
            d = df[(df["T"] == T) & df[lab].notna()]
            tr, te = d[d.half == 0], d[d.half == 1]
            if len(tr) < 1000: continue
            cs = conds_for(tr, feats)
            best, nt = search_rules(tr, cs, tr[lab].values)
            ntried_all += nt
            for rnk, (idx, ma, n) in enumerate(best):
                m = apply_rule(te, cs, idx)
                tt = te[m]
                s = acct(tt.assign(ret=tt[lab]))
                base = te[lab].mean()
                rule_rows.append(dict(label=lab, T=T, rank=rnk, rule=rule_text(cs, idx), A_mean=ma, A_n=n,
                                      B_n=len(tt), B_mean=tt[lab].mean() if len(tt) else np.nan, B_base=base,
                                      B_star=s["star"] if s else False, B_tot=s["tot"] if s else np.nan))
                if rnk == 0: best_real[(lab, T)] = tt[lab].mean() if len(tt) else np.nan
    RR = pd.DataFrame(rule_rows)
    RR.to_parquet(os.path.join(OUT, "search_rules.parquet"))
    say(f"  시도한 규칙 수 (조건 1개 + 상위 40 × 전체 짝) 합계 약 {ntried_all:,}개 (라벨 {len(LABELS)} × 시각 {len(Ts)})")
    say(f"  {'라벨':5s} {'시각':5s} {'A평균':>7s} {'A건':>5s} | {'B평균':>7s} {'B기준':>7s} {'B건':>5s} {'B★':>3s} {'B합계':>7s} | 규칙")
    for _, r in RR[RR["rank"] == 0].iterrows():
        say(f"  {r.label:5s} {r['T']:5s} {r.A_mean:+.2%} {r.A_n:5.0f} | {r.B_mean:+.2%} {r.B_base:+.2%} {r.B_n:5d} {'★' if r.B_star else ' ':>3s} {r.B_tot:+7.0f}만 | {r.rule}")
    say(f"\n  A 최고 5개 전체({len(RR)}개) 중 B 에서: 플러스 {np.mean(RR.B_mean > 0):.0%}, 기준보다 나음 {np.mean(RR.B_mean > RR.B_base):.0%}, "
        f"B ★ {RR.B_star.sum()}개, B 평균의 평균 {RR.B_mean.mean():+.2%} (기준 평균 {RR.B_base.mean():+.2%})")

    # 우연 기준선 (M1)
    say(f"\n  [우연 기준선] A 라벨을 (날, 시각) 안에서 섞고 같은 탐색 {NPERM}번 → 고른 1위 규칙의 B 평균")
    null = defaultdict(list)
    for it in range(NPERM):
        for lab in LABELS:
            for T in Ts:
                d = df[(df["T"] == T) & df[lab].notna()]
                tr, te = d[d.half == 0], d[d.half == 1]
                if len(tr) < 1000: continue
                cs = conds_for(tr, feats)
                best, _ = search_rules(tr, cs, perm_labels(tr, lab), top_single=20, keep=1)
                if not best: null[(lab, T)].append(np.nan); continue
                m = apply_rule(te, cs, best[0][0])
                null[(lab, T)].append(te[m][lab].mean() if m.sum() else np.nan)
        print(f"   perm {it + 1}/{NPERM} {_clock.time() - t0:.0f}s", file=sys.stderr, flush=True)
    say(f"  {'라벨':5s} {'시각':5s} {'실제 1위 B':>9s} | 섞은 것 B 평균 (중앙·90%) | 실제가 섞은 것보다 큰 비율")
    pv = []
    for (lab, T), v in sorted(best_real.items()):
        nv = np.array(null[(lab, T)], float); nv = nv[~np.isnan(nv)]
        if not len(nv): continue
        frac = np.mean(v > nv); pv.append(frac)
        say(f"  {lab:5s} {T:5s} {v:+.2%} | {np.median(nv):+.2%} · {np.quantile(nv, 0.9):+.2%} | {frac:.0%}")
    pickle.dump(dict(null=dict(null), real=best_real), open(os.path.join(OUT, "rule_null.pkl"), "wb"))

    # ---------------- M2
    say("\n" + "=" * 140)
    say("[M2] 릿지 회귀 (시각별) — A 로 학습, B 에서 각 (날, 시각) 예측 상위 k 매수. '예측>0' = 모델이 비용 뒤 + 라고 볼 때만.")
    ridge_res = {}
    for lab in LABELS:
        res = ridge_eval(df, feats, lab, A, B, Ts)
        ridge_res[lab] = res
        say(f"\n  라벨 {lab}")
        for T in Ts:
            if (T, 0, "평균") not in res: continue
            base = res[(T, 0, "평균")].ret.mean()
            parts = [f"{T} 기준 {base:+.2%}"]
            for k in (1, 3, 5):
                for gate in ("모두", "예측>0"):
                    s = acct(res[(T, k, gate)])
                    parts.append(f"상위{k}{'' if gate == '모두' else '·예측+'} {s['mean']:+.2%}{'★' if s['star'] else ''}({s['n']})" if s else f"상위{k} 없음")
            say("    " + " | ".join(parts))
    # 우연 기준선 (M2): 상위3 B 평균
    say(f"\n  [우연 기준선] A 라벨 섞고 릿지 {NPERM}번 → B 상위 3 평균 (실제와 비교)")
    for lab in LABELS:
        real = {T: ridge_res[lab][(T, 3, "모두")].ret.mean() for T in Ts if (T, 3, "모두") in ridge_res[lab]}
        nul = defaultdict(list)
        for it in range(NPERM):
            res = ridge_eval(df, feats, lab, A, B, Ts, ks=(3,), perm=True, lam=1000.0)
            for T in real: nul[T].append(res[(T, 3, "모두")].ret.mean())
        say(f"  {lab}: " + " | ".join(f"{T} 실제 {real[T]:+.2%} 섞음 중앙 {np.median(nul[T]):+.2%} 95% {np.quantile(nul[T], 0.95):+.2%} "
                                      f"{'통과' if real[T] > np.quantile(nul[T], 0.95) else ''}" for T in real))
    pickle.dump({lab: {k: v for k, v in r.items()} for lab, r in ridge_res.items()}, open(os.path.join(OUT, "ridge_AB.pkl"), "wb"))

    # ---------------- 롤링 (분기)
    say("\n" + "=" * 140)
    say("[롤링] 앞 분기 전부로 학습 → 다음 분기 평가 (Q2·Q3·Q4). 릿지 상위 3 / 규칙 1위. 값 = 평가 분기 건당 평균 (기준 = 상위 100 평균)")
    roll = []
    for lab in LABELS:
        for T in Ts:
            line = [f"  {lab:5s} {T}"]
            for q in (1, 2, 3):
                trm = (df.qtr < q).values; tem = (df.qtr == q).values
                res = ridge_eval(df, feats, lab, trm, tem, [T], ks=(3,), lam=1000.0)
                if (T, 3, "모두") not in res: continue
                rv = res[(T, 3, "모두")].ret.mean(); bv = res[(T, 0, "평균")].ret.mean()
                d = df[(df["T"] == T) & df[lab].notna()]
                tr, te = d[d.qtr < q], d[d.qtr == q]
                cs = conds_for(tr, feats)
                best, _ = search_rules(tr, cs, tr[lab].values, keep=1, top_single=20)
                if best:
                    m = apply_rule(te, cs, best[0][0]); rl = te[m][lab].mean() if m.sum() else np.nan; rn = int(m.sum())
                else:
                    rl, rn = np.nan, 0
                roll.append(dict(label=lab, T=T, q=q, ridge=rv, base=bv, rule=rl, rule_n=rn))
                line.append(f"Q{q + 1} 릿지 {rv:+.2%} 규칙 {rl:+.2%}({rn}) 기준 {bv:+.2%}")
            say(" | ".join(line))
    pd.DataFrame(roll).to_parquet(os.path.join(OUT, "rolling.parquet"))
    say(f"\n끝 {_clock.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
