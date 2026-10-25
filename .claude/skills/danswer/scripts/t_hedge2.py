"""하락장 헤지주 종가 베팅 ② — 고정 헤지주 목록(보안·방산·통신·전력가스·음식료담배·비철)과 '목록 없이 대금 상위' 비교.
t_hedge.py(과거 하락일 성적으로 만든 목록)는 모두 손실 → 사람이 생각하는 '헤지주' 업종 목록과 대금 순위 조건을 따로 본다.
신호·매도는 t_hedge.py 와 같음 (하락일 · 상승 마감 · 고가 근처 → 종가 매수 → 다음 날 09:00 시가).
⚠️ 고정 목록은 지금 아는 업종 지식으로 고른 것(사후 선택 위험).
"""
import numpy as np
from collections import defaultdict
from engine import *

R = Report("t_hedge2.txt")
D = days()
SIG = {}
for i, d in enumerate(CAL):
    xs = [kospi_chg(CAL[j]) for j in range(max(1, i - 20), i)]
    xs = [x for x in xs if x is not None]
    SIG[d] = np.std(xs) if len(xs) >= 15 else None

FIXED = {
    "보안": ["053800", "263860", "042510", "136540", "208350", "150900"],
    "방산": ["079550", "012450", "064350", "272210", "047810", "103140", "005870"],
    "통신": ["017670", "030200", "032640"],
    "전력가스": ["015760", "036460", "034020", "052690"],
    "음식료담배": ["033780", "271560", "004370", "003230", "097950", "280360", "005180"],
    "비철·금": ["010130", "103140"],
}
FCODE = {c: g for g, cs in FIXED.items() for c in cs}
SEC_DEF = {"통신", "전기/가스", "음식료/담배"}


def day_chg(d, _c={}):
    if d not in _c:
        a, b = daily_day(d), daily_day(prev_day(d))
        _c[d] = {c: a[c][3] / b[c][3] - 1 for c in a if c in b and b[c][3] and a[c][3]}
    return _c[d]


def exit_ret(c, d, buy_daily):
    f = factor(c, d)
    ex = next_day_exits(c, d, buy_daily * f) if f else {}
    if "09:00 시가" in ex: return ex["09:00 시가"]
    n = next_day(d); nd = daily_day(n).get(c) if n else None
    if not nd or not nd[0]: return None
    r = nd[0] / buy_daily - 1 - COST
    return r if abs(r) < 0.35 else None


DOWN = {
    "코스피 < 0": lambda d: (kospi_chg(d) or 0) < 0,
    "코스피 ≤ −1%": lambda d: (kospi_chg(d) or 0) <= -0.01,
    "코스피 ≤ −1σ": lambda d: bool(SIG.get(d)) and (kospi_chg(d) or 0) <= -SIG[d],
}
rows = []   # d, c, group, ret, pos, chg, vrank, rel
for d in D:
    if (kospi_chg(d) or 0) >= 0: continue
    t = daily_day(d); ch = day_chg(d); vr = value_rank(d)
    k = kospi_chg(d)
    for c, r in t.items():
        x = ch.get(c)
        if x is None or x <= 0 or x >= LIMIT or not is_common(c): continue
        g = FCODE.get(c) or ("업종:" + SECTOR[c] if SECTOR.get(c) in SEC_DEF else None)
        rk = vr.get(c, 9999)
        if not g and rk > 100: continue
        o, h, l, cl = r[:4]
        pos = (cl - l) / (h - l) if h > l else 1.0
        if pos < 0.8: continue
        ret = exit_ret(c, d, cl)
        if ret is None: continue
        rows.append((d, c, g, ret, pos, x, rk, x - k))
R.say(f"기간 {D[0]} ~ {D[-1]}. 후보 {len(rows)}건 (하락일·상승·고가 근처 ≥0.8)")
for dn, f in DOWN.items():
    R.say(f"\n== {dn} ({sum(1 for d in D if f(d))}일) ==")
    sel = [r for r in rows if f(r[0])]
    R.stats([(r[0], r[3]) for r in sel if r[2] and not r[2].startswith("업종")], "고정 헤지주 목록 전체")
    R.stats([(r[0], r[3]) for r in sel if r[2] and not r[2].startswith("업종") and r[6] <= 100], "고정 목록 · 대금 100위 안")
    for g in FIXED:
        R.stats([(r[0], r[3]) for r in sel if r[2] == g], f"  {g}")
    R.stats([(r[0], r[3]) for r in sel if r[2] and r[2].startswith("업종")], "방어 업종(통신·전기가스·음식료) 전체")
    for n in (10, 30, 100):
        R.stats([(r[0], r[3]) for r in sel if r[6] <= n], f"목록 없이 대금 {n}위 안")
        R.stats([(r[0], r[3]) for r in sel if r[6] <= n and r[7] >= 0.03], f"목록 없이 대금 {n}위 안 · 코스피 대비 +3%p↑")
