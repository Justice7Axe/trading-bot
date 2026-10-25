"""하락장 헤지주 종가 베팅 1년 백테스트 (2026-10-26 사용자: "하락장에는 헤지주를 공략. 안랩처럼 종가까지 고가 부근을 유지하면
종가 매매 후 다음 날 갭 상승을 노림").

헤지주 목록 (미래 정보 없이, 그날 전 120거래일로만 매일 다시 만듦):
  코스피 하락일(≤ −1%)에 오른 비율·평균 등락이 좋은 종목. 20일 평균 대금 ≥ 30억, 우선주 제외, 하락일 표본 ≥ 6.
  A = 하락일 평균 등락 > 0 & 오른 비율 ≥ 50% / B = A 중 평균 상위 30 / C = 하락일 평균 ≥ 코스피 +2%p (시장 대비 강함)
신호: 코스피 하락일(정의 3가지)에 헤지주가 상승 마감(상한가 제외) & 고가 근처((종가−저가)/(고가−저가) ≥ 0.8)
매수: 정규장 종가 / 매도: 다음 날 09:00 시가 (1분봉 있으면 08:00 NXT 시가도), 비용 0.25%.
⚠️ 고가 근처·상승 판단을 종가로 함(실제는 15:19 판단 → 종가 매수) — 약간 낙관적.
"""
import numpy as np
from collections import defaultdict
from engine import *

R = Report("t_hedge.txt")
D = days()
ALL = [d for d in CAL if d <= P1]
SIG = {}
for i, d in enumerate(CAL):
    if i < 21 or d not in KOSPI: continue
    xs = [kospi_chg(CAL[j]) for j in range(i - 20, i)]
    xs = [x for x in xs if x is not None]
    SIG[d] = np.std(xs) if len(xs) >= 15 else None

chg_cache = {}


def day_chg(d):
    if d not in chg_cache:
        a, b = daily_day(d), daily_day(prev_day(d))
        chg_cache[d] = {c: a[c][3] / b[c][3] - 1 for c in a if c in b and b[c][3] and a[c][3]}
    return chg_cache[d]


def hedge_list(d, mode):
    i = CIDX[d]
    win = [CAL[j] for j in range(max(0, i - 120), i)]
    downs = [x for x in win if (kospi_chg(x) or 0) <= -0.01]
    if len(downs) < 6: return set()
    # 유동성: 전날까지 20일 평균 대금
    val = defaultdict(list)
    for x in win[-20:]:
        for c, r in daily_day(x).items(): val[c].append(r[5] or 0)
    liq = {c for c, v in val.items() if np.mean(v) >= 3e9 and is_common(c)}
    stat = {}
    for c in liq:
        rs = [day_chg(x).get(c) for x in downs]
        rs = [r for r in rs if r is not None]
        if len(rs) < 6: continue
        ex = [day_chg(x)[c] - kospi_chg(x) for x in downs if c in day_chg(x)]
        stat[c] = (np.mean(rs), np.mean([r > 0 for r in rs]), np.mean(ex))
    if mode == "A": return {c for c, s in stat.items() if s[0] > 0 and s[1] >= 0.5}
    if mode == "B":
        a = sorted((c for c, s in stat.items() if s[0] > 0 and s[1] >= 0.5), key=lambda c: -stat[c][0])
        return set(a[:30])
    if mode == "C": return {c for c, s in stat.items() if s[2] >= 0.02}
    if mode == "ALL": return set(stat)


def exit_ret(c, d, buy_daily):
    ex = next_day_exits(c, d, buy_daily * (factor(c, d) or 0)) if factor(c, d) else {}
    if "09:00 시가" in ex: return ex["09:00 시가"], ex.get("08:00 NXT 시가"), "1분봉"
    n = next_day(d)
    nd = daily_day(n).get(c) if n else None
    if not nd or not nd[0]: return None, None, None
    r = nd[0] / buy_daily - 1 - COST
    return (r, None, "일봉") if abs(r) < 0.35 else (None, None, None)


DOWN = {
    "코스피 < 0": lambda d: (kospi_chg(d) or 0) < 0,
    "코스피 ≤ −1%": lambda d: (kospi_chg(d) or 0) <= -0.01,
    "코스피 ≤ −1σ (강한 하락장 근사)": lambda d: SIG.get(d) and (kospi_chg(d) or 0) <= -SIG[d],
    "코스피 ≥ 0 (비교: 하락일 아님)": lambda d: (kospi_chg(d) or 0) >= 0,
}

lists = {m: {} for m in ("A", "B", "C", "ALL")}
for d in D:
    for m in lists: lists[m][d] = hedge_list(d, m)
R.say(f"기간 {D[0]} ~ {D[-1]}, {len(D)}일. 헤지주 목록 평균 크기: " + ", ".join(f"{m} {np.mean([len(v) for v in lists[m].values()]):.0f}" for m in lists))

rows = []   # (d, c, mode-set, ret9, ret8, src, closepos, chg)
for d in D:
    t = daily_day(d); ch = day_chg(d)
    cand = set().union(*(lists[m][d] for m in lists))
    for c in cand:
        r = t.get(c); x = ch.get(c)
        if not r or x is None or x <= 0 or x >= LIMIT: continue
        o, h, l, cl = r[:4]
        pos = (cl - l) / (h - l) if h > l else 1.0
        if pos < 0.7: continue
        r9, r8, src = exit_ret(c, d, cl)
        if r9 is None: continue
        rows.append((d, c, {m for m in lists if c in lists[m][d]}, r9, r8, src, pos, x))
R.say(f"후보(헤지주 & 상승 & 고가 근처 0.7↑) {len(rows)}건, 1분봉 매도 {sum(r[5] == '1분봉' for r in rows)}건")

for dn, f in DOWN.items():
    R.say(f"\n== {dn} ({sum(1 for d in D if f(d))}일) ==")
    for m in ("A", "B", "C", "ALL"):
        for pmin in (0.8, 0.9):
            tr = [(d, r9) for d, c, ms, r9, r8, src, pos, x in rows if f(d) and m in ms and pos >= pmin]
            R.stats(tr, f"목록 {m} · 고가 근처 ≥{pmin}")
        tr = [(d, r9) for d, c, ms, r9, r8, src, pos, x in rows if f(d) and m in ms and pos >= 0.8 and x >= 0.03]
        R.stats(tr, f"목록 {m} · 고가 근처 ≥0.8 · +3%↑")

R.say("\n== 08:00 NXT 시가 매도 (1분봉 있는 것만, 코스피 < 0, 목록 A, ≥0.8) ==")
sub = [(d, r9, r8) for d, c, ms, r9, r8, src, pos, x in rows if DOWN["코스피 < 0"](d) and "A" in ms and pos >= 0.8 and r8 is not None]
R.stats([(d, a) for d, a, b in sub], "09:00 시가")
R.stats([(d, b) for d, a, b in sub], "08:00 NXT 시가")

R.say("\n== 안랩(053800) 신호일 (코스피 < 0, 상승, 고가 근처 ≥0.8) ==")
for d, c, ms, r9, r8, src, pos, x in rows:
    if c == "053800" and DOWN["코스피 < 0"](d) and pos >= 0.8:
        R.say(f"  {d} 코스피 {kospi_chg(d):+.2%} 안랩 {x:+.2%} 고가근처 {pos:.2f} 목록 {''.join(sorted(ms))} → 다음 날 {r9:+.2%} ({src})")

R.say("\n== 자주 나온 헤지주 (코스피 < 0, 목록 A, ≥0.8) ==")
cnt = defaultdict(list)
for d, c, ms, r9, r8, src, pos, x in rows:
    if DOWN["코스피 < 0"](d) and "A" in ms and pos >= 0.8: cnt[c].append(r9)
for c, v in sorted(cnt.items(), key=lambda kv: -len(kv[1]))[:25]:
    R.say(f"  {NAME.get(c, c)}({c}) [{SECTOR.get(c)}] {len(v)}건 건당 {np.mean(v):+.2%}")
