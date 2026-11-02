r"""장 초 고점 눌림 재돌파가 수익을 주는 전제 조건 찾기 (2026-11-03 사용자: '거꾸로 재돌파가 수익을 주는 전제 조건은 뭐가 있는지').

자료: bt.py 의 전날 대금 30위 재돌파 매매 (기본 10분·−1.5%, data/open_pullback_break/trades.parquet).
결과: C 손절(눌림 저가)만·다음 날 09:00 (이 매수 자리에 가장 맞는 매도) · A 역배열 매도.
조건 (매수 순간까지 알 수 있는 것만): 코스피·코스닥 그 시각 등락, 시장 20일선, 그 종목 전날 등락·시가 갭·매수가 등락,
  250일 고가 대비, 20일선 대비, 눌림 깊이, 매수 시각, 전날 대금 순위, 시총, 전날 외인·기관, 그날 그 시각까지 주도 섹터 대장이었나(hong_pick 후보),
  장 초 고점 H0 의 등락률, 그 종목 그 시각 누적 대금 순위는 못 구해서 뺌.
방법: ① 조건 하나씩 셋으로 나눠 (앞·뒤 반 모두 + 인 칸만 표시) ② 둘 묶기 상위 ③ 달마다 다시 학습한 모델로 고르기(앞 3달 학습만).
여러 칸을 본 것이라 우연히 좋아 보이는 칸이 섞임 → 뒤 반(하반기)만으로 다시 확인한 것, 모델의 처음 보는 달 성적을 함께 봄.
실행: PYTHONIOENCODING=utf-8 PYTHONPATH=D:\\Ellie\\trading .venv\\Scripts\\python.exe -m kiwoom_trading.research.open_pullback_break.conditions
  → data/open_pullback_break/conditions.txt
"""
import itertools
import os
import sys
import warnings
from datetime import datetime, time

import numpy as np
import pandas as pd

from kiwoom_trading.backtest import engine as E

warnings.filterwarnings("ignore")
OUT = os.path.join(E.DATA, "open_pullback_break")
_IX = {}


def idx_at(code, d, t):
    if (code, d) not in _IX:
        rows = E.IX.execute("SELECT ts, close FROM idx_min WHERE code=? AND ts >= ? AND ts < ? ORDER BY ts",
                            [code, datetime.combine(d, time(9, 0)), datetime.combine(d, time(15, 31))]).fetchall()
        _IX[(code, d)] = [(r[0].time(), r[1]) for r in rows]
    xs = [c for tt, c in _IX[(code, d)] if tt < t]
    return xs[-1] if xs else np.nan


IDXC = {c: dict(E.IX.execute("SELECT date, close FROM idx_daily WHERE code=?", [c]).fetchall()) for c in ("001", "101")}
KOR = dict(kospi="코스피 매수 시각 등락", kosdaq="코스닥 매수 시각 등락", prev_chg="전날 등락률", gap="시가 갭", buy_chg="매수가 등락률",
           h0_chg="장 초 고점 등락률", dist_hi="250일 고가 대비", ma20="20일선 대비", depth="눌림 깊이", tmin="매수 시각(분)", prank="전날 대금 순위",
           lmcap="시총(log)", frg="전날 외인(억)", ins="전날 기관(억)", leader="그 시각 주도 섹터 대장", mkt_up="시장 20일선 위")


def features(df):
    try:
        cand = pd.read_parquet(os.path.join(E.DATA, "hong_pick", "cands.parquet"))
        cand["date"] = pd.to_datetime(cand.date).dt.date
        lead = {(r.date, r.code): r.t_sig for r in cand.itertuples()}
    except Exception:
        lead = {}
    out = []
    for r in df.itertuples():
        d, c = r.date, r.code; p = E.prev_day(d)
        dd, pdd = E.daily_day(d), E.daily_day(p)
        f = E.factor(c, d)
        if c not in pdd or not f:
            continue
        pc = pdd[c][3] * f
        reg = E.regular(E.bars(c, d))
        hi = E.hi_n(c, d, 250); m20 = E.ma_n(c, d, 20); iv = E.inv(c, p)
        tm = r.t.hour * 60 + r.t.minute - 540
        kp, kq = IDXC["001"].get(p), IDXC["101"].get(p)
        ls = lead.get((d, c))
        out.append(dict(date=d, code=c, A=r.A, C=r.C, mkt_up=int(r.mkt != "둘 다 20일선 아래"),
                        kospi=idx_at("001", d, r.t) / kp - 1 if kp else np.nan, kosdaq=idx_at("101", d, r.t) / kq - 1 if kq else np.nan,
                        prev_chg=E.chg(c, p), gap=reg[0][1] / pc - 1, buy_chg=r.buy / pc - 1, h0_chg=r.h0 / pc - 1,
                        dist_hi=(r.buy / f) / hi - 1 if hi else np.nan, ma20=(pdd[c][3] / m20 - 1) if m20 else np.nan,
                        depth=r.stop / r.h0 - 1, tmin=tm, prank=E.value_rank(p).get(c), lmcap=np.log10(E.mcap(c, p) or 1),
                        frg=(iv[0] / 1e8 if iv else np.nan), ins=(iv[1] / 1e8 if iv else np.nan),
                        leader=int(ls is not None and ls <= tm)))
    return pd.DataFrame(out)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rp = E.Report.__new__(E.Report); rp.f = open(os.path.join(OUT, "conditions.txt" if "--four" not in sys.argv else "conditions_four.txt"), "w", encoding="utf-8")
    four = "--four" in sys.argv          # 2026-11-03 사용자 '대상 종목을 4개 종목으로 한정해서'
    if four:
        from kiwoom_trading.strategies.hong_styles.backtest import MKT
        df = pd.read_parquet(os.path.join(OUT, "four.parquet")); df = df[df.entry].copy()
        df["date"] = pd.to_datetime(df.date).dt.date; df["t"] = df.t_buy; df["mkt"] = df.date.map(MKT)
        rp.f = open(os.path.join(OUT, "conditions_four.txt"), "w", encoding="utf-8")
        rp.say("[검증된 4종목만: SK하이닉스·삼성전자·한미반도체·제주반도체]")
    else:
        df = pd.read_parquet(os.path.join(OUT, "trades.parquet")); df["date"] = pd.to_datetime(df.date).dt.date
    X = features(df)
    X.to_parquet(os.path.join(OUT, "conditions_four.parquet" if four else "conditions.parquet"))
    MINN = 30 if four else 60
    ds = sorted(X.date.unique()); h = ds[len(ds) // 2]
    rp.say(f"재돌파 {len(X)}건 ({ds[0]} ~ {ds[-1]}), 반 나눔 {h} — 기준: C 손절만·다음 날 09:00 {X.C.mean():+.2%} / A 역배열 {X.A.mean():+.2%}")
    feats = list(KOR)
    cells = []
    rp.say("\n## ① 조건 하나씩 (셋으로 나눔) — C 건당 · 앞 / 뒤 · 건수")
    for fe in feats:
        v = X[[fe, "C", "A", "date"]].dropna()
        if v[fe].nunique() <= 2:
            bins = {f"= {int(k)}": v[fe] == k for k in sorted(v[fe].unique())}
        else:
            q = pd.qcut(v[fe], 3, labels=False, duplicates="drop")
            bins = {f"{v[fe][q == k].min():.3g}~{v[fe][q == k].max():.3g}": q == k for k in sorted(q.unique())}
        line = []
        for lab, m in bins.items():
            g = v[m]; a, b = g[g.date < h].C.mean(), g[g.date >= h].C.mean()
            mark = "✔" if a > 0 and b > 0 else " "
            line.append(f"{mark}{lab}: {g.C.mean():+.2%} ({a:+.2%}/{b:+.2%}) {len(g)}건")
            cells.append((fe, lab, m, g))
        rp.say(f"  {KOR[fe]:14s} " + " | ".join(line))

    rp.say("\n## ② 둘 묶기 — 앞·뒤 반 모두 + · 60건↑ · C 건당 상위 15")
    combos = []
    for (f1, l1, m1, g1), (f2, l2, m2, g2) in itertools.combinations(cells, 2):
        if f1 == f2:
            continue
        idx = g1.index.intersection(g2.index)
        if len(idx) < MINN:
            continue
        g = X.loc[idx]; a, b = g[g.date < h].C.mean(), g[g.date >= h].C.mean()
        if a > 0 and b > 0:
            combos.append((g.C.mean(), f"{KOR[f1]} {l1} & {KOR[f2]} {l2}", g))
    for mean, lab, g in sorted(combos, key=lambda x: -x[0])[:15]:
        rp.stats([(r.date, r.C) for r in g.itertuples()], lab, 70)

    rp.say("\n## ③ 달마다 다시 학습 (LightGBM, 앞 달까지만 학습) — 처음 보는 달 성적")
    import lightgbm as lgb
    X["ym"] = pd.to_datetime(X.date).dt.to_period("M")
    months = sorted(X.ym.unique()); picks = []
    for m in months[3:]:
        tr = X[X.ym < m].dropna(subset=["C"]); te = X[X.ym == m].copy()
        mdl = lgb.LGBMRegressor(n_estimators=200, learning_rate=0.03, num_leaves=15, min_child_samples=30, subsample=0.8, subsample_freq=1,
                                colsample_bytree=0.8, verbose=-1, random_state=0)
        mdl.fit(tr[feats], tr.C.clip(-0.1, 0.15)); te["s"] = mdl.predict(te[feats]); picks.append(te)
    P = pd.concat(picks)
    rp.stats([(r.date, r.C) for r in P.itertuples() if r.C == r.C], "비교: 시험 기간 전부")
    for th in (0.0, 0.005, 0.01):
        g = P[P.s > th]
        rp.stats([(r.date, r.C) for r in g.itertuples() if r.C == r.C], f"모델 점수 > {th:.1%}")
    imp = pd.Series(mdl.feature_importances_, index=feats).sort_values(ascending=False)
    rp.say("  모델이 많이 쓴 조건: " + ", ".join(f"{KOR[k]}" for k in imp.index[:6]))


if __name__ == "__main__":
    main()
