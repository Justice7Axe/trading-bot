"""상승 직전 연구(early_rise)의 장중 특징·출렁임 예측을 지금 매매(1️⃣2️⃣6️⃣📕☕🔁) 1년 매매 기록에 붙여 거르기 효과 보기 (2026-10-31).
매매 기록: data/strict_select/trades_feat.pkl (신호 시각 t, 수익 ret = 각 매매 규칙 매도). 특징: data/early_rise/feat_*.parquet 의
신호 직전 5분 시점(그 시각까지 끝난 봉만) 값. 학습 점수(scored.parquet)는 −5~+5% 시점·2026-01~ 만 있음.
"""
import glob, os, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
D = r"D:\Ellie\trading\data"
out = open(os.path.join(D, "early_rise", "apply_report.txt"), "w", encoding="utf-8")
def say(s=""): print(s); out.write(s + "\n")
tr = pd.DataFrame(pd.read_pickle(os.path.join(D, "strict_select", "trades_feat.pkl")))
tr = tr[tr.t.notna()].copy()
tr["tm"] = tr.t.map(lambda x: x.hour * 60 + x.minute)
tr["ts"] = ((tr.tm - 1) // 5) * 5            # 신호 분 전에 끝난 5분 시점
cols = ["date", "code", "t", "rng30", "bbw", "acc5", "vwap", "ret_open", "ret_prev", "rsi", "d_range20", "fr1_r", "ins1_r", "crank", "rank_jump", "mcap"]
F = pd.concat((pd.read_parquet(f, columns=cols) for f in glob.glob(os.path.join(D, "early_rise", "feat_*.parquet"))), ignore_index=True)
F["date"] = pd.to_datetime(F.date).dt.date
S = pd.read_parquet(os.path.join(D, "early_rise", "scored.parquet"), columns=["date", "code", "t", "score", "score2"])
S["date"] = pd.to_datetime(S.date).dt.date
m = tr.merge(F, left_on=["date", "code", "ts"], right_on=["date", "code", "t"], how="left", suffixes=("", "_f"))
m = m.merge(S, left_on=["date", "code", "ts"], right_on=["date", "code", "t"], how="left", suffixes=("", "_s"))
say(f"매매 {len(tr):,}건 중 특징 붙은 것 {m.rng30.notna().sum():,} (전날 대금 300위 밖·09:20 전 신호는 빠짐)")
days = sorted(m.date.unique()); h = days[len(days) // 2]
def line(g, nm):
    if len(g) < 20: return f"{nm} {len(g)}건"
    a, b = g[g.date < h].ret.mean(), g[g.date >= h].ret.mean()
    return f"{nm} {len(g)}건 {g.ret.mean():+.2%} (앞 {a:+.2%} 뒤 {b:+.2%}) 합 {g.ret.sum()*100:+.0f}만"
for k, g in m[m.rng30.notna()].groupby("kind"):
    say(f"\n## {k}  전체 {line(g, '')}")
    for f in ("rng30", "bbw", "d_range20", "acc5", "vwap", "rsi", "ret_open", "fr1_r", "ins1_r"):
        x = g[f]
        if x.notna().sum() < 60: continue
        q = pd.qcut(x.rank(method="first"), 3, labels=["낮음", "중간", "높음"])
        say(f"  {f:10s} " + " | ".join(line(gg, str(lab)) for lab, gg in g.groupby(q, observed=True)))
    gs = g[g.score2.notna()]
    if len(gs) >= 60:
        q = pd.qcut(gs.score2.rank(method="first"), 3, labels=["낮음", "중간", "높음"])
        say(f"  기대손익모델 " + " | ".join(line(gg, str(lab)) for lab, gg in gs.groupby(q, observed=True)))
        q = pd.qcut(gs.score.rank(method="first"), 3, labels=["낮음", "중간", "높음"])
        say(f"  확률모델    " + " | ".join(line(gg, str(lab)) for lab, gg in gs.groupby(q, observed=True)))
