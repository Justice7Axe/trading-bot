"""PART 1 — 실시간 순위 기록(screener.rank_snapshots)으로 본 '주도주가 언제 보이나' (전 시장 KRX 순위 → 종목군 편향 없음, 표본 작음).

source: value_krx(KRX 거래대금 상위 200, ETF 섞임 → 주식만 다시 순위), search_day(조회 상위 20, 갱신 드묾), search_1m(1분 조회 상위 20).
08:00~08:59 의 value_krx 는 KRX 장전 시간외 대금(등락률 0) — 정규장 전 값이라 참고만.
실행: PYTHONPATH=D:\\Ellie\\trading python kiwoom_trading/research/leader_early/part1_snapshots.py
"""
import os, shutil, sys, tempfile
from collections import defaultdict
from datetime import datetime, time, timedelta
import duckdb
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from common import E, labels, leaders, Rep

dst = os.path.join(tempfile.gettempdir(), "le_screener.duckdb")
try:
    shutil.copy(os.path.join(E.DATA, "screener.duckdb"), dst)
except OSError:
    print("screener.duckdb 잠김 → 전에 복사한 것 사용", file=sys.stderr)
S = duckdb.connect(dst, read_only=True)
STOCK = set(E.NAME)
R = Rep("part1_snapshots.txt")

days = [d for (d,) in S.execute("SELECT DISTINCT date FROM rank_snapshots WHERE source='value_krx' ORDER BY 1").fetchall()]
days = [d for d in days if d in E.CIDX]
TS = [time(8, 30), time(8, 50), time(9, 1), time(9, 3), time(9, 5), time(9, 10), time(9, 15), time(9, 30)]

# snaps[d][src] = [(time, {code: (rank, chg, value)})]
snaps = defaultdict(lambda: defaultdict(list))
for d in days:
    rows = S.execute("""SELECT ts, source, rank, code, change_rate, trade_value FROM rank_snapshots
                        WHERE date=? AND source IN ('value_krx','search_day','search_1m') AND ts::TIME BETWEEN '08:00' AND '10:30'
                        ORDER BY ts, source, rank""", [d]).fetchall()
    cur = defaultdict(lambda: defaultdict(list))
    for ts, src, rk, c, ch, v in rows:
        cur[(ts, src)]["x"].append((rk, c, ch or 0.0, v or 0))
    for (ts, src), dct in sorted(cur.items()):
        lst = sorted(dct["x"])
        if src == "value_krx":
            lst = [x for x in lst if x[1] in STOCK and E.is_common(x[1])]
            m = {c: (i + 1, ch, v) for i, (_, c, ch, v) in enumerate(lst)}
        else:
            m = {c: (rk, ch, v) for rk, c, ch, v in lst}
        snaps[d][src].append((ts.time(), m))


def snap_at(d, src, t, back_min=0):
    """t(분) 시각 스냅샷 = 그 분 59초까지 마지막 기록. back_min 분 전 것도."""
    lim = (datetime.combine(d, t) + timedelta(seconds=59) - timedelta(minutes=back_min)).time()
    best = None
    for ts, m in snaps[d][src]:
        if ts <= lim: best = m
        else: break
    return best or {}


R("=" * 100)
R(f"PART 1 — 실시간 순위 기록 {len(days)}일 ({days[0]} ~ {days[-1]}), 전 시장 KRX 대금 상위 200 (주식만 다시 순위)")
R("라벨 L1 = 그날 대금 20위 안(주식·우선주 제외) & 전일 대비 +5%↑, L2 = L1 & 종가 ≥ 고가×0.9")
R("=" * 100)
tot1 = tot2 = 0
for d in days:
    lb = labels(d); l1 = leaders(d, 1); l2 = leaders(d, 2); tot1 += len(l1); tot2 += len(l2)
    R(f" {d}  L1 {len(l1)}  L2 {len(l2)} : " + ", ".join(f"{E.NAME[c]}({lb[c][3]}위 {lb[c][2]:+.0%}{'*' if c in l2 else ''})" for c in sorted(l1, key=lambda c: lb[c][3])))
R(f" 합계 L1 {tot1} (하루 {tot1 / len(days):.1f}), L2 {tot2} (하루 {tot2 / len(days):.1f})   * = L2")

# ---------- 1) 재현율: 그 시각 순위 안에 이미 있었나
R("\n[1] 그날 주도주 중 T 시각에 이미 순위 안에 있던 비율 (재현율)")
R(f" {'T':6s} | {'대금20':>7s} {'대금50':>7s} {'대금200':>7s} | {'조회일20':>7s} {'조회1분20':>8s} | {'셋 중 하나':>9s} || L2: 대금20 대금50 하나")
for t in TS:
    c1 = defaultdict(int); c2 = defaultdict(int)
    for d in days:
        v = snap_at(d, "value_krx", t); sd = snap_at(d, "search_day", t); s1 = snap_at(d, "search_1m", t)
        for which, cc in ((1, c1), (2, c2)):
            for c in leaders(d, which):
                r = v.get(c, (999,))[0]
                cc["v20"] += r <= 20; cc["v50"] += r <= 50; cc["v200"] += r <= 200
                cc["sd"] += c in sd; cc["s1"] += c in s1
                cc["any"] += (r <= 20) or (c in sd) or (c in s1)
    f = lambda k, cc, n: f"{cc[k] / n:7.0%}"
    R(f" {t.strftime('%H:%M'):6s} | {f('v20', c1, tot1)} {f('v50', c1, tot1)} {f('v200', c1, tot1)} | {f('sd', c1, tot1)} {f('s1', c1, tot1):>8s} | {f('any', c1, tot1):>9s} || "
      f"{f('v20', c2, tot2)} {f('v50', c2, tot2)} {f('any', c2, tot2)}")
R(" (08:30·08:50 대금 = KRX 장전 시간외 대금이라 정규장 순위와 다름)")


# ---------- 2) 간단 규칙의 정밀도·재현율
def rules(d, t):
    v = snap_at(d, "value_krx", t); v5 = snap_at(d, "value_krx", t, 5); s1 = snap_at(d, "search_1m", t)
    # 대금 20위에 처음 든 시각 (09:00 부터)
    first20 = {}
    for ts, m in snaps[d]["value_krx"]:
        if ts < time(9, 0): continue
        for c, (r, ch, val) in m.items():
            if r <= 20 and c not in first20: first20[c] = ts
    lim = (datetime.combine(d, t) + timedelta(seconds=59)).time()
    lim5 = (datetime.combine(d, t) - timedelta(minutes=5)).time()
    pre = t < time(9, 0)
    s1chg = {c: x[1] for c, x in s1.items()}
    out = {
        "대금 20위 & +3%↑": {c for c, (r, ch, _) in v.items() if r <= 20 and ch >= 0.03},
        "대금 20위 & +5%↑": {c for c, (r, ch, _) in v.items() if r <= 20 and ch >= 0.05},
        "대금 50위 & +5%↑": {c for c, (r, ch, _) in v.items() if r <= 50 and ch >= 0.05},
        "대금 10위 & +3%↑": {c for c, (r, ch, _) in v.items() if r <= 10 and ch >= 0.03},
        "조회1분 10위 & +3%↑": {c for c, x in s1.items() if x[0] <= 10 and x[1] >= 0.03 and c in STOCK and E.is_common(c)},
        "조회1분 20위 & +5%↑": {c for c, x in s1.items() if x[1] >= 0.05 and c in STOCK and E.is_common(c)},
        "5분간 대금 순위 30계단↑ (지금 100위 안)": {c for c, (r, ch, _) in v.items() if r <= 100 and v5.get(c, (201,))[0] - r >= 30},
        "5분간 30계단↑ & +3%↑": {c for c, (r, ch, _) in v.items() if r <= 100 and v5.get(c, (201,))[0] - r >= 30 and ch >= 0.03},
        "대금 20위 첫 진입 5분 안 & +3%↑": {c for c, (r, ch, _) in v.items() if r <= 20 and ch >= 0.03 and c in first20 and lim5 < first20[c] <= lim},
        "대금 20위 & +3%↑ & 조회1분 20위": {c for c, (r, ch, _) in v.items() if r <= 20 and ch >= 0.03 and c in s1},
    }
    if pre:
        out = {"조회1분 20위 & +3%↑ (프리)": {c for c, x in s1.items() if x[1] >= 0.03 and c in STOCK and E.is_common(c)},
               "조회1분 10위 & +5%↑ (프리)": {c for c, x in s1.items() if x[0] <= 10 and x[1] >= 0.05 and c in STOCK and E.is_common(c)},
               "장전 시간외 대금 20위": {c for c, (r, ch, _) in v.items() if r <= 20},
               "장전 시간외 20위 or 조회1분 +3%": {c for c, (r, ch, _) in v.items() if r <= 20} | {c for c, x in s1.items() if x[1] >= 0.03 and c in STOCK}}
    return out


R("\n[2] 간단 규칙 — 하루 평균 포착 수, 정밀도(포착 중 주도주 비율), 재현율(주도주 중 포착 비율)")
R(f" {'T':6s} {'규칙':40s} {'하루':>5s} | {'L1 정밀':>7s} {'L1 재현':>7s} | {'L2 정밀':>7s} {'L2 재현':>7s}")
for t in TS:
    agg = defaultdict(lambda: [0, 0, 0, 0, 0])
    for d in days:
        l1, l2 = leaders(d, 1), leaders(d, 2)
        for k, s in rules(d, t).items():
            a = agg[k]; a[0] += len(s); a[1] += len(s & l1); a[2] += len(s & l2); a[3] += len(l1); a[4] += len(l2)
    for k, a in agg.items():
        R(f" {t.strftime('%H:%M'):6s} {k:40s} {a[0] / len(days):5.1f} | {a[1] / max(a[0], 1):7.0%} {a[1] / max(a[3], 1):7.0%} | {a[2] / max(a[0], 1):7.0%} {a[2] / max(a[4], 1):7.0%}")
    R("")

# ---------- 3) 주도주가 대금 20위에 처음 든 시각
R("[3] 그날 주도주(L1)가 대금 20위·50위에 처음 든 시각 (09:00 이후 스냅샷 기준)")
first_all = []
for d in days:
    lb = labels(d); f20 = {}; f50 = {}
    for ts, m in snaps[d]["value_krx"]:
        if ts < time(9, 0): continue
        for c, (r, ch, val) in m.items():
            if r <= 20 and c not in f20: f20[c] = (ts, ch)
            if r <= 50 and c not in f50: f50[c] = (ts, ch)
    for c in sorted(leaders(d, 1), key=lambda c: f20.get(c, (time(23),))[0]):
        a, b = f20.get(c), f50.get(c)
        first_all.append(a[0] if a else None)
        R(f"  {d} {E.NAME[c]:14s} 최종 {lb[c][3]:2d}위 {lb[c][2]:+5.0%} {'L2' if lb[c][1] else '  '} | 50위 첫 진입 {b[0].strftime('%H:%M') if b else '—':5s} "
          f"| 20위 첫 진입 {a[0].strftime('%H:%M') if a else '10:30 뒤'} (그때 {a[1]:+.1%})" if a else
          f"  {d} {E.NAME[c]:14s} 최종 {lb[c][3]:2d}위 {lb[c][2]:+5.0%} {'L2' if lb[c][1] else '  '} | 50위 첫 진입 {b[0].strftime('%H:%M') if b else '—':5s} | 20위 첫 진입 10:30 뒤")
mins = [(datetime.combine(days[0], x) - datetime.combine(days[0], time(9, 0))).seconds / 60 for x in first_all if x]
R(f"\n  20위 첫 진입 (10:30 전 {len(mins)}/{len(first_all)}): 중앙 {np.median(mins):.0f}분 뒤, 09:01 {np.mean(np.array(mins) <= 1.99):.0%}, "
  f"09:05 까지 {np.mean(np.array(mins) <= 5.99):.0%}, 09:10 까지 {np.mean(np.array(mins) <= 10.99):.0%}, 09:30 까지 {np.mean(np.array(mins) <= 30.99):.0%}  (분모 10:30 전 진입한 것)")
n = len(first_all)
for lim in (2, 6, 11, 31, 91):
    R(f"   09:{lim - 1:02d} 까지 진입 / 전체 L1: {sum(1 for x in mins if x < lim) / n:.0%}" if lim < 61 else f"   10:30 까지 진입 / 전체 L1: {len(mins) / n:.0%}")
