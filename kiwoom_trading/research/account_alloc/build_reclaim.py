"""🔁 시가 탈환 1년 매매 목록 (premarket_reclaim/timing.py 의 E1 시가 회복 · M3 절반 +2R·트레일 3% 를 그대로, 매수 시각·가격까지 저장).

기존 보고(buy-signals 18장): 1년 2,273건 건당 +0.33% ★ (손절 거리 조건 없음).
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.account_alloc.build_reclaim → data/account_alloc/reclaim.pkl
"""
import os
import pickle
import sys

import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.premarket_reclaim.timing import entries, sell, setup

OUT = os.path.join(E.DATA, "account_alloc")
os.makedirs(OUT, exist_ok=True)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    for i, d in enumerate(E.days()):
        p = E.prev_day(d)
        U = [c for c, r in E.value_rank(p).items() if r <= 200 and E.is_common(c)]
        B, P = E.load_day(U, d), E.load_day(U, p)
        for c in U:
            b = B.get(c) or []
            pr = E.regular(P.get(c) or [])
            if len(b) < 100 or len(pr) < 30:
                continue
            s = setup(b, pr[-1][4])
            if not s:
                continue
            stop0 = s[2] * 0.999
            en = entries(b, s).get("E1 시가 회복")
            if not en:
                continue
            j, e = en
            if e <= stop0:
                continue
            ex = E.next_day_exits(c, d, e)
            nopen = e * (1 + ex["09:00 시가"] + E.COST) if "09:00 시가" in ex else None
            r, rr = sell(b, j, e, stop0, nopen, e + 2 * (e - stop0))
            if r is not None and abs(r) < 0.35:
                rows.append(dict(date=d, code=c, t=b[j][0], px=float(e), ret=float(r), R=float(rr), prev_close=pr[-1][4]))
        if i % 20 == 0:
            print(f"{d} {len(rows)}", file=sys.stderr, flush=True)
    pickle.dump(rows, open(os.path.join(OUT, "reclaim.pkl"), "wb"))
    v = np.array([x["ret"] for x in rows])
    print(f"🔁 {len(rows)}건 건당 {v.mean():+.2%} (기존 보고 2,273건 +0.33%)")


if __name__ == "__main__":
    main()
