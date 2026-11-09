"""저돌(책 대상)을 장 시작 전에 아는 시장 조건만으로 거른 결과 — jeodol_trades.pkl (yoonta_jeodol_grid.py 결과) 사용.
조건: 전날 코스피 종가 ≥ 250일 최고 종가 × 0.9 (52주 고점 −10% 안 = 상승 추세, 책 11쪽 '지수가 고점을 계속 높임'에 가장 가까운 숫자).

    .venv\\Scripts\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_jeodol_causal.py > data/yoonta/jeodol_causal.txt
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
T52, MA20 = {}, {}
for i, d in enumerate(dates):
    if i >= 250:
        T52[d] = cl[i - 1] >= 0.9 * cl[i - 250:i].max()
        MA20[d] = cl[i - 1] >= cl[i - 20:i].mean()
print("저돌(책 대상) — 장 전에 아는 시장 조건만으로 거름. 비용 0.25%, 건당 100만")
for rn in ("r60", "r20"):
    print(f"\n=== {'60일' if rn == 'r60' else '20일'} 최고가 돌파")
    for s, t in ((0.02, 0.05), (0.02, 0.10), (0.03, 0.05), (0.03, 0.07), (0.03, 0.10), (0.03, None), (0.04, 0.05), (0.04, 0.10), (0.04, None)):
        tr = TR[(rn, s, t)]
        for lab, f in (("52주 고점 −10% 안", lambda x: T52.get(x[0])), ("52주 −10% 안 & 전날 20일선 위", lambda x: T52.get(x[0]) and MA20.get(x[0])),
                       ("52주 −10% 안 · 09:10 강한 하락(D) 날 빼기 (09:10 뒤 매수만)", lambda x: T52.get(x[0]) and not (x[3] == "D") and x[5] >= Y.time(9, 10)),
                       ("52주 −10% 밖", lambda x: not T52.get(x[0]))):
            sub = [(x[0], x[1], x[2], None, None) for x in tr if f(x)]
            Y.stats(sub, f"−{s:.0%}/{'없음' if t is None else f'+{t:.0%}'} · {lab}")
