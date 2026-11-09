"""1) 가설 검증: 전날 코스피 급락 → 다음 날 반등하나 (지수 일봉 4년 + 지수 1분봉 1년 + 대용 인버스 모든 날).

실행: PYTHONPATH=. .venv/Scripts/python.exe -m kiwoom_trading.research.inverse_after_drop.hypothesis
결과: data/inverse_after_drop/hypothesis.txt
"""
import os
import sys
from datetime import date, time

import numpy as np

from kiwoom_trading.research.inverse_after_drop import common as C

rep = open(os.path.join(C.OUT, "hypothesis.txt"), "w", encoding="utf-8")


def say(s=""):
    print(s); rep.write(s + "\n"); rep.flush()


BINS = [("≤ −5%", -9, -0.05), ("−5 ~ −3%", -0.05, -0.03), ("−3 ~ −2%", -0.03, -0.02), ("−2 ~ −1%", -0.02, -0.01),
        ("−1 ~ 0%", -0.01, 0.0), ("0 ~ +1%", 0.0, 0.01), ("+1 ~ +2%", 0.01, 0.02), ("> +2%", 0.02, 9)]
CUM = [("≤ −1%", -0.01), ("≤ −2%", -0.02), ("≤ −3%", -0.03), ("≤ −5%", -0.05)]


def m(xs):
    return f"{np.mean(xs):+.2%}" if xs else "   —  "


def up(xs):
    return f"{np.mean(np.array(xs) > 0):.0%}" if xs else "—"


def daily_rows(code):
    D = C.idx_daily(code)
    rows = []
    for i in range(2, len(D)):
        p2, p1, t = D[i - 2], D[i - 1], D[i]
        rows.append(dict(date=t["date"], prev=p1["close"] / p2["close"] - 1, prev_oc=p1["close"] / p1["open"] - 1,
                         prev_gap=p1["open"] / p2["close"] - 1,
                         gap=t["open"] / p1["close"] - 1, oc=t["close"] / t["open"] - 1, cc=t["close"] / p1["close"] - 1,
                         lo=t["low"] / t["open"] - 1, hi=t["high"] / t["open"] - 1,
                         nxt=(D[i + 1]["open"] / t["open"] - 1) if i + 1 < len(D) else None))
    return rows


def table(rows, title):
    say(f"\n### {title} ({len(rows)}일, {rows[0]['date']} ~ {rows[-1]['date']})")
    say("  전날 코스피     |  날 | 다음 날 시가 갭 (상승%) | 시가→종가 (상승%) | 종가→종가 (상승%) | 시가→다음 날 시가")
    for lab, lo, hi in BINS:
        g = [r for r in rows if lo < r["prev"] <= hi]
        say(f"  {lab:14s} | {len(g):3d} | {m([r['gap'] for r in g])} ({up([r['gap'] for r in g]):>4s})        "
            f"| {m([r['oc'] for r in g])} ({up([r['oc'] for r in g]):>4s})  | {m([r['cc'] for r in g])} ({up([r['cc'] for r in g]):>4s})  "
            f"| {m([r['nxt'] for r in g if r['nxt'] is not None])}")
    say("  -- 누적")
    for lab, th in CUM:
        g = [r for r in rows if r["prev"] <= th]
        say(f"  {lab:14s} | {len(g):3d} | {m([r['gap'] for r in g])} ({up([r['gap'] for r in g]):>4s})        "
            f"| {m([r['oc'] for r in g])} ({up([r['oc'] for r in g]):>4s})  | {m([r['cc'] for r in g])} ({up([r['cc'] for r in g]):>4s})  "
            f"| {m([r['nxt'] for r in g if r['nxt'] is not None])}")
    g = rows
    say(f"  {'전체':14s} | {len(g):3d} | {m([r['gap'] for r in g])} ({up([r['gap'] for r in g]):>4s})        "
        f"| {m([r['oc'] for r in g])} ({up([r['oc'] for r in g]):>4s})  | {m([r['cc'] for r in g])} ({up([r['cc'] for r in g]):>4s})  "
        f"| {m([r['nxt'] for r in g if r['nxt'] is not None])}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    say("# 가설: 전날 급락 → 다음 날 기계적 반등?")
    for code, nm in (("001", "코스피"), ("101", "코스닥")):
        rows = daily_rows(code)
        if code == "101":     # 코스닥도 '전날 코스피' 기준으로 나눔
            kp = {r["date"]: r["prev"] for r in daily_rows("001")}
            rows = [dict(r, prev=kp[r["date"]]) for r in rows if r["date"] in kp]
        say(f"\n## {nm} 일봉 — 전날 코스피 등락 구간별 그날 {nm}")
        table(rows, "4년 전체")
        h = len(rows) // 2
        table(rows[:h], "앞 반")
        table(rows[h:], "뒤 반")
        table([r for r in rows if r["date"] >= date(2025, 10, 15)], "최근 1년 (인버스 백테스트 기간)")

    # 아침 급락 vs 오후 급락 (전날 −2%↓ 중)
    rows = daily_rows("001")
    say("\n## 전날 −2%↓ 급락을 '어떻게 빠졌나' 로 나눔 (코스피, 4년) — 전날 시가 갭 vs 전날 시가→종가")
    for lab, f in (("갭으로 빠짐 (전날 시가→종가 ≥ −1%)", lambda r: r["prev_oc"] >= -0.01),
                   ("장중에 빠짐 (전날 시가→종가 < −1%)", lambda r: r["prev_oc"] < -0.01)):
        g = [r for r in rows if r["prev"] <= -0.02 and f(r)]
        say(f"  {lab:34s} {len(g):3d}일 | 갭 {m([r['gap'] for r in g])} ({up([r['gap'] for r in g])}) | 시가→종가 {m([r['oc'] for r in g])} "
            f"({up([r['oc'] for r in g])}) | 종가→종가 {m([r['cc'] for r in g])} ({up([r['cc'] for r in g])})")

    # 연속 급락
    say("\n## 이틀 연속 하락 뒤 (코스피, 4년)")
    D = C.idx_daily("001")
    ret = {D[i]["date"]: D[i]["close"] / D[i - 1]["close"] - 1 for i in range(1, len(D))}
    ds = [x["date"] for x in D]
    for lab, f in (("전날 −2%↓ & 그 전날도 −", lambda a, b: a <= -0.02 and b < 0), ("전날 −2%↓ & 그 전날 +", lambda a, b: a <= -0.02 and b >= 0)):
        g = [r for r in rows if r["date"] in ds and ds.index(r["date"]) >= 3 and f(r["prev"], ret[ds[ds.index(r["date"]) - 2]])]
        say(f"  {lab:24s} {len(g):3d}일 | 갭 {m([r['gap'] for r in g])} | 시가→종가 {m([r['oc'] for r in g])} | 종가→종가 {m([r['cc'] for r in g])} ({up([r['cc'] for r in g])})")

    # 장중 (1분봉 1년): 09:00→09:11, 09:11→종가, 09:11→다음날 시가, 09:11 뒤 최고/최저
    say("\n## 장중 코스피 (지수 1분봉 2025-10 ~ 2026-11-06) — 전날 코스피 구간별")
    KM = C.idx_min("001"); KD = {r["date"]: r for r in C.idx_daily("001")}; kd = sorted(KD)
    rows2 = []
    for i, d in enumerate(kd):
        if d not in KM or i < 1:
            continue
        bs = KM[d]; p = KD[kd[i - 1]]
        prev = p["close"] / KD[kd[i - 2]]["close"] - 1 if i >= 2 else None
        b11 = next((b for b in bs if b["ts"].time() >= time(9, 11)), None)
        b30 = next((b for b in bs if b["ts"].time() >= time(9, 30)), None)
        if not b11 or prev is None:
            continue
        e = b11["open"]; after = [b for b in bs if time(9, 11) <= b["ts"].time() < time(15, 20)]
        o = KD[d]["open"]
        no = KD[kd[i + 1]]["open"] if i + 1 < len(kd) else None
        rows2.append(dict(date=d, prev=prev, a=e / o - 1, b=KD[d]["close"] / e - 1, c=(no / e - 1) if no else None,
                          hi=max(x["high"] for x in after) / e - 1, lo=min(x["low"] for x in after) / e - 1, d30=b30["open"] / e - 1 if b30 else None))
    say("  전날 코스피     |  날 | 09:00→09:11 | 09:11→09:30 | 09:11→종가 (상승%) | 09:11→다음 날 시가 | 09:11 뒤 최고 / 최저 (평균)")
    for lab, lo, hi in BINS + [("≤ −2% 누적", -9, -0.02), ("≤ −3% 누적", -9, -0.03), ("전체", -9, 9)]:
        g = [r for r in rows2 if lo < r["prev"] <= hi]
        if not g:
            continue
        say(f"  {lab:14s} | {len(g):3d} | {m([r['a'] for r in g])}     | {m([r['d30'] for r in g if r['d30'] is not None])}     "
            f"| {m([r['b'] for r in g])} ({up([r['b'] for r in g]):>4s}) | {m([r['c'] for r in g if r['c'] is not None])}           "
            f"| {m([r['hi'] for r in g])} / {m([r['lo'] for r in g])}")
    say("  (인버스는 이 값의 반대로 움직임: 09:11→종가가 + 면 인버스 손실)")

    # 모든 날 대용 인버스로 ⑤ 규칙 (09:11, +5/−3, 다음 날 09:00) — 시장 상황 상관없이 전날 구간별
    say("\n## 모든 날 인버스 ⑤ 규칙 재현 (09:11 매수 +5% 익절 / −3% 손절 / 다음 날 09:00, 실제 인버스 1분봉 우선·없으면 대용) — 시장 상황 무관")
    tr = []
    for r in rows2:
        x, src, _ = C.trade(r["date"])
        if x is not None:
            tr.append((r["date"], r["prev"], x))
    for lab, lo, hi in BINS + [("≤ −2% 누적", -9, -0.02), ("≤ −3% 누적", -9, -0.03), ("전체", -9, 9)]:
        g = [(d, x) for d, p, x in tr if lo < p <= hi]
        say(f"  {lab:14s} {C.fmt(C.summ(g))}")


if __name__ == "__main__":
    main()
