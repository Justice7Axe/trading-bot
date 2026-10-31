"""상승 직전 종목 찾기 — 분석 (build.py 결과 data/early_rise/feat_*.parquet).

1) 특징 하나씩 구분력(AUC, 앞·뒤 반) — 대상: 아직 덜 오른 시점(전일 대비 −5% ~ +5%)
2) 묶은 점수: LightGBM, 달마다 그 전 달까지만으로 학습 → 그 달 점수 (처음 보는 자료만 평가, 첫 3달은 학습만)
3) 점수 상위 매수: 시점마다 점수 1등이 기준(학습 기간 상위 q) 넘으면 다음 봉 시가 매수, 종목당 하루 1번, 하루 최대 K
   매도: 익절·손절 먼저 닿는 쪽, 아니면 다음 날 09:00 (종가 매도 안 함), 비용 0.25%
4) 비교: 같은 시점 아무 종목(기준), 대금 가속 1등, 순위 급상승 1등, 키움 조회 순위(1분) 20위 처음 진입(10-13 ~)
실행: PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/early_rise/analyze.py
"""
import glob, os, shutil, sys, tempfile
from collections import defaultdict
from datetime import datetime, time
import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "early_rise")
DROP = {"date", "code", "y", "edge", "m", "score", "score2", "dec", "mfe60", "mae60", "r1519", "buy", "cval", "d_close", "d_val20", "fr1", "ins1", "fr5", "ins5", "crank15"}
EXITS = {"+5/−2": (0.05, 0.02), "+5/−3": (0.05, 0.03), "+3/−2": (0.03, 0.02), "+7/−3": (0.07, 0.03), "익절 없음/−3": (None, 0.03)}


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


R = Rep("report.txt")


def auc(y, s):
    m = ~np.isnan(s); y, s = y[m], s[m]
    if y.sum() == 0 or y.sum() == len(y): return np.nan
    r = pd.Series(s).rank().values
    return (r[y == 1].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (len(y) - y.sum()))


def load():
    df = pd.concat((pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(OUT, "feat_*.parquet")))), ignore_index=True)
    df = df.replace([np.inf, -np.inf], np.nan)
    df["date"] = pd.to_datetime(df.date).dt.date
    # 기대 손익 근사 (+5% 익절 / −2% 손절 / 60분 안에 둘 다 아니면 15:19 값을 −2~+5% 로 자름) — 출렁임만 큰 종목에 속지 않게
    stop = (df.y == 0) & (df.mae60 <= -0.02)
    df["edge"] = np.where(df.y == 1, 0.05, np.where(stop, -0.02, df.r1519.clip(-0.02, 0.05))) - E.COST
    return df


# ---------------------------------------------------------------- 매매 결과 (실제 1분봉으로)
_exit_cache = {}


def trade(c, d, t, buy):
    """t(분) 봉 다음 봉 시가 매수 → EXITS 별 수익."""
    key = (c, d, t)
    if key in _exit_cache: return _exit_cache[key]
    b = E.bars(c, d); tt = time(t // 60, t % 60)
    j = next((i for i, x in enumerate(b) if x[0] > tt), None)
    out = {}
    if j is not None:
        for name, (tp, sl) in EXITS.items():
            r, _ = E.intraday_exit(b, j, b[j][1], stop=sl, tp=tp, hold=lambda _: True, c=c, d=d)
            out[name] = r
    _exit_cache[key] = out
    return out


def stats(trs, title):
    """trs = [(date, {exit: ret})] → 매도별 한 줄."""
    if len(trs) < 15:
        R.say(f"  {title}: {len(trs)}건 (적음)"); return
    ds = sorted({d for d, _ in trs}); h = ds[len(ds) // 2]
    R.say(f"  {title}: {len(trs)}건 {len(ds)}일")
    for name in EXITS:
        v = [(d, x[name]) for d, x in trs if name in x]
        a = np.mean([r for d, r in v if d < h]); b_ = np.mean([r for d, r in v if d >= h])
        bd = defaultdict(float)
        for d, r in v: bd[d] += r
        s = sorted(bd.values(), reverse=True)
        star = "★" if a > 0 and b_ > 0 and sum(s[5:]) > 0 else " "
        m = np.mean([r for _, r in v])
        R.say(f"   {star} {name:10s} 건당 {m:+.2%} 합계 {sum(r for _, r in v) * 100:+6.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+6.0f}만 | 앞 {a:+.2%} 뒤 {b_:+.2%} | 승률 {np.mean([r > 0 for _, r in v]):.0%}")


def pick(df, score, q, k=3, top=1):
    """시점마다 점수 상위 top 중 기준 q 넘는 것, 종목당 하루 1번, 하루 최대 k (시간 순)."""
    d = df.assign(s=score).dropna(subset=["s"])
    d = d[d.s >= q]
    d = d.sort_values(["date", "t", "s"], ascending=[True, True, False])
    d = d.groupby(["date", "t"]).head(top)
    out, seen, cnt = [], set(), defaultdict(int)
    for r in d.itertuples():
        if (r.date, r.code) in seen or cnt[r.date] >= k: continue
        seen.add((r.date, r.code)); cnt[r.date] += 1
        out.append(r)
    return out


def run_trades(rows, title):
    trs = []
    for r in rows:
        x = trade(r.code, r.date, r.t, r.buy)
        if x: trs.append((r.date, x))
    stats(trs, title)
    return trs


def main():
    df = load()
    R.say(f"전체 {len(df):,} 시점·종목, {df.date.nunique()}일, 기준 확률 {df.y.mean():.2%}")
    P = df[(df.ret_prev > -0.05) & (df.ret_prev < 0.05)].copy()
    R.say(f"아직 덜 오른 시점(−5%~+5%) {len(P):,}, 기준 확률 {P.y.mean():.2%}, 60분 최고 평균 {P.mfe60.mean():+.2%}, 15:19 평균 {P.r1519.mean():+.2%}")
    feats = [c for c in df.columns if c not in DROP]
    days = sorted(P.date.unique()); h = days[len(days) // 2]
    A, B = P[P.date < h], P[P.date >= h]

    R.say("\n## 1) 특징 하나씩 구분력 AUC (0.5 = 동전 던지기, 0.5 에서 멀수록 강함) — 앞 / 뒤")
    rows = []
    for f in feats:
        a1, a2 = auc(A.y.values, A[f].values.astype(float)), auc(B.y.values, B[f].values.astype(float))
        rows.append((f, a1, a2))
    R.say(f"  (뒤 칸 = 그 특징 상위 10% / 하위 10% 의 기대 손익 근사, 전체 {P.edge.mean():+.2%})")
    for f, a1, a2 in sorted(rows, key=lambda x: -abs((x[1] + x[2]) / 2 - 0.5)):
        x = P[f].astype(float); hi, lo = x.quantile(0.9), x.quantile(0.1)
        R.say(f"  {f:12s} {a1:.3f} / {a2:.3f} | 상위10% {P.edge[x >= hi].mean():+.2%} 하위10% {P.edge[x <= lo].mean():+.2%}")

    R.say("\n## 2) 묶은 점수 (LightGBM, 달마다 그 전까지만 학습)")
    P["m"] = P.date.map(lambda d: d.strftime("%Y%m"))
    months = sorted(P.m.unique())
    P["score"] = np.nan
    imp = defaultdict(float)
    qs, qs2 = {}, {}
    P["score2"] = np.nan
    for i, m in enumerate(months):
        if i < 3: continue
        tr = P[P.m < m]; te = P.m == m
        mdl = lgb.LGBMClassifier(n_estimators=300, learning_rate=0.03, num_leaves=31, min_child_samples=500,
                                 subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
        mdl.fit(tr[feats], tr.y)
        P.loc[te, "score"] = mdl.predict_proba(P.loc[te, feats])[:, 1]
        m2 = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.03, num_leaves=31, min_child_samples=1000,
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
        m2.fit(tr[feats], tr.edge)
        P.loc[te, "score2"] = m2.predict(P.loc[te, feats])
        st2 = m2.predict(tr[feats].sample(min(len(tr), 300000), random_state=0))
        qs2[m] = {q: np.quantile(st2, q) for q in (0.99, 0.995, 0.999)}
        st = mdl.predict_proba(tr[feats].sample(min(len(tr), 300000), random_state=0))[:, 1]
        qs[m] = {q: np.quantile(st, q) for q in (0.99, 0.995, 0.999)}
        for f, v in zip(feats, mdl.booster_.feature_importance("gain")): imp[f] += v
        R.say(f"  {m}: 학습 {len(tr):,} → 시험 {te.sum():,} AUC {auc(P.loc[te, 'y'].values, P.loc[te, 'score'].values):.3f}")
    T = P.dropna(subset=["score"]).copy()
    R.say(f"  전체 시험 AUC {auc(T.y.values, T.score.values):.3f}")
    R.say("  중요 특징 상위 15: " + ", ".join(f for f, _ in sorted(imp.items(), key=lambda x: -x[1])[:15]))
    for sc, nm in (("score", "확률 모델"), ("score2", "기대 손익 모델")):
        T["dec"] = pd.qcut(T[sc].rank(method="first"), 10, labels=False)
        R.say(f"  {nm} 10분위별 (0 = 낮음) +5% 먼저 확률 · 기대 손익 근사 · 15:19 · 60분 최저:")
        for k, g in T.groupby("dec"):
            R.say(f"   {k}: {g.y.mean():.2%} · {g.edge.mean():+.2%} · {g.r1519.mean():+.2%} · {g.mae60.mean():+.2%}")
    T.to_parquet(os.path.join(OUT, "scored.parquet"))

    R.say("\n## 3) 점수 상위 매수 (실제 1분봉, 다음 봉 시가, 다음 날 09:00)")
    thr = lambda q: T.m.map(lambda m: qs[m][q])
    for q in (0.99, 0.995, 0.999):
        for k in (1, 3):
            rows = pick(T, T.score.where(T.score >= thr(q)), -1, k=k)
            run_trades(rows, f"확률 모델 상위 {1 - q:.1%} · 하루 {k}")
            thr2 = T.m.map(lambda m: qs2[m][q])
            run_trades(pick(T, T.score2.where(T.score2 >= thr2), -1, k=k), f"기대 손익 모델 상위 {1 - q:.1%} · 하루 {k}")

    R.say("\n## 4) 비교 (같은 시험 기간·같은 종목군·같은 매도)")
    rng = np.random.default_rng(0)
    run_trades(pick(T, pd.Series(rng.random(len(T)), index=T.index), 0.999, k=3), "아무 종목 (무작위, 하루 3)")
    run_trades(pick(T, T.acc5.where(T.acc5 >= 5), -1, k=3), "5분 대금 가속 ≥5배 1등 (하루 3)")
    run_trades(pick(T, T.rank_jump.where(T.rank_jump >= 50), -1, k=3), "15분 대금 순위 50계단↑ 1등 (하루 3)")

    # 키움 조회 순위 1분 20위 처음 진입
    dst = os.path.join(tempfile.gettempdir(), "er_screener.duckdb")
    try: shutil.copy(os.path.join(E.DATA, "screener.duckdb"), dst)
    except OSError: pass
    S = duckdb.connect(dst, read_only=True)
    sr = S.execute("""SELECT CAST(ts AS DATE) d, code, min(ts) FROM rank_snapshots WHERE source='search_1m'
                      AND CAST(ts AS TIME) BETWEEN '09:05' AND '14:30' GROUP BY 1, 2""").fetchall()
    first = {(d, c): ts for d, c, ts in sr}
    sdays = sorted({d for d, _ in first})
    R.say(f"  키움 조회 기록 {sdays[0]} ~ {sdays[-1]} ({len(sdays)}일) — 이 기간만 따로 비교")
    TP = T[T.date.isin(sdays)]
    rows = []
    for r in TP.itertuples():
        ts = first.get((r.date, r.code))
        if ts and r.t == -(-(ts.hour * 60 + ts.minute) // 5) * 5:     # 진입 분 이후 첫 5분 시점
            rows.append(r)
    seen = set(); rows = [r for r in rows if not ((r.date, r.code) in seen or seen.add((r.date, r.code)))]
    run_trades(rows, "키움 조회 20위 처음 진입 (덜 오른 종목만)")
    for q in (0.99, 0.995):
        run_trades(pick(TP, TP.score.where(TP.score >= TP.m.map(lambda m: qs[m][q])), -1, k=3), f"확률 모델 상위 {1 - q:.1%} · 하루 3 (같은 기간)")
        thr2 = TP.m.map(lambda m: qs2[m][q])
        run_trades(pick(TP, TP.score2.where(TP.score2 >= thr2), -1, k=3), f"기대 손익 모델 상위 {1 - q:.1%} · 하루 3 (같은 기간)")


if __name__ == "__main__":
    main()
