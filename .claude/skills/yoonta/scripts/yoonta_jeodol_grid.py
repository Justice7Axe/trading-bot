"""저돌(책 대상) 손절·익절 조합·월별·시장 분위기 확인 — yoonta_minute_bt.py 의 함수를 그대로 쓴다.

    .venv\\Scripts\\python.exe -X utf8 .claude/skills/yoonta/scripts/yoonta_jeodol_grid.py --kang-cached > data/yoonta/jeodol_grid.txt
"""
import os
import pickle
import sys
from collections import defaultdict
from datetime import time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import yoonta_minute_bt as Y  # noqa: E402

GRID = [(s, t) for s in (0.02, 0.03, 0.04, 0.05) for t in (0.03, 0.05, 0.07, 0.10, None)]
TR = defaultdict(list)


def run_day(d):
    info, p1, p2 = Y.day_info(d)
    want = [c for c, x in info.items() if x["book"]]
    if not want:
        return
    bars = Y.load_bars(d, p1, p2, want)
    for code, b in bars.items():
        inf = info[code]
        if b["tm"][b["k0"]] > time(9, 5):
            continue
        for rn in ("r20", "r60"):
            e = Y.sig_jeodol(b, inf, inf[rn])
            if e is None or e >= len(b["tm"]) or b["tm"][e] > Y.T_END or Y.value_until(b, e - 1) < 1e9:
                continue
            buy = b["o"][e]
            if buy >= inf["pc"] * 1.285:
                continue
            gapx = "갭 +5%↑" if inf["gap"] >= 0.05 else "갭 +5% 미만"
            for s, t in GRID:
                r, _ = Y.simulate(b, e, inf["nopen"], stop=buy * (1 - s), tps=[(1, buy * (1 + t))] if t else ())
                if r is not None:
                    TR[(rn, s, t)].append((d, r, code, Y.REG.get(d, "?"), gapx, b["tm"][e]))


if __name__ == "__main__":
    for i, d in enumerate(Y.DAYS[:-1]):
        run_day(d)
        if i % 40 == 0:
            print(d, file=sys.stderr, flush=True)
    pickle.dump(dict(TR), open(os.path.join(Y.OUT, "jeodol_trades.pkl"), "wb"))
    print("저돌(책 대상: 전날 대금 100억↑·거래량 1,000만 주↑) 09:00~10:00 — 손절·익절 조합, 비용 0.25%, 건당 100만")
    for rn in ("r60", "r20"):
        print(f"\n=== {'60일' if rn == 'r60' else '20일'} 최고가 돌파")
        for s, t in GRID:
            tr = TR[(rn, s, t)]
            for lab, f in (("전부", lambda x: True), ("N+ 만", lambda x: x[3] == "N+"), ("N− 빼고 D 빼고 (U·N+)", lambda x: x[3] in ("U", "N+"))):
                sub = [(x[0], x[1], x[2], None, None) for x in tr if f(x)]
                Y.stats(sub, f"손절 −{s:.0%} · 익절 {'없음' if t is None else f'+{t:.0%}'} · {lab}")
    for rn in ("r60",):
        tr = TR[(rn, 0.03, 0.05)]
        print("\n### 60일 · −3%/+5% 월별 합계(만) · 분위기")
        bm = defaultdict(list)
        for x in tr:
            bm[(x[0].strftime("%Y-%m"))].append(x)
        for m in sorted(bm):
            v = bm[m]
            print(f"  {m}: {len(v):3d}건 합계 {sum(x[1] for x in v) * 100:+5.0f}만 | N+ {sum(x[1] for x in v if x[3] == 'N+') * 100:+5.0f}만 "
                  f"({sum(1 for x in v if x[3] == 'N+')}건)")
        for lab in ("갭 +5%↑", "갭 +5% 미만"):
            v = [x[1] for x in tr if x[4] == lab]
            print(f"  {lab}: {len(v)}건 건당 {np.mean(v):+.2%}")
        for a, b2 in ((time(9, 0), time(9, 10)), (time(9, 10), time(9, 30)), (time(9, 30), time(10, 1))):
            v = [x[1] for x in tr if a <= x[5] < b2]
            print(f"  매수 {a:%H:%M}~{b2:%H:%M}: {len(v)}건 건당 {np.mean(v) if v else 0:+.2%}")
