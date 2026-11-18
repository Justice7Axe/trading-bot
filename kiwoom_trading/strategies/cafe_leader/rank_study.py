"""☕ 대장 = 테마 안 등락률 1등 + 거래대금 순위권 한정 — 1년 검증 (2026-11-18 사용자: "대장주를 등락률이 높은 것으로 하는 것에다,
어느 정도 거래대금이 전 거래일 또는 당일 거래대금 순위권에 있는 종목에 한한 것으로 해줘").

exit_study.py 와 같은 매수 자리(③ 프리장 50억↑, 1분봉 당일 고점 돌파+햄버거 → 돌파 고점 눌림 지정가 10분, 종목당 하루 첫 돌파만,
매도 절반 +2.5% · 나머지 상한가 · −2% 손절 즉시 · 아니면 다음 날 09:00, 비용 0.25%)에서 ① 대장 정의만 바꿔 비교한다.
  base   : 지금 규칙 — 대상 전날 대금 200위(일봉 대금), 그 안에서 테마 +4%↑ 2종목↑ 중 누적 대금 1위 (exit_study 와 같은 목록)
  chgN   : 대상 = 그날 1분봉이 있는 종목 전부. 테마 형성(+4%↑ 2종목↑)은 누적 대금 10억↑ 종목 전부로 세고,
           대장 = 그중 '전 거래일 정규장 대금 N위 안' 또는 '그 시각 당일 누적(통합) 대금 N위 안' 종목만 놓고 등락률 1등
           (+29.5%↑ 끼리는 대금 순, +5%↑, 신규 상장 20거래일 안 제외) — live.top_by_chg 와 같은 함수.
  전 거래일 정규장 대금: 2026-09-14 뒤는 data/daily_regular.duckdb(1분봉 09:00~15:30), 그 전은 일봉 대금(그땐 정규장 값).
  당일 누적 대금 순위: 그 시각까지 통합 1분봉 대금(프리장 포함) — 그날 1분봉이 있는 종목(대금 상위 약 500 + 장중 +15%↑) 안에서 매김.
    그날 상위 500 밖으로 끝난 종목이 장중 한때 N위 안이었던 경우는 빠짐(드묾) → 근사.
계좌: exit_study.account (하루 3종목·잔고÷3·복리, 1주가 몫보다 비싸면 못 삼).

실행: .venv/Scripts/python.exe -m kiwoom_trading.strategies.cafe_leader.rank_study [--report-only]  → data/cafe/rank_study.txt, rank_study.pkl
"""
from __future__ import annotations

import datetime as _dt
import os
import pickle
import sys
from collections import defaultdict
from datetime import time

import duckdb
import numpy as np

from kiwoom_trading.backtest import engine as E
from kiwoom_trading.strategies.cafe_leader import backtest as B
from kiwoom_trading.strategies.cafe_leader import exit_study as X
from kiwoom_trading.strategies.cafe_leader.live import NEW_LISTING_DAYS, top_by_chg

OUT = os.environ.get("CAFE_STUDY_OUT", B.OUT)   # 장중 자료 보호 시 스크래치로
os.makedirs(OUT, exist_ok=True)
NS = (50, 100, 200)
MEMBER_VALUE = 1e9          # 테마 형성에 세는 종목: 누적 대금 10억↑ (live 👑 의 등락률 상위 조건과 같음)
CHASE = 0.15

try:
    RG = duckdb.connect(E._cp("daily_regular.duckdb"), read_only=True)
except Exception as exc:       # 없으면 9-14 뒤도 일봉(통합) 대금으로 — 결과에 표시
    print(f"[rank_study] daily_regular 없음: {exc}", file=sys.stderr)
    RG = None
LIST_DATE = dict(E.DM.execute("SELECT code, list_date FROM stocks WHERE list_date IS NOT NULL").fetchall())


def prev_regular_rank(p) -> dict:
    """전 거래일 정규장 거래대금 순위 {code: 순위}."""
    if p >= E.NXT_SWITCH and RG is not None:
        rows = RG.execute("SELECT code, value FROM daily_regular WHERE date = ? AND value IS NOT NULL ORDER BY value DESC", [p]).fetchall()
        if rows:
            return {c: i + 1 for i, (c, _) in enumerate(rows)}
    return E.value_rank(p)


def new_listed(c, d) -> bool:
    ld = LIST_DATE.get(c)
    if ld is None or ld > d:
        return ld is not None
    i0, i1 = E.CIDX.get(ld), E.CIDX.get(d)
    if i1 is None:
        return False
    if i0 is None:
        i0 = next((i for i, x in enumerate(E.CAL) if x >= ld), i1)
    return i1 - i0 + 1 <= NEW_LISTING_DAYS


def day_trades(d):
    p = E.prev_day(d)
    vr = E.value_rank(p)
    prk = prev_regular_rank(p)
    pd_ = E.daily_day(p)
    codes = [c for c in E._min_codes(d) if E.is_common(c) and c in pd_]
    U200 = {c for c, r in vr.items() if r <= 200 and E.is_common(c) and c in pd_}
    codes = sorted(set(codes) | U200)
    Bd = E.load_day(codes, d)
    info = {}
    for c in codes:
        b = Bd[c]
        reg = E.regular(b)
        if len(reg) < 60:
            continue
        f = E.factor(c, d)
        if not f:
            continue
        pre = [x for x in b if x[0] < time(9, 0)]
        info[c] = dict(reg=reg, pre=pre, pc=pd_[c][3] * f, prev=sum(B.val(x) for x in pre))
    if not info:
        return []
    # 분 격자 09:00~10:30: 종목별 그 분까지 마지막 종가·누적 대금(프리장 포함)
    grid = [time(9 + m // 60, m % 60) for m in range(0, 91)]
    gi = {t: i for i, t in enumerate(grid)}
    cl = list(info)
    ci = {c: i for i, c in enumerate(cl)}
    CH = np.full((len(cl), len(grid)), np.nan)
    CV = np.zeros((len(cl), len(grid)))
    for c, v in info.items():
        i = ci[c]
        cum, last, k = v["prev"], None, 0
        reg = v["reg"]
        for g, t in enumerate(grid):
            while k < len(reg) and reg[k][0] <= t:
                cum += B.val(reg[k])
                last = reg[k][4]
                k += 1
            CV[i, g] = cum
            if last is not None:
                CH[i, g] = last / v["pc"] - 1
    themes = {c: B.THEME.get(c, set()) for c in cl}
    newl = {c for c in cl if new_listed(c, d)}
    cache = {}

    def chg_leaders(g):
        if g in cache:
            return cache[g]
        order = np.argsort(-CV[:, g])
        trank = {cl[i]: r + 1 for r, i in enumerate(order)}
        rows = [(c, float(CH[ci[c], g]), float(CV[ci[c], g])) for c in cl
                if c not in newl and not np.isnan(CH[ci[c], g]) and CV[ci[c], g] >= MEMBER_VALUE]
        out = {}
        for n in NS:
            elig = {c for c, _, _ in rows if prk.get(c, 10**6) <= n or trank[c] <= n}
            out[n] = (top_by_chg(rows, themes, eligible=elig), trank)
        cache[g] = out
        return out

    info200 = {c: v for c, v in info.items() if c in U200}
    out = []
    for c, v in info.items():
        reg, pc = v["reg"], v["pc"]
        if v["prev"] < B.PRE_VALUE:
            continue
        hi = None
        for j, x in enumerate(reg):
            t = x[0]
            if t > B.LAST_BUY:
                break
            if hi is not None and j >= 3 and x[4] > hi and x[4] > x[1]:
                prev5 = [B.val(y) for y in reg[max(0, j - 5):j]]
                bv = B.val(x)
                if bv >= B.BAR_VALUE and bv >= B.BAR_MULT * (np.mean(prev5) if prev5 else 0) and j + 1 < len(reg):
                    flags = {}
                    if c in U200:
                        flags["base"] = B.leader_at(c, d, t, info200, by="value")[0]
                    g = gi.get(t)
                    if g is not None:
                        L = chg_leaders(g)
                        for n in NS:
                            flags[f"chg{n}"] = c in L[n][0]
                        trank = L[NS[0]][1].get(c)
                    else:
                        trank = None
                    if any(flags.values()):
                        fill = None
                        for k in range(j + 1, min(j + 11, len(reg))):
                            if reg[k][3] <= hi:
                                fill = (k, min(reg[k][1], hi))
                                break
                        if fill:
                            r, _ = X.exit_var(c, d, reg, fill[0], fill[1], pc, 0.02, False)
                            out.append(dict(code=c, date=d, t=t, fill_t=reg[fill[0]][0], buy=fill[1], chg=fill[1] / pc - 1,
                                            ret=r, flags=flags, prev_rank=prk.get(c), today_rank=trank, in200=c in U200))
                    break      # 종목당 하루 첫 돌파만 (backtest.py·exit_study 와 같음)
            hi = x[2] if hi is None else max(hi, x[2])
    return out


def run():
    allt = []
    for i, d in enumerate(E.days()):
        allt += day_trades(d)
        if i % 20 == 0:
            print(f"  {d} 누적 {len(allt)}", file=sys.stderr, flush=True)
    with open(os.path.join(OUT, "rank_study.pkl"), "wb") as f:
        pickle.dump(allt, f)
    return allt


def report(allt):
    R = B.Rep(os.path.join(OUT, "rank_study.txt"))
    days = E.days()
    R.say(f"☕ 대장 = 등락률 1등 + 대금 순위권(전 거래일 정규장 N위 또는 당일 누적 N위) — ①③⑥ 눌림 지정가 1년 ({days[0]} ~ {days[-1]})")
    R.say("1건 100만 기준 '만'. ★ = 앞·뒤 반 모두 + & 최고 5일 빼도 +. 계좌 = 하루 3종목·잔고÷3·복리, 매수 시각 순서\n")
    for t in allt:
        t[(0.02, False)] = t["ret"]

    def line(name, ts):
        R.stats([(t["date"], t["ret"]) for t in ts if t["ret"] is not None], name, 50)
        a10, m10, n10 = X.account(ts, (0.02, False), 100_000)
        a100, m100, n100 = X.account(ts, (0.02, False), 1_000_000)
        R.say(f"      계좌 10만 → {a10:,.0f} (낙폭 {m10:.0%}, {n10}건) · 100만 → {a100:,.0f} (낙폭 {m100:.0%}, {n100}건)")

    keys = [("base", "지금: 전날 200위 안 테마 대금 1위"), *((f"chg{n}", f"등락률 1등 · 대금 {n}위 안(전날 정규장 또는 당일)") for n in NS)]
    rec0 = _dt.date(2026, 8, 1)
    for title, f in (("## 1. 추격 금지 없음", lambda t: True), ("## 2. 추격 금지 +15% (지금 규칙)", lambda t: t["chg"] <= CHASE)):
        R.say(title)
        for k, name in keys:
            line(name, [t for t in allt if t["flags"].get(k) and f(t)])
        R.say("")
    R.say("## 3. 최근 석 달 (2026-08 뒤, 추격 금지 +15%)")
    for k, name in keys:
        line("[최근] " + name, [t for t in allt if t["flags"].get(k) and t["chg"] <= CHASE and t["date"] >= rec0])
    R.say("\n## 4. 어디서 들어왔나 (추격 금지 +15%)")
    for n in NS:
        ts = [t for t in allt if t["flags"].get(f"chg{n}") and t["chg"] <= CHASE]
        line(f"chg{n} 중 전날 정규장 {n}위 안", [t for t in ts if (t["prev_rank"] or 10**6) <= n])
        line(f"chg{n} 중 당일 순위로만 들어옴", [t for t in ts if (t["prev_rank"] or 10**6) > n])
        line(f"chg{n} 중 지금 규칙(base)과 겹침", [t for t in ts if t["flags"].get("base")])
        line(f"chg{n} 중 새로 생긴 것(base 아님)", [t for t in ts if not t["flags"].get("base")])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if "--report-only" in sys.argv:
        with open(os.path.join(OUT, "rank_study.pkl"), "rb") as f:
            report(pickle.load(f))
        return
    report(run())


if __name__ == "__main__":
    main()
