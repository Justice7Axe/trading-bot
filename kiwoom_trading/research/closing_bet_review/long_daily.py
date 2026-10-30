"""종가배팅 긴 기간 검증 (개선 후보 1) — 일봉만으로 'D 종가 → D+1 시가' (2024-10 ~ 2026-10).

일봉(daily_day: 수정주가, 9-14 뒤는 1분봉으로 정규장 값으로 바꿈)만 쓴다 → 같은 수정 기준끼리라 비율이 맞다.
  대상: D일 대금 상위 N(주식, stocks 표) · 상승 마감(0 < 등락 < +29.5%). 수익 = D+1 시가 ÷ D 종가 − 1 − 0.25%.
  9-14 뒤 1분봉이 없어 정규장 값으로 못 바꾼 종목·일(UNSURE)은 뺀다 (종가가 20:00 애프터 종가라서).
  기간: A 2024-10-14 ~ 2025-10-15 (처음 보는 기간, 1분봉 없음) / B 2025-10-16 ~ (지금까지 본 1년).
한계: stocks 표가 지금 목록이면 그사이 상장 폐지 종목이 빠진다(생존 편향) — delisted 칸 확인해 표시.
출력: data/closing_bet_review/long_daily.txt, long_daily.pkl
"""
import os
import pickle
from collections import defaultdict
from datetime import date

import numpy as np

from kiwoom_trading.backtest import engine as E

OUT = os.path.join(E.DATA, "closing_bet_review")
SPLIT_B = date(2025, 10, 16)
# 처음 보는 기간에도 쓸 '시장 상황': 코스피 전날 종가의 52주(250일) 고점 대비 (장 전에 앎)
KD = sorted(E.KOSPI)


def dd52(d):
    i = KD.index(d) if d in E.KOSPI else None
    if not i or i < 2:
        return None
    w = [E.KOSPI[x] for x in KD[max(0, i - 251):i]]
    return E.KOSPI[KD[i - 1]] / max(w) - 1


def main():
    rep = open(os.path.join(OUT, "long_daily.txt"), "w", encoding="utf-8")

    def say(s=""):
        print(s); rep.write(s + "\n"); rep.flush()

    n_del = E.DM.execute("SELECT count(*), sum(CASE WHEN delisted THEN 1 ELSE 0 END) FROM stocks").fetchone()
    say(f"stocks 표 {n_del[0]}종목 중 delisted 표시 {n_del[1]} → 0 이면 상장 폐지 종목은 빠져 있음(생존 편향)")
    rows = []
    for d in E.CAL:
        nd = E.next_day(d)
        if nd is None or d < date(2024, 10, 14):
            continue
        today, prev, nxt = E.daily_day(d), E.daily_day(E.prev_day(d)), E.daily_day(nd)
        vals = sorted(((c, r[5] or 0) for c, r in today.items() if r[5]), key=lambda x: -x[1])[:200]
        kc = E.kospi_chg(d)
        for rk, (c, _) in enumerate(vals, 1):
            if c not in prev or c not in nxt or not prev[c][3] or not today[c][3]:
                continue
            if (c, d) in E.UNSURE or (c, nd) in E.UNSURE:
                continue
            ch = today[c][3] / prev[c][3] - 1
            o = nxt[c][0]
            if not o:
                continue
            r = o / today[c][3] - 1 - E.COST
            if abs(r) > 0.35:
                continue
            hi, lo = today[c][1], today[c][2]
            rows.append(dict(date=d, code=c, rk=rk, chg=ch, ret=r, pos=(today[c][3] - lo) / (hi - lo) if hi > lo else 1.0,
                             kospi=kc, common=E.is_common(c)))
    pickle.dump(rows, open(os.path.join(OUT, "long_daily.pkl"), "wb"))
    say(f"자료 {len(rows):,}건, {rows[0]['date']} ~ {rows[-1]['date']}")

    def stats(tr, title):
        if len(tr) < 15:
            say(f"  {title:40s} {len(tr)}건"); return
        ds = sorted({d for d, _ in tr}); h = ds[len(ds) // 2]
        v = np.array([x for _, x in tr]); a = [x for d, x in tr if d < h]; b = [x for d, x in tr if d >= h]
        bd = defaultdict(float)
        for d, x in tr: bd[d] += x
        s = sorted(bd.values(), reverse=True)
        eq = np.cumsum([bd[d] for d in sorted(bd)]); mdd = (np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()
        ok = "★" if np.mean(a) > 0 and np.mean(b) > 0 and sum(s[5:]) > 0 else " "
        say(f" {ok}{title:40s} {len(v):5d}건 {len(bd):3d}일 건당 {v.mean():+.2%} 합계 {v.sum() * 100:+6.0f}만 최고5일 빼면 {sum(s[5:]) * 100:+6.0f}만"
            f" | 앞 {np.mean(a):+.2%} 뒤 {np.mean(b):+.2%} | 승률 {np.mean(v > 0):.0%} 낙폭 {mdd * 100:.0f}만")

    periods = {"A 2024-10~2025-10 (처음 보는 기간)": lambda d: d < SPLIT_B, "B 2025-10~2026-10 (본 기간)": lambda d: d >= SPLIT_B}
    for pn, pf in periods.items():
        say(f"\n== {pn}")
        for N in (5, 10, 20, 30, 200):
            stats([(r["date"], r["ret"]) for r in rows if pf(r["date"]) and r["rk"] <= N and 0 < r["chg"] < E.LIMIT], f"대금 {N}위 · 상승 마감")
        stats([(r["date"], r["ret"]) for r in rows if pf(r["date"]) and r["rk"] <= 10 and r["chg"] <= 0], "대금 10위 · 하락 마감")
        stats([(r["date"], r["ret"]) for r in rows if pf(r["date"]) and r["rk"] <= 10 and 0 < r["chg"] < E.LIMIT and r["common"]], "대금 10위 · 상승 · 우선주 제외")
        stats([(r["date"], r["ret"]) for r in rows if pf(r["date"]) and r["rk"] <= 10 and 0 < r["chg"] < E.LIMIT and r["pos"] >= 0.8], "대금 10위 · 상승 · 고가 부근(≥0.8)")
        stats([(r["date"], r["ret"]) for r in rows if pf(r["date"]) and r["rk"] <= 200], "대금 200 전체 (밤사이 바탕)")
    say("\n== 분기별 · 대금 10위 · 상승 마감 (건당 / 건수) — 대금 200 전체와 비교")
    q = defaultdict(list); qa = defaultdict(list)
    for r in rows:
        k = f"{r['date'].year}Q{(r['date'].month - 1) // 3 + 1}"
        if r["rk"] <= 10 and 0 < r["chg"] < E.LIMIT: q[k].append(r["ret"])
        qa[k].append(r["ret"])
    for k in sorted(q):
        say(f"  {k}: {np.mean(q[k]):+.2%} ({len(q[k])}건) | 대금 200 전체 {np.mean(qa[k]):+.2%} | 차이 {np.mean(q[k]) - np.mean(qa[k]):+.2%}p")
    say("\n== 코스피 52주 고점 대비 (전날, 장 전 앎) · 대금 10위 · 상승 — 두 기간 합쳐")
    for lo, hi, nm in ((-1, -0.20, "−20%↓ (깊은 약세)"), (-0.20, -0.10, "−20~−10% (약세)"), (-0.10, -0.03, "−10~−3%"), (-0.03, 1, "고점 근처 −3% 안")):
        stats([(r["date"], r["ret"]) for r in rows if r["rk"] <= 10 and 0 < r["chg"] < E.LIMIT and (x := dd52(r["date"])) is not None and lo < x <= hi], nm)
    say("\n== 그날 코스피 등락 (종가, 장 마감에 앎) · 대금 10위 · 상승 — 두 기간 합쳐")
    for lo, hi, nm in ((-1, -0.015, "코스피 −1.5%↓"), (-0.015, 0, "−1.5~0%"), (0, 0.015, "0~+1.5%"), (0.015, 1, "+1.5%↑")):
        stats([(r["date"], r["ret"]) for r in rows if r["rk"] <= 10 and 0 < r["chg"] < E.LIMIT and r["kospi"] is not None and lo < r["kospi"] <= hi], nm)


if __name__ == "__main__":
    main()
