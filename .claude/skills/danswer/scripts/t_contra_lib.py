"""④ 역행 강세 종가 다시 검증 (2026-10-26 사용자 "④ 다시 검증해줘") — 바로잡은 엔진(engine.py)으로, 실제 운영 규칙에 최대한 맞춤.

운영 규칙 (screener/contra_close.py): 09:10·09:20 강한 하락장 판정(코스피 ≤ −1σ 또는 대금 상위 200 주식 중앙 ≤ −1.5%)인 날,
15:15~15:19 대금 30위 안, 그 시점 대금 상위 주식 중앙값 대비 +3%p↑, 상한가 제외 → 종가 매수 → 다음 날 09:00 시가 매도.
옛 근거(스크래치 contra_close.py, closebet.pkl): 422건 +0.85% — closebet.pkl 에 액면분할 등 −80% 같은 잘못된 줄이 있었음.

여기서:
- 강한 하락장 판정 = 09:10 또는 09:20 의 코스피(지수 1분봉) z ≤ −1 또는 전날 대금 상위 200 의 1분봉 중앙 등락 ≤ −1.5% (운영과 같은 기준)
- 15:15 대금 순위 = 그날 최종 대금 순위로 근사, 중앙값·등락 = 그날 정규장 종가 기준 (15:19 값과 조금 다름)
- 매수 = 정규장 종가, 매도 = 다음 날 09:00 시가 (1분봉, 기준 맞춤), 비용 0.25%
"""
import numpy as np
from datetime import datetime, time
from engine import *


IDXM = {}
for ts, cl in IX.execute("SELECT ts, close FROM idx_min WHERE code='001' ORDER BY ts").fetchall():
    IDXM[(ts.date(), ts.time())] = cl


def kospi_at(d, t):
    for m in range(0, 6):
        k = (d, time(t.hour, t.minute + m))
        if k in IDXM: return IDXM[k]
    return None


def sd20(d):
    i = CIDX[d]
    xs = [kospi_chg(CAL[j]) for j in range(i - 20, i)]
    xs = [x for x in xs if x is not None]
    return np.std(xs) if len(xs) >= 15 else None


def med_at(d, t):
    p = prev_day(d)
    top = [c for c, r in sorted(value_rank(p).items(), key=lambda kv: kv[1])[:200] if is_common(c)]
    B = load_day(top, d); P = load_day(top, p)
    xs = []
    for c in top:
        pr = regular(P[c]); x = at(B[c], t)
        if pr and x: xs.append(x / pr[-1][4] - 1)
    return float(np.median(xs)) if len(xs) >= 50 else None


def strong_down(d):
    p = prev_day(d)
    s = sd20(d)
    for t in (time(9, 10), time(9, 20)):
        k = kospi_at(d, t)
        z = (k / KOSPI[p] - 1) / s if k and p in KOSPI and s else None
        m = med_at(d, t)
        if (z is not None and z <= -1) or (m is not None and m <= -0.015):
            return True, z, m
    return False, z, m


def day_chg(d):
    a, b = daily_day(d), daily_day(prev_day(d))
    return {c: a[c][3] / b[c][3] - 1 for c in a if c in b and b[c][3] and a[c][3]}


def exit9(c, d, buy_daily):
    f = factor(c, d)
    if not f: return None
    ex = next_day_exits(c, d, buy_daily * f)
    return ex.get("09:00 시가")


