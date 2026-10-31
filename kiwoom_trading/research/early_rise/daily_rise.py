"""상승 직전 종목 찾기 2 — 일봉 기준 '며칠 안에 오를 종목' (2026-10-31, 1분봉 60분 버전은 우위 없음 → build/analyze 참고).

D 장 마감 뒤 아는 일봉·대금·수급·지표로 점수 → D+1 시가 매수 → 일봉으로 매도:
  손절가 먼저(갭으로 이미 아래면 시가), 그다음 익절가, 못 닿으면 보유 기간 끝난 다음 날 시가 (종가 매도 안 함), 비용 0.25%.
표본: 그날 대금 500위 안 주식(우선주 제외), 종가 1,000원↑, 상한가 마감 제외, D+1 시가 갭 +29%↑ 제외.
자료: 일봉 2024-10-11~ (engine.daily_day, 9-14 뒤는 1분봉 있는 종목만 정규장 값), 수급 investor_daily, 코스피 idx_daily.
학습: LightGBM 달마다 그 전 달까지만(결과가 확정된 날까지만) → 2025-07 부터 처음 보는 자료로 평가.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe kiwoom_trading/research/early_rise/daily_rise.py
"""
import os, sys
from collections import defaultdict
from datetime import date
import lightgbm as lgb
import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "early_rise"); os.makedirs(OUT, exist_ok=True)
TEST0 = "202507"
EXITS = {"+10/−5 · 5일": (0.10, 0.05, 5), "익절 없음/−7 · 5일": (None, 0.07, 5), "+5/−3 · 3일": (0.05, 0.03, 3),
         "다음 날 시가 (1일)": (None, None, 1), "익절 없음/−10 · 10일": (None, 0.10, 10)}
MAIN = "+10/−5 · 5일"


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


PROG = os.environ.get("EARLY_PROG") == "1"     # 일별 프로그램 매매(program_daily, 2026-11-01 백필) 특징 넣기
R = Rep("daily_report_prog.txt" if PROG else "daily_report.txt")


def auc(y, s):
    m = ~np.isnan(s); y, s = y[m], s[m]
    if y.sum() == 0 or y.sum() == len(y): return np.nan
    r = pd.Series(s).rank().values
    return (r[y == 1].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (len(y) - y.sum()))


def panel():
    rows = []
    for d in E.CAL:
        for c, r in E.daily_day(d).items():
            if E.is_common(c): rows.append((d, c, *r))
    df = pd.DataFrame(rows, columns=["date", "code", "o", "h", "l", "c", "v", "val"])
    return df.sort_values(["code", "date"]).reset_index(drop=True)


def exits(o, h, l, i):
    """i = D 의 위치(같은 종목 배열 안). D+1 시가 매수 → EXITS 별 수익 (없으면 nan)."""
    out = {}
    n = len(o)
    if i + 1 >= n: return {k: np.nan for k in EXITS}
    buy = o[i + 1]
    for name, (tp, sl, H) in EXITS.items():
        r = np.nan
        if i + H + 1 < n:
            sp = buy * (1 - sl) if sl else None; tpp = buy * (1 + tp) if tp else None
            for k in range(i + 1, i + H + 1):
                if sp and l[k] <= sp:
                    r = (min(o[k], sp) if k > i + 1 else sp) / buy - 1; break
                if tpp and h[k] >= tpp:
                    r = (max(o[k], tpp) if k > i + 1 else tpp) / buy - 1; break
            if np.isnan(r): r = o[i + H + 1] / buy - 1
            r -= E.COST
        out[name] = r
    return out


def features(df):
    kospi = pd.Series(E.KOSPI).sort_index(); kospi.index = pd.to_datetime(kospi.index)
    kf = pd.DataFrame({"k_chg1": kospi.pct_change(), "k_chg5": kospi.pct_change(5), "k_ma20": kospi / kospi.rolling(20).mean() - 1})
    out = []
    for c, g in df.groupby("code", sort=False):
        if len(g) < 70: continue
        o, h, l, cl, val = (g[k].astype(float).values for k in ("o", "h", "l", "c", "val"))
        s = pd.Series(cl)
        f = pd.DataFrame({"date": g.date.values, "code": c})
        f["chg1"] = s.pct_change().values; f["chg3"] = s.pct_change(3).values; f["chg5"] = s.pct_change(5).values; f["chg20"] = s.pct_change(20).values
        for n in (5, 10, 20, 60):
            f[f"ma{n}"] = (s / s.rolling(n).mean() - 1).values
        f["ma20_slope"] = (s.rolling(20).mean().pct_change(5)).values
        f["hi60"] = (s / pd.Series(h).rolling(60).max() - 1).values
        f["hi120"] = (s / pd.Series(h).rolling(120, min_periods=60).max() - 1).values
        f["lo20"] = (s / pd.Series(l).rolling(20).min() - 1).values
        m20, s20 = s.rolling(20).mean(), s.rolling(20).std()
        bbw = 4 * s20 / m20
        f["bbw"] = bbw.values; f["bbw_rel"] = (bbw / bbw.rolling(60).min()).values; f["bbp"] = ((s - (m20 - 2 * s20)) / (4 * s20)).values
        dl = s.diff(); up = dl.clip(lower=0).ewm(alpha=1 / 14).mean(); dn = (-dl.clip(upper=0)).ewm(alpha=1 / 14).mean()
        f["rsi"] = (100 - 100 / (1 + up / dn)).values
        macd = s.ewm(span=12).mean() - s.ewm(span=26).mean(); hist = macd - macd.ewm(span=9).mean()
        f["macdh"] = (hist / s).values; f["macdh_d"] = ((hist - hist.shift(3)) / s).values
        f["macd_cross"] = ((hist > 0) & (hist.shift(1) <= 0)).astype(float).values
        rng = (h - l); f["body"] = (cl - o) / np.where(rng > 0, rng, np.nan); f["close_pos"] = (cl - l) / np.where(rng > 0, rng, np.nan)
        f["upper_wick"] = (h - np.maximum(o, cl)) / np.where(rng > 0, rng, np.nan)
        f["range1"] = rng / cl; f["range20"] = (pd.Series(h).rolling(20).max() / pd.Series(l).rolling(20).min() - 1).values
        vs = pd.Series(val)
        f["val"] = val; f["valr5"] = (vs / vs.rolling(5).mean().shift(1)).values; f["valr20"] = (vs / vs.rolling(20).mean().shift(1)).values
        f["val3r20"] = (vs.rolling(3).mean() / vs.rolling(20).mean().shift(3)).values
        f["upstreak"] = pd.Series((cl > np.r_[np.nan, cl[:-1]]).astype(int)).groupby((pd.Series(cl) <= pd.Series(cl).shift()).cumsum()).cumsum().values
        f["mcap"] = np.log10(np.maximum((E.SHARES.get(c) or 0) * cl, 1))
        f["close"] = cl
        ex = [exits(o, h, l, i) for i in range(len(g))]
        for k in EXITS: f["r_" + k] = [x[k] for x in ex]
        f["gap_next"] = np.r_[o[1:] / cl[:-1] - 1, np.nan]
        out.append(f)
    X = pd.concat(out, ignore_index=True)
    fl = pd.DataFrame(E.DM.execute("SELECT code, date, foreign_, institution, individual FROM investor_daily").fetchall(),
                      columns=["code", "date", "fr", "ins", "ind"]).sort_values(["code", "date"])
    for k in ("fr", "ins", "ind"):
        fl[k + "5"] = fl.groupby("code")[k].transform(lambda x: x.rolling(5).sum())
        fl[k + "20"] = fl.groupby("code")[k].transform(lambda x: x.rolling(20).sum())
    fl["ins_streak"] = fl.groupby("code").ins.transform(lambda x: (x > 0).astype(int).groupby((x <= 0).cumsum()).cumsum())
    fl["fr_streak"] = fl.groupby("code").fr.transform(lambda x: (x > 0).astype(int).groupby((x <= 0).cumsum()).cumsum())
    X = X.merge(fl, on=["code", "date"], how="left")
    for k in ("fr", "ins", "ind", "fr5", "ins5", "ind5", "fr20", "ins20", "ind20"):
        X[k + "_r"] = X[k] / X.val
    if PROG:
        import duckdb
        pc = duckdb.connect(os.path.join(E.DATA, "program_daily.duckdb"), read_only=True)
        pg = pd.DataFrame(pc.execute("SELECT code, date, buy_amt, sell_amt, net_amt FROM program_daily").fetchall(),
                          columns=["code", "date", "pbuy", "psell", "pnet"]).sort_values(["code", "date"])
        pc.close()
        for k in ("pbuy", "psell", "pnet"):
            pg[k] = pg[k].astype(float) * 1e6     # 백만 원 → 원
        gp = pg.groupby("code")
        pg["pnet5"] = gp.pnet.transform(lambda x: x.rolling(5).sum())
        pg["pnet20"] = gp.pnet.transform(lambda x: x.rolling(20).sum())
        pb5 = gp.pbuy.transform(lambda x: x.rolling(5).sum()); ps5 = gp.psell.transform(lambda x: x.rolling(5).sum())
        pg["pg_share5"] = pb5 / (pb5 + ps5)
        pg["pg_streak"] = gp.pnet.transform(lambda x: (x > 0).astype(int).groupby((x <= 0).cumsum()).cumsum())
        X = X.merge(pg[["code", "date", "pnet", "pnet5", "pnet20", "pg_streak", "pg_share5"]], on=["code", "date"], how="left")
        vs5 = X.groupby("code").val.transform(lambda x: x.rolling(5).sum())
        vs20 = X.groupby("code").val.transform(lambda x: x.rolling(20).sum())
        X["pg1_r"] = X.pnet / X.val; X["pg5_r"] = X.pnet5 / vs5; X["pg20_r"] = X.pnet20 / vs20
        X["pg_quiet"] = X.pg5_r - X.chg5          # 가격 변화보다 프로그램이 먼저 쌓인 정도
    X["date"] = pd.to_datetime(X.date)
    X = X.merge(kf, left_on="date", right_index=True, how="left")
    X["vrank"] = X.groupby("date").val.rank(ascending=False)
    X["vrank5"] = X.groupby("code").vrank.transform(lambda x: x.shift(1).rolling(5).mean())
    X["vrank_jump"] = X.vrank5 - X.vrank
    X["breadth"] = X.groupby("date").chg1.transform(lambda x: (x > 0).mean())
    X["rel1"] = X.chg1 - X.groupby("date").chg1.transform("median")
    X["rel5"] = X.chg5 - X.groupby("date").chg5.transform("median")
    X = X.replace([np.inf, -np.inf], np.nan)
    return X


RAW = {"date", "code", "close", "val", "pnet", "pnet5", "pnet20", "fr", "ins", "ind", "fr5", "ins5", "ind5", "fr20", "ins20", "ind20", "gap_next", "m", "y", "score", "score2"}


def stats(trs, title):
    """trs = DataFrame(date, r_*) 매수 목록."""
    if len(trs) < 15:
        R.say(f"  {title}: {len(trs)}건 (적음)"); return None
    ds = sorted(trs.date.unique()); h = ds[len(ds) // 2]
    R.say(f"  {title}: {len(trs)}건 {len(ds)}일")
    res = {}
    for name in EXITS:
        v = trs[["date", "r_" + name]].dropna()
        x = v["r_" + name]
        a, b = x[v.date < h].mean(), x[v.date >= h].mean()
        bd = v.groupby("date")["r_" + name].sum().sort_values(ascending=False)
        star = "★" if a > 0 and b > 0 and bd.iloc[5:].sum() > 0 else " "
        R.say(f"   {star} {name:16s} 건당 {x.mean():+.2%} 합계 {x.sum() * 100:+6.0f}만 최고5일 빼면 {bd.iloc[5:].sum() * 100:+6.0f}만 | 앞 {a:+.2%} 뒤 {b:+.2%} | 승률 {(x > 0).mean():.0%}")
        res[name] = (x.mean(), a, b, star)
    return res


def top_k(T, col, k):
    """그날 점수 상위 k 를 먼저 고르고, 다음 날 상한가(+29.5%↑)로 시작해 못 사는 것은 매매 없음 (다음 순위로 채우지 않음)."""
    t = T.dropna(subset=[col]).sort_values(["date", col], ascending=[True, False]).groupby("date").head(k)
    return t[t.gap_next < 0.295]


def main():
    df = panel()
    X = features(df)
    U = X[(X.vrank <= 500) & (X.close >= 1000) & (X.chg1 < 0.295)].copy()   # 다음 날 갭으로 미리 거르지 않음 (검토 지적: 미래 정보) — 고른 뒤 상한가 시작이면 못 산 것으로
    U = U[U.date >= pd.Timestamp("2025-01-02")].dropna(subset=["r_" + MAIN])
    U["m"] = U.date.dt.strftime("%Y%m")
    U["y"] = (U["r_" + MAIN] > 0.09).astype(int)
    feats = [c for c in U.columns if c not in RAW and not c.startswith("r_")]
    R.say(f"표본 {len(U):,} (종목·일), {U.date.nunique()}일, 특징 {len(feats)}개: {', '.join(feats)}")
    R.say(f"전체 평균: " + " · ".join(f"{k} {U['r_' + k].mean():+.2%}" for k in EXITS))

    R.say("\n## 1) 특징 하나씩 — 상위 10% / 하위 10% 의 건당 수익 (" + MAIN + "), 앞·뒤 반")
    days = sorted(U.date.unique()); hh = days[len(days) // 2]
    rows = []
    for f in feats:
        x = U[f]; hi, lo = x.quantile(0.9), x.quantile(0.1)
        top, bot = U[x >= hi], U[x <= lo]
        rows.append((f, top["r_" + MAIN].mean(), bot["r_" + MAIN].mean(),
                     top[top.date < hh]["r_" + MAIN].mean(), top[top.date >= hh]["r_" + MAIN].mean()))
    for f, t, b, ta, tb in sorted(rows, key=lambda r: -max(r[1], r[2])):
        R.say(f"  {f:12s} 상위 {t:+.2%} (앞 {ta:+.2%} 뒤 {tb:+.2%}) · 하위 {b:+.2%}")

    R.say("\n## 2) LightGBM 달마다 (그 전 달까지 결과 확정된 자료만 학습)")
    months = sorted(U.m.unique())
    U["score"] = np.nan; U["score2"] = np.nan
    imp = defaultdict(float)
    for m in months:
        if m < TEST0: continue
        first = pd.Timestamp(m[:4] + "-" + m[4:] + "-01")
        # 보유 최대 10일 → 학습 자료는 시험 달 시작 15 거래일 전까지만 (결과가 시험 달에 걸리지 않게)
        cut = [d for d in days if d < first]
        cut = cut[-15] if len(cut) > 15 else cut[0]
        tr = U[(U.date < cut) & (U.gap_next < 0.295)]; te = U.m == m
        m1 = lgb.LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=300,
                               subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
        m1.fit(tr[feats], tr["r_" + MAIN].clip(-0.1, 0.12))
        U.loc[te, "score"] = m1.predict(U.loc[te, feats])
        m2 = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=300,
                                subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
        m2.fit(tr[feats], tr.y)
        U.loc[te, "score2"] = m2.predict_proba(U.loc[te, feats])[:, 1]
        for f, v in zip(feats, m1.booster_.feature_importance("gain")): imp[f] += v
        R.say(f"  {m}: 학습 {len(tr):,} → 시험 {te.sum():,} · 익절 맞히기 AUC {auc(U.loc[te, 'y'].values, U.loc[te, 'score2'].values):.3f}")
    T = U.dropna(subset=["score"]).copy()
    R.say("  중요 특징 상위 15 (수익 모델): " + ", ".join(f for f, _ in sorted(imp.items(), key=lambda x: -x[1])[:15]))
    for sc, nm in (("score", "수익 모델"), ("score2", "익절 확률 모델")):
        T["dec"] = pd.qcut(T[sc].rank(method="first"), 10, labels=False)
        R.say(f"  {nm} 10분위 (0 = 낮음) 건당 {MAIN}:  " + " · ".join(f"{k}:{g['r_' + MAIN].mean():+.2%}" for k, g in T.groupby("dec")))
    T.to_parquet(os.path.join(OUT, "daily_scored.parquet"))

    R.say("\n## 3) 점수 상위 매수 (D+1 시가, 하루 k 종목)")
    for sc, nm in (("score", "수익 모델"), ("score2", "익절 확률 모델")):
        for k in (1, 3, 5):
            stats(top_k(T, sc, k), f"{nm} 하루 {k}")

    R.say("\n## 4) 비교 (같은 기간)")
    rng = np.random.default_rng(0)
    stats(T.assign(rr=rng.random(len(T))).pipe(top_k, "rr", 3), "아무 종목 (무작위, 하루 3)")
    stats(top_k(T[T.chg1 > 0].assign(nv=-T.vrank), "nv", 3), "대금 3위 안·상승 마감 (종가배팅 비슷, 하루 3)")
    stats(top_k(T.assign(vj=T.vrank_jump), "vj", 3), "대금 순위 급상승 1~3등 (하루 3)")
    stats(top_k(T[(T.bbw_rel < 1.2) & (T.valr20 > 2) & (T.chg1 > 0)].assign(v2=T.valr20), "v2", 3), "볼린저 좁음 + 대금 2배↑ + 상승 (하루 3)")
    if PROG:
        R.say("\n## 4-1) 프로그램 규칙 (하루 3, 같은 기간) — 가격은 덜 움직였는데 프로그램이 먼저 쌓인 종목")
        Q = T[T.pg5_r.notna()]
        R.say(f"  프로그램 자료 있는 줄 {len(Q):,} / {len(T):,}")
        x = Q.pg5_r; hi, lo = x.quantile(0.9), x.quantile(0.1)
        R.say(f"  5일 프로그램 순매수 비율 상위 10% {Q[x >= hi]['r_' + MAIN].mean():+.2%} · 하위 10% {Q[x <= lo]['r_' + MAIN].mean():+.2%} · 전체 {Q['r_' + MAIN].mean():+.2%}")
        stats(top_k(Q.assign(rr=np.random.default_rng(0).random(len(Q))), "rr", 3), "(비교) 프로그램 자료 있는 종목 무작위 3")
        quiet = Q.chg5.abs() < 0.03
        stats(top_k(Q[quiet].assign(z=Q.pg5_r), "z", 3), "5일 가격 ±3% 안 & 5일 프로그램 순매수 비율 1~3등")
        stats(top_k(Q[quiet & (Q.pg_streak >= 3)].assign(z=Q.pg5_r), "z", 3), "  + 3일 연속 프로그램 순매수")
        stats(top_k(Q.assign(z=Q.pg_quiet), "z", 3), "프로그램 쌓임 − 가격 변화 1~3등")
        stats(top_k(Q[Q.mcap >= 12].assign(z=Q.pg5_r), "z", 3), "시총 1조↑ 5일 프로그램 순매수 비율 1~3등")
        stats(top_k(Q[quiet & (Q.pg5_r > 0) & (Q.fr5_r > 0) & (Q.ins5_r > 0)].assign(z=Q.pg5_r), "z", 3), "5일 가격 ±3% & 프로그램·외인·기관 5일 모두 + (프로그램 1~3등)")
        for nm, mk in (("코스피 20일선 위", Q.k_ma20 >= 0), ("코스피 20일선 아래", Q.k_ma20 < 0)):
            stats(top_k(Q[mk & quiet].assign(z=Q.pg5_r), "z", 3), f"[{nm}] 5일 가격 ±3% & 프로그램 1~3등")

    R.say("\n## 5) 시장 상황별 (수익 모델 하루 3, 코스피 20일선 위/아래)")
    t3 = top_k(T, "score", 3)
    stats(t3[t3.k_ma20 >= 0], "코스피 20일선 위")
    stats(t3[t3.k_ma20 < 0], "코스피 20일선 아래")
    R.say("\n## 6) 달별 (수익 모델 하루 3, " + MAIN + ")")
    R.say("  " + " · ".join(f"{m}:{g['r_' + MAIN].mean():+.2%}({len(g)})" for m, g in t3.groupby("m")))


if __name__ == "__main__":
    main()
