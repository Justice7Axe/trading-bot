"""🔺 홍인기 D+ 대장 후보 고르기·체결 연구 — 분석 (build.py 의 data/hong_pick/cands.parquet).

1) 사는 방법 × 파는 방법 기본 성적 (대형·중소형)
2) 홍인기가 그날 실제 매매한 후보(일지) vs 아닌 후보 — 특징 차이·성적
3) 특징 하나씩 셋으로 나눠 성적 (앞·뒤 반 같이)
4) 달마다 다시 학습(LightGBM, 앞 달까지만 학습)해 하루 1~2개 고르기 — 성적·★
5) 10만 계좌 (지금 실전과 함께)
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.research.hong_pick.analyze
  → data/hong_pick/report.txt
"""
import os
import pickle
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

warnings.filterwarnings("ignore")
OUT = os.path.join(E.DATA, "hong_pick")
FEATS = ["small", "t_sig", "chg", "rank", "cv", "accel", "n_mem", "mem_mean", "mem_n15", "mem_rank", "margin", "lmcap", "dist_hi",
         "ma20_pos", "prev_chg", "gap", "pre_chg", "nxt", "kospi", "kosdaq", "frg", "ins", "f_recent", "f_past", "f_quiet", "f_kki",
         "lead_cnt60", "sec_cnt20"]
KOR = dict(small="중소형 대장", t_sig="신호 시각(분)", chg="그 순간 등락률", rank="누적 대금 순위", cv="누적 대금(억)", accel="대금÷20일 평균",
           n_mem="섹터 +5% 동료 수", mem_mean="동료 평균 등락률", mem_n15="동료 +15%↑ 수", mem_rank="동료 평균 대금 순위", margin="2등과 등락률 차이",
           lmcap="시총(log)", dist_hi="250일 고가 대비", ma20_pos="전날 20일선 대비", prev_chg="전날 등락률", gap="시가 갭", pre_chg="프리장 등락",
           nxt="NXT 종목", kospi="코스피 그 시각", kosdaq="코스닥 그 시각", frg="전날 외인", ins="전날 기관", f_recent="최근 강세 섹터",
           f_past="같은 섹터 과거 대장", f_quiet="장대양봉 뒤 2주", f_kki="끼", lead_cnt60="60일 대장 횟수", sec_cnt20="섹터 20일 주도 횟수")


class Rep:
    def __init__(self):
        self.f = open(os.path.join(OUT, "report.txt"), "w", encoding="utf-8")

    def say(self, s=""):
        print(s); self.f.write(str(s) + "\n"); self.f.flush()


R = Rep()


def stat(df, col, title, w=46):
    v = df[["date", col]].dropna()
    if len(v) < 15:
        R.say(f"  {title:{w}s} {len(v)}건 (적음)"); return None
    ds = sorted(v.date.unique()); h = ds[len(ds) // 2]
    a, b = v[v.date < h][col].mean(), v[v.date >= h][col].mean()
    bd = v.groupby("date")[col].sum().sort_values(ascending=False)
    star = "★" if a > 0 and b > 0 and bd.iloc[5:].sum() > 0 else " "
    R.say(f" {star}{title:{w}s} {len(v):4d}건 건당 {v[col].mean():+.2%} (앞 {a:+.2%} 뒤 {b:+.2%}) 승률 {(v[col] > 0).mean():.0%} 최고5일 빼면 {bd.iloc[5:].sum() * 100:+.0f}만")
    return v[col].mean()


def hong_label(df):
    J = pd.read_csv(os.path.join(E.DATA, "hong", "journal_trades.csv"))
    J["date"] = pd.to_datetime(J.date).dt.date
    s = {(r.date, E.code_by_name(r.name)) for r in J.itertuples()}
    return df.apply(lambda r: int((r.date, r.code) in s), axis=1)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    df = pd.read_parquet(os.path.join(OUT, "cands.parquet"))
    df["date"] = pd.to_datetime(df.date).dt.date
    df["hong"] = hong_label(df)
    jd = pd.read_csv(os.path.join(E.DATA, "hong", "journal_trades.csv")).date.pipe(pd.to_datetime).dt.date
    jdays = set(jd)
    R.say(f"후보 {len(df)}건 ({df.date.min()} ~ {df.date.max()}), 대형 {int((df.small == 0).sum())} · 중소형 {int(df.small.sum())}, 홍인기가 그날 매매 {int(df.hong.sum())}")

    R.say("\n## 1) 사는 방법 × 파는 방법 (E1 다음 봉 시가 · E2 −2% 눌림 지정가 · E3 상한가 풀릴 때 / X1 −3%·다음 날 09:00 · X2 손절 없이 09:00 · X3 NXT 08:00 · X4 당일 15:19)")
    for lab, sub in (("대형(대금 20위 대장)", df[df.small == 0]), ("중소형 대장", df[df.small == 1])):
        R.say(f" [{lab}]")
        for e in ("E1", "E2", "E3"):
            for x in ("X1", "X2", "X3", "X4"):
                if f"{e}{x}" in sub:
                    stat(sub, f"{e}{x}", f"{e}{x}")

    R.say("\n## 2) 홍인기가 고른 후보 vs 아닌 후보 (일지 기간 날짜만)")
    sub = df[df.date.isin(jdays)]
    for c in ("E1X1", "E1X2", "E1X3"):
        stat(sub[sub.hong == 1], c, f"그가 고른 것 {c}"); stat(sub[sub.hong == 0], c, f"안 고른 것 {c}")
    R.say("  특징 평균 (고른 것 / 안 고른 것):")
    for f in FEATS:
        a, b = sub[sub.hong == 1][f].mean(), sub[sub.hong == 0][f].mean()
        R.say(f"    {KOR[f]:16s} {a:10.3f} / {b:10.3f}")

    R.say("\n## 3) 특징 하나씩 셋으로 나눠 (E1X1, 대형+중소형) — 많이 나눠 본 것이라 ★ 하나만으로 믿지 말 것")
    for f in FEATS:
        v = df[[f, "E1X1", "date"]].dropna()
        if v[f].nunique() <= 2:
            for val in sorted(v[f].unique()):
                stat(v[v[f] == val], "E1X1", f"{KOR[f]} = {val}")
            continue
        q = pd.qcut(v[f], 3, labels=False, duplicates="drop")
        for k in sorted(q.unique()):
            lo, hi = v[f][q == k].min(), v[f][q == k].max()
            stat(v[q == k], "E1X1", f"{KOR[f]} {lo:.3g}~{hi:.3g}")

    R.say("\n## 4) 달마다 다시 학습 — 하루 1~2개 고르기 (앞 달까지만 학습, 첫 3달은 학습만)")
    import lightgbm as lgb
    df["ym"] = pd.to_datetime(df.date).dt.to_period("M")
    months = sorted(df.ym.unique())
    picks = defaultdict(list)
    for m in months[3:]:
        tr = df[df.ym < m]; te = df[df.ym == m].copy()
        for tgt in ("E1X1", "E1X3"):
            t2 = tr.dropna(subset=[tgt])
            mdl = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                    colsample_bytree=0.8, verbose=-1, random_state=0)
            mdl.fit(t2[FEATS], t2[tgt].clip(-0.15, 0.3))
            te[f"s_{tgt}"] = mdl.predict(te[FEATS])
        th = tr.copy()
        clf = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=20, verbose=-1, random_state=0)
        if th.hong.sum() >= 10:
            clf.fit(th[FEATS], th.hong); te["s_hong"] = clf.predict_proba(te[FEATS])[:, 1]
        else:
            te["s_hong"] = np.nan
        for _, g in te.groupby("date"):
            for sc, tgt in (("s_E1X1", "E1X1"), ("s_E1X3", "E1X3"), ("s_hong", "E1X1"), ("s_hong", "E1X3")):
                gg = g.dropna(subset=[tgt]).sort_values(sc, ascending=False)
                for k in (1, 2):
                    for _, r in gg.head(k).iterrows():
                        picks[(sc, tgt, k)].append(r)
                gp = gg[gg[sc] > 0] if sc.startswith("s_E") else gg[gg[sc] >= 0.3]
                for _, r in gp.head(1).iterrows():
                    picks[(sc, tgt, "기준 넘을 때 1")].append(r)
    test = df[df.ym >= months[3]]
    stat(test, "E1X1", "비교: 시험 기간 후보 전부 E1X1"); stat(test, "E1X3", "비교: 시험 기간 후보 전부 E1X3")
    for key, rows in picks.items():
        sc, tgt, k = key
        stat(pd.DataFrame(rows), tgt, f"{ {'s_E1X1': '수익 모델(X1)', 's_E1X3': '수익 모델(X3)', 's_hong': '홍인기 닮은 모델'}[sc]} → {tgt} · 하루 {k}")
    pickle.dump(dict(picks), open(os.path.join(OUT, "picks.pkl"), "wb"))


if __name__ == "__main__":
    main()
