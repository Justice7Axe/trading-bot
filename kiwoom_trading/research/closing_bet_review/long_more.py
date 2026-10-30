"""긴 기간(일봉) 추가 분석 — 월별, 약세장 구간, 간밤 미국 지수 (long_daily.pkl 사용).

미국 지수(index.duckdb us_daily, ^NDX·NQ=F):
  '어젯밤' = D일 15:30 전에 끝난 마지막 미국 장 (미국 날짜 < D) → 매수 전에 앎
  '오늘 밤' = D 종가 매수 뒤 D+1 09:00 전에 끝나는 미국 장 (미국 날짜 ≥ D 중 첫 날) → 매수 때 모름 (위험 설명용, 거르기에 못 씀)
출력: data/closing_bet_review/long_more.txt
"""
import bisect
from datetime import timedelta
import os
import pickle
from collections import defaultdict

import numpy as np

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "closing_bet_review")
R = pickle.load(open(os.path.join(OUT, "long_daily.pkl"), "rb"))
US = defaultdict(dict)
for s, d, c in E.IX.execute("SELECT symbol, date, close FROM us_daily ORDER BY date").fetchall():
    US[s][d] = c


def us_ret(sym):
    ds = sorted(US[sym]); r = {ds[i]: US[sym][ds[i]] / US[sym][ds[i - 1]] - 1 for i in range(1, len(ds))}
    return ds, r


def prior(sym, d):
    """NQ=F 는 날짜가 '세션 시작일'(일요일 날짜도 있음, ^NDX 다음 날과 상관 0.64) → 날짜 X 는 KST X+2 06~07시에 끝남.
    그래서 KST d 에 끝난 NQ=F 는 날짜 ≤ d−2 (d−1 이하로 잡으면 오늘 밤이 섞임 — 처음 돌렸을 때 이 실수로 +1.49% 처럼 보였음)."""
    ds, r = US_R[sym]
    cut = d - timedelta(days=1) if sym == "NQ=F" else d
    i = bisect.bisect_left(ds, cut) - 1
    return r.get(ds[i]) if i >= 1 else None


def tonight(sym, d):
    ds, r = US_R[sym]; i = bisect.bisect_left(ds, d)
    return r.get(ds[i]) if i < len(ds) else None


US_R = {s: us_ret(s) for s in ("^NDX", "NQ=F")}
rep = open(os.path.join(OUT, "long_more.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(s + "\n"); rep.flush()


def line(v, nm):
    v = np.array(v)
    say(f"  {nm:34s} {len(v):5d}건 건당 {v.mean():+.2%}" if len(v) else f"  {nm:34s} 0건")


base = [r for r in R if r["rk"] <= 10 and 0 < r["chg"] < E.LIMIT]
say("== 월별 대금 10위 · 상승 마감 → 다음 날 시가 (건당 / 건수 | 대금 200 전체)")
m = defaultdict(list); ma = defaultdict(list)
for r in R:
    k = f"{r['date']:%Y-%m}"; ma[k].append(r["ret"])
    if r["rk"] <= 10 and 0 < r["chg"] < E.LIMIT: m[k].append(r["ret"])
for k in sorted(m):
    say(f"  {k}: {np.mean(m[k]):+.2%} ({len(m[k])}건, 합계 {sum(m[k]) * 100:+.0f}만) | 전체 {np.mean(ma[k]):+.2%}")

for sym in ("^NDX", "NQ=F"):
    say(f"\n== {sym} 어젯밤 등락 (매수 전에 앎) · 대금 10위 · 상승 — A 처음 보는 기간 / B 본 기간")
    for lo, hi, nm in ((-1, -0.01, "−1%↓"), (-0.01, 0, "−1~0%"), (0, 0.01, "0~+1%"), (0.01, 1, "+1%↑")):
        for pn, pf in (("A", lambda d: d < E.P0), ("B", lambda d: d >= E.P0)):
            line([r["ret"] for r in base if pf(r["date"]) and (x := prior(sym, r["date"])) is not None and lo < x <= hi], f"{nm} {pn}")
say("\n== ^NDX 오늘 밤 (매수 때 모름, 위험 크기 설명용) · 대금 10위 · 상승")
for lo, hi, nm in ((-1, -0.01, "−1%↓"), (-0.01, 0, "−1~0%"), (0, 0.01, "0~+1%"), (0.01, 1, "+1%↑")):
    line([r["ret"] for r in base if (x := tonight("^NDX", r["date"])) is not None and lo < x <= hi], nm)
pickle.dump({"prior": {d: prior("^NDX", d) for d in E.CAL}, "tonight": {d: tonight("^NDX", d) for d in E.CAL},
             "prior_nq": {d: prior("NQ=F", d) for d in E.CAL}}, open(os.path.join(OUT, "us_map.pkl"), "wb"))
