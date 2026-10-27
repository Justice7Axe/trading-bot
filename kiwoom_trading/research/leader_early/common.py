"""당일 주도주 조기 발견 연구 — 공통 (라벨·AUC·출력).

라벨 (그날 장 마감 뒤에야 아는 사실 = 맞힐 대상):
  L1 = 그날 거래대금 상위 20위(주식만: stocks 테이블 = ETF·ETN·스팩 없음, 우선주 제외) & 전일 대비 +5%↑
  L2 = L1 & 종가 ≥ 그날 고가 × 0.9 (끝까지 강함)
일봉은 engine.daily_day (2026-09-14 이후 통합 종가 → 정규장 1분봉으로 바로잡음). 대금은 일봉 값(9-14 이후는 통합 대금).
"""
import os
from functools import lru_cache
import numpy as np

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "leader_early"); os.makedirs(OUT, exist_ok=True)


@lru_cache(maxsize=None)
def common_rank(d):
    """그날 주식(우선주 제외) 대금 순위 {code: rank}."""
    rows = sorted(((c, r[5] or 0) for c, r in E.daily_day(d).items() if E.is_common(c)), key=lambda x: -x[1])
    return {c: i + 1 for i, (c, _) in enumerate(rows)}


@lru_cache(maxsize=None)
def labels(d):
    """{code: (L1, L2, chg, rank)} — 그날 대금 20위 안 종목만 (나머지는 둘 다 False)."""
    dd, pd_ = E.daily_day(d), E.daily_day(E.prev_day(d))
    out = {}
    for c, r in common_rank(d).items():
        if r > 20: continue
        a, b = dd[c], pd_.get(c)
        if not b or not b[3]: continue
        ch = a[3] / b[3] - 1
        l1 = ch >= 0.05
        l2 = l1 and a[3] >= a[1] * 0.9
        out[c] = (l1, l2, ch, r)
    return out


def leaders(d, which=1):
    return {c for c, v in labels(d).items() if v[which - 1]}


def auc(score, y):
    """순위 기반 AUC (동점은 평균 순위). score 에 nan 있으면 뺀다."""
    s = np.asarray(score, float); y = np.asarray(y, bool)
    m = ~np.isnan(s); s, y = s[m], y[m]
    n1, n0 = y.sum(), (~y).sum()
    if n1 == 0 or n0 == 0: return float("nan")
    order = s.argsort(kind="mergesort")
    ranks = np.empty(len(s)); ranks[order] = np.arange(1, len(s) + 1)
    # 동점 평균
    ss = s[order]; i = 0
    while i < len(ss):
        j = i
        while j + 1 < len(ss) and ss[j + 1] == ss[i]: j += 1
        if j > i: ranks[order[i:j + 1]] = (i + j + 2) / 2
        i = j + 1
    return (ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


class Rep:
    def __init__(self, name):
        self.f = open(os.path.join(OUT, name), "w", encoding="utf-8")

    def __call__(self, s=""):
        print(s, flush=True); self.f.write(str(s) + "\n"); self.f.flush()
