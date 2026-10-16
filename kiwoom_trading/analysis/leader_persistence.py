"""'끝까지 가는 종목' 장중 판별 — 아침에 오른 종목 중 종가까지 강한 종목을 10:00 전에 가를 수 있는가.

배경 (2026-10-17): 10-16 주도주 9종목의 최적 매수 자리(VWAP 눌림 반등 등)를 규칙으로 만들면 9종목에선 +1.73%/건,
같은 규칙을 다른 종목에 쓰면 −0.91%/건이었다. 자리보다 '그날 끝까지 오른 종목인가'가 핵심이라 그 판별을 따로 본다.

표본 (선택 편향 없이):
- data/minute_history.duckdb (통합 AL 1분봉). 날짜 D 에는 **전날 전 종목 대금 순위 상위 N(200)** 만 쓴다.
  (D 의 상위 200 도 섞여 있지만 장 마감 뒤에야 아는 목록이라 쓰지 않는다.)
- 판정 시각 T(09:30, 10:00)에 전일 대비 +3% 이상이고, 표본 안 장중 누적 대금 순위 100위 안인 종목 = 후보.
- 결과: T 다음 봉 시가 → 15:19 종가 수익률(비용 0.25%), 그리고 '끝까지 강함' = 그 수익률 ≥ +2%.

보는 것:
1. 특징별 판별력(AUC: 0.5 = 못 가름, 1 = 완벽) — 기간 앞 절반 / 뒤 절반 각각 (둘 다 같은 방향이어야 진짜)
2. 특징별 다섯 구간 평균 수익률
3. 앞 절반에서 고른 상위 특징 2~3개 조합 규칙 → 뒤 절반에서 그대로 확인 (걷기 앞 검증)

    .venv\\Scripts\\python.exe -m kiwoom_trading.analysis.leader_persistence [--db 복사본] [--since 2025-10-15]
"""
import argparse
import bisect
import itertools
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import date, time

import duckdb

from kiwoom_trading.common.daily_store import PROJECT_ROOT
from kiwoom_trading.screener.leader_shape import features

COST = 0.0025
TS = (time(9, 30), time(10, 0))


def _copy(path: str) -> str:
    dst = os.path.join(tempfile.gettempdir(), f"lp_{os.getpid()}_" + os.path.basename(path))
    shutil.copy(path, dst)
    return dst


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    rank_sum, i = 0.0, 0
    while i < len(allv):          # 같은 값은 평균 순위
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        r = (i + 1 + j) / 2
        rank_sum += r * sum(1 for k in range(i, j) if allv[k][1])
        i = j
    return (rank_sum - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def collect(m, dm, days, top: int) -> list[dict]:
    all_days = [r[0] for r in dm.execute("SELECT DISTINCT date FROM daily_ohlcv WHERE code='005930' ORDER BY 1").fetchall()]
    info = {c: (sec, sh) for c, sec, sh in dm.execute("SELECT code, sector, listed_shares FROM stocks").fetchall()}
    rows = []
    for d in days:
        pd_ = max(x for x in all_days if x < d)
        uni = {c: (cl, val) for c, cl, val in dm.execute(
            "SELECT code, close, value FROM (SELECT code, close, value, rank() OVER (ORDER BY value DESC) rk FROM daily_ohlcv "
            "WHERE date = ? AND value > 0) WHERE rk <= ?", [pd_, top]).fetchall()}
        hist = defaultdict(list)
        for c, dd, cl, val in dm.execute("SELECT code, date, close, value FROM daily_ohlcv WHERE date < ? AND date >= ? - INTERVAL 40 DAY "
                                         "ORDER BY date", [d, d]).fetchall():
            if c in uni:
                hist[c].append((cl, val))
        by = defaultdict(list)
        for r in m.execute("SELECT code, ts, open, high, low, close, volume FROM minute_ohlcv WHERE ts::date = ? "
                           "AND ts::time BETWEEN TIME '09:00' AND TIME '15:19' ORDER BY code, ts", [d]).fetchall():
            if r[0] in uni:
                by[r[0]].append(dict(ts=r[1], open=r[2], high=r[3], low=r[4], close=r[5], volume=r[6]))
        by = {c: b for c, b in by.items() if len(b) > 100 and b[0]["ts"].time() <= time(9, 2)}
        if len(by) < 50:
            continue
        tsl = {c: [b["ts"] for b in bs] for c, bs in by.items()}
        cum = {}
        for c, bs in by.items():
            acc, cs = 0.0, []
            for b in bs:
                acc += b["volume"] * (b["high"] + b["low"] + b["close"]) / 3
                cs.append(acc)
            cum[c] = cs
        for T in TS:
            k_of = {c: bisect.bisect_left(tsl[c], __import__("datetime").datetime.combine(d, T)) for c in by}
            cv = {c: (cum[c][k_of[c] - 1] if k_of[c] > 0 else 0.0) for c in by}
            order = sorted(cv, key=cv.get, reverse=True)
            rank = {c: i + 1 for i, c in enumerate(order)}
            above = {c: by[c][k_of[c] - 1]["close"] > by[c][0]["open"] for c in by if k_of[c] > 0}
            breadth = sum(above.values()) / max(len(above), 1)
            sec_up = defaultdict(list)
            for c, a in above.items():
                sec_up[(info.get(c) or ("?", 0))[0]].append(a)
            for c, bs in by.items():
                k = k_of[c]
                if k < 20 or k >= len(bs) - 1:
                    continue
                prev = uni[c][0]
                f = features(bs[:k], prev)
                if not f or f["chg"] < 0.03 or rank[c] > 100:
                    continue
                h = hist.get(c, [])
                avg20 = sum(v or 0 for _, v in h[-20:]) / max(len(h[-20:]), 1)
                up = bs[:k]
                pv = vv = 0.0
                for b in up:
                    tp = (b["high"] + b["low"] + b["close"]) / 3
                    pv += tp * b["volume"]; vv += b["volume"]
                vw = pv / vv if vv else up[-1]["close"]
                cl = [b["close"] for b in up]
                ma20 = sum(cl[-20:]) / 20
                last10 = cv[c] - (cum[c][k - 11] if k > 10 else 0)
                first10 = cum[c][min(9, k - 1)]
                buy = bs[k]["open"]
                ret = bs[-1]["close"] / buy - 1 - COST
                sec = (info.get(c) or ("?", 0))[0]
                rows.append(dict(
                    date=d, T=T, code=c, ret=ret, strong=ret >= 0.02,
                    rank=rank[c], chg=f["chg"], gap=f["gap"], from_open=f["from_open"], eff=f["eff"],
                    vwap_share=f["vwap_share"], new_highs=f["new_highs"], pull=f["pull"],
                    vs_vwap=up[-1]["close"] / vw - 1, vs_ma20=up[-1]["close"] / ma20 - 1,
                    from_high=up[-1]["close"] / max(b["high"] for b in up) - 1,
                    value_vs_avg=cv[c] / avg20 if avg20 else 0.0,
                    accel=last10 / max(first10, 1),          # 최근 10분 대금 ÷ 첫 10분 대금 (돈이 계속 들어오나)
                    prev_chg=prev / h[-2][0] - 1 if len(h) >= 2 else 0.0,
                    prev_rank=sorted(uni, key=lambda x: -(uni[x][1] or 0)).index(c) + 1,
                    breadth=breadth, sector_up=sum(sec_up[sec]) / max(len(sec_up[sec]), 1),
                    mcap=(info.get(c) or ("?", 0))[1] * prev / 1e12 if (info.get(c) or ("?", 0))[1] else 0.0,
                ))
    return rows


FEATS = ["rank", "chg", "gap", "from_open", "eff", "vwap_share", "new_highs", "pull", "vs_vwap", "vs_ma20", "from_high",
         "value_vs_avg", "accel", "prev_chg", "prev_rank", "breadth", "sector_up", "mcap"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="")
    ap.add_argument("--since", default="2025-10-15")
    ap.add_argument("--top", type=int, default=200)
    a = ap.parse_args()
    m = duckdb.connect(a.db or _copy(os.path.join(PROJECT_ROOT, "data", "minute_history.duckdb")), read_only=True)
    dm = duckdb.connect(_copy(os.path.join(PROJECT_ROOT, "data", "daily_ohlcv.duckdb")), read_only=True)
    days = [r[0] for r in m.execute("SELECT DISTINCT ts::date FROM minute_ohlcv WHERE ts::date >= ? ORDER BY 1",
                                    [date.fromisoformat(a.since)]).fetchall()]
    rows = collect(m, dm, days, a.top)
    used = sorted({r["date"] for r in rows})
    half = used[len(used) // 2]
    print(f"'끝까지 가는 종목' 판별 — {used[0]}~{used[-1]} ({len(used)}일), 전날 대금 상위 {a.top}, 앞/뒤 나눔 {half}")
    for T in TS:
        R = [r for r in rows if r["T"] == T]
        A = [r for r in R if r["date"] < half]
        B = [r for r in R if r["date"] >= half]
        print(f"\n===== 판정 {T:%H:%M}: 후보 {len(R)}건 (하루 {len(R) / len(used):.1f}건), 평균 {sum(r['ret'] for r in R) / len(R):+.2%}, "
              f"끝까지 강함(+2%↑) {sum(r['strong'] for r in R) / len(R):.0%}")
        print("  특징          AUC 앞  AUC 뒤 | 다섯 구간 평균 수익률 (낮은 값 → 높은 값)")
        ranked = []
        for k in FEATS:
            aa = auc([r[k] for r in A if r["strong"]], [r[k] for r in A if not r["strong"]])
            ab = auc([r[k] for r in B if r["strong"]], [r[k] for r in B if not r["strong"]])
            xs = sorted(R, key=lambda r: r[k])
            q = [xs[i * len(xs) // 5:(i + 1) * len(xs) // 5] for i in range(5)]
            qs = " ".join(f"{sum(r['ret'] for r in g) / len(g):+.2%}" for g in q if g)
            same = (aa - 0.5) * (ab - 0.5) > 0
            ranked.append((abs(aa - 0.5) if same else 0, k, aa, ab))
            print(f"  {k:12} {aa:6.2f} {ab:6.2f} {'✓' if same and abs(aa - 0.5) >= 0.05 and abs(ab - 0.5) >= 0.05 else ' '} | {qs}")
        # 걷기 앞 검증: 앞 절반에서 가장 좋은 조합(상위 특징 4개 중 2~3개, 각 특징의 앞 절반 상위/하위 40% 경계)
        tops = [k for s, k, aa, ab in sorted(ranked, reverse=True)[:4] if s > 0]
        best = None
        for n in (1, 2, 3):
            for combo in itertools.combinations(tops, n):
                conds = []
                for k in combo:
                    vals = sorted(r[k] for r in A)
                    aa = next(x[2] for x in ranked if x[1] == k)
                    cut = vals[int(len(vals) * (0.6 if aa > 0.5 else 0.4))]
                    conds.append((k, ">=" if aa > 0.5 else "<=", cut))
                sel = lambda r: all((r[k] >= c) if op == ">=" else (r[k] <= c) for k, op, c in conds)
                sa = [r["ret"] for r in A if sel(r)]
                if len(sa) < 20:
                    continue
                score = sum(sa) / len(sa)
                if best is None or score > best[0]:
                    best = (score, conds, sel)
        if best:
            score, conds, sel = best
            sb = [r["ret"] for r in B if sel(r)]
            desc = " 그리고 ".join(f"{k} {op} {c:.3g}" for k, op, c in conds)
            print(f"  ▶ 앞 절반 최선 규칙: {desc}")
            print(f"     앞 절반 {sum(1 for r in A if sel(r))}건 평균 {score:+.2%} | 뒤 절반(처음 보는 기간) {len(sb)}건 평균 "
                  f"{(sum(sb) / len(sb)) if sb else 0:+.2%} 승률 {(sum(1 for x in sb if x > 0) / len(sb)) if sb else 0:.0%} "
                  f"(뒤 절반 후보 전체 {sum(r['ret'] for r in B) / max(len(B), 1):+.2%})")


if __name__ == "__main__":
    main()
