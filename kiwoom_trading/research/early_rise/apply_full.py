"""지금 매매 1년 기록 전체(trades_feat.pkl 7,566건)에 신호 순간 1분봉 특징(VWAP 대비·5분 대금 가속·30분 출렁임·시가 대비)을 붙여
'추격 순간 피하기' 거르기 효과 확인 (2026-10-31, early_rise 연구 후속). 신호 분 전에 끝난 봉까지만 씀."""
import os, sys
from datetime import time
import numpy as np, pandas as pd
from kiwoom_trading.backtest import engine as E
sys.stdout.reconfigure(encoding="utf-8")
out = open(os.path.join(E.DATA, "early_rise", "apply_full.txt"), "w", encoding="utf-8")
def say(s=""): print(s); out.write(s + "\n"); out.flush()
tr = pd.DataFrame(pd.read_pickle(os.path.join(E.DATA, "strict_select", "trades_feat.pkl")))
tr = tr[tr.t.notna()].copy()
rows = []
for r in tr.itertuples():
    b = [x for x in E.bars(r.code, r.date) if time(9, 0) <= x[0] < r.t]
    if len(b) < 3: rows.append((np.nan,) * 4); continue
    c = np.array([x[4] for x in b], float); v = np.array([x[5] for x in b], float); h = np.array([x[2] for x in b], float); l = np.array([x[3] for x in b], float)
    val = c * v; vwap = val.sum() / max(v.sum(), 1)
    a5 = val[-5:].sum(); base = val[-35:-5].mean() * 5 if len(val) > 10 else np.nan
    rows.append((r.px / vwap - 1, a5 / base if base and base > 0 else np.nan, h[-30:].max() / l[-30:].min() - 1, r.px / b[0][1] - 1))
tr[["vwap", "acc5", "rng30", "ret_open"]] = rows
days = sorted(tr.date.unique()); hh = days[len(days) // 2]
def line(g, nm):
    if len(g) < 20: return f"{nm} {len(g)}건"
    a, b = g[g.date < hh].ret.mean(), g[g.date >= hh].ret.mean()
    return f"{nm} {len(g)}건 {g.ret.mean():+.2%} (앞 {a:+.2%} 뒤 {b:+.2%})"
say(f"매매 {len(tr):,}건, 특징 붙은 것 {tr.vwap.notna().sum():,}")
for k, g in tr.groupby("kind"):
    g = g[g.vwap.notna()]
    say(f"\n## {k}  {line(g, '전체')}  합 {g.ret.sum()*100:+.0f}만")
    for f in ("vwap", "acc5", "rng30", "ret_open"):
        x = g[f]
        if x.notna().sum() < 60: continue
        q = pd.qcut(x.rank(method="first"), 3, labels=["낮음", "중간", "높음"])
        say(f"  {f:8s} " + " | ".join(line(gg, str(lab)) for lab, gg in g.groupby(q, observed=True)) + f"  (경계 {x.quantile(1/3):+.3f} / {x.quantile(2/3):+.3f})")
tr.to_pickle(os.path.join(E.DATA, "early_rise", "trades_signal_feat.pkl"))
