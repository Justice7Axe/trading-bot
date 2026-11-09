"""저돌 후보 계좌 모의: 100만 원 시작, 하루 첫 신호 1종목(또는 2종목 나눠서) 전액, 장 전 조건(코스피 52주 고점 −10% 안 & 전날 20일선 위).
    .venv/Scripts/python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_jeodol_account.py --kang-cached
"""
import os, pickle, sys
from collections import defaultdict
import duckdb, numpy as np
sys.path.insert(0, os.path.dirname(__file__))
import yoonta_minute_bt as Y  # noqa: E402

TR = pickle.load(open(os.path.join(Y.OUT, "jeodol_trades.pkl"), "rb"))
ix = duckdb.connect(Y._copy("index.duckdb"), read_only=True)
rows = ix.execute("SELECT date, close FROM idx_daily WHERE code='001' ORDER BY date").fetchall()
dates = [d for d, _ in rows]; cl = np.array([c for _, c in rows], float)
OK = {d: cl[i - 1] >= 0.9 * cl[i - 250:i].max() and cl[i - 1] >= cl[i - 20:i].mean() for i, d in enumerate(dates) if i >= 250}
for rn in ("r20", "r60"):
    for s, t in ((0.03, 0.05), (0.03, 0.10), (0.04, 0.10)):
        by = defaultdict(list)
        for x in TR[(rn, s, t)]:
            if OK.get(x[0]):
                by[x[0]].append((x[5], x[1]))
        for k in (1, 2, 3):
            eq = 1.0; curve = []; months = defaultdict(float)
            for d in sorted(by):
                v = [r for _, r in sorted(by[d])[:k]]
                day = np.mean(v)
                eq *= 1 + day; curve.append(eq); months[d.strftime("%Y-%m")] += day
            c = np.array(curve); mdd = (1 - c / np.maximum.accumulate(c)).max()
            print(f"{'20일' if rn == 'r20' else '60일'} −{s:.0%}/+{t:.0%} 하루 앞 {k}종목 나눠 매수: {len(by)}일 · 100만 → {eq * 100:.0f}만 (최대 낙폭 {mdd:.0%})"
                  f" | 월별 {' '.join(f'{m[2:]}:{v * 100:+.0f}%' for m, v in sorted(months.items()))}")
