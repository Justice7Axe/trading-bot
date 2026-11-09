"""5) 인버스 갭(모의)도 같은 질문: 장 시작 대금 상위 주식 중앙 ≤ −1% → 09:01 인버스 매수 → 15:19 정리. 전날 코스피 급락 다음 날이면 손실인가.

갭 중앙: 2025-10-15~2026-10-16 은 옛 연구 regime_days.pkl 의 gap_med(전날 대금 상위 200 시가 갭 중앙),
         그 뒤는 스캐너 rank_snapshots(value_krx) 09:00~09:05 첫 스냅샷의 주식만 등락 중앙 (운영과 같은 방식).
실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.inverse_after_drop.gap → data/inverse_after_drop/gap.txt
"""
import os
import sys
from datetime import date, time

import duckdb
import numpy as np
import pandas as pd

from kiwoom_trading.research.inverse_after_drop import common as C

rep = open(os.path.join(C.OUT, "gap.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(s + "\n"); rep.flush()


def gap_meds():
    g = pd.read_pickle(os.path.join(C.DATA, "research_archive", "f3f6486b", "regime_days.pkl"))
    out = {r.date: float(r.gap_med) for r in g.itertuples()}
    dm = C.ro(os.path.join(C.DATA, "daily_ohlcv.duckdb"))
    stocks = {c for (c,) in dm.execute("SELECT code FROM stocks").fetchall()}
    dm.close()
    s = C.ro(os.path.join(C.DATA, "screener_snapshot.duckdb"))
    rows = s.execute("SELECT date, ts, code, change_rate FROM rank_snapshots WHERE source='value_krx' AND ts::time BETWEEN '09:00' AND '09:05:59' "
                     "AND date > '2026-10-16' ORDER BY ts").fetchall()
    s.close()
    first = {}
    for d, ts, code, ch in rows:
        first.setdefault(d, ts)
    by = {}
    for d, ts, code, ch in rows:
        if ts == first[d] and code in stocks and ch is not None:
            by.setdefault(d, []).append(ch)
    for d, xs in by.items():
        if len(xs) >= 50:
            out[d] = float(np.median(xs))
    return out, stocks


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    gm, stocks = gap_meds()
    say(f"(확인) 123310 이 주식 목록에 있나: {'123310' in stocks} / 갭 중앙 있는 날 {len(gm)}일 ({min(gm)} ~ {max(gm)})")
    KD = {r["date"]: r for r in C.idx_daily("001")}; kd = sorted(KD)
    rows = []
    for d, g in sorted(gm.items()):
        if g > -0.01 or d not in KD or d > date(2026, 11, 6):
            continue
        i = kd.index(d)
        prev = KD[kd[i - 1]]["close"] / KD[kd[i - 2]]["close"] - 1
        x, src, _ = C.trade(d, entry=time(9, 1), tp=None, sl=None, exit_mode="close")
        if x is None:
            continue
        rows.append(dict(date=d, gap=g, prev=prev, ret=x, src=src))
    say(f"\n# 인버스 갭 (갭 중앙 ≤ −1% → 09:01 매수 → 15:19 정리) {len(rows)}일, 비용 0.05%")
    tr = lambda g: [(r["date"], r["ret"]) for r in g]
    say(f"  전체            {C.fmt(C.summ(tr(rows)))}")
    for lab, lo, hi in (("전날 ≤ −3%", -9, -0.03), ("전날 −3 ~ −2%", -0.03, -0.02), ("전날 −2 ~ −1%", -0.02, -0.01), ("전날 −1 ~ 0%", -0.01, 0), ("전날 > 0%", 0, 9),
                        ("전날 ≤ −2% 누적", -9, -0.02), ("전날 > −2% 누적", -0.02, 9)):
        say(f"  {lab:14s} {C.fmt(C.summ(tr([r for r in rows if lo < r['prev'] <= hi])))}")
    say("\n  전날 −2%↓ 날 하나씩:")
    for r in rows:
        if r["prev"] <= -0.02:
            say(f"   {r['date']} 전날 코스피 {r['prev']:+.1%} 갭 중앙 {r['gap']:+.1%} → {r['ret']:+.2%} ({r['src']})")
    say("  자료: " + ", ".join(f"{s} {sum(1 for r in rows if r['src'] == s)}" for s in ("real", "proxy")))


if __name__ == "__main__":
    main()
